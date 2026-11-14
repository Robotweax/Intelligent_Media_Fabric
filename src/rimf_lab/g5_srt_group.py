"""G5 SRT-group comparison, stage 1: one SRT connection group over two routed paths.

Four namespaces form the faulted diamond's topology (a-r1-b / a-r2-b) without FIPS: the
transits forward IPv6 in the kernel and static routes send each member over its own transit. The SRT
Telemetry incident peer on `a` opens a Broadcast or Backup group with one member per
transit to the peer on `b`. The faulted diamond's fixture, source, collector, decode and
frame comparison are reused unchanged. The coordinator samples the group and each member
on both endpoints on one monotonic clock and blackholes transit `r1`, the faster path.

The result is ordering-only and records `G5: not-passed`. It reports what the downstream
collector saw; it applies ADR-0012's definition of hitless and enforces no budget. See
docs/qualification/g5-srt-group-comparison-plan-2026-11-13.md.
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .contracts import (
    COMMIT_RE,
    ContractError,
    load_json,
    validate_correlation_envelope,
    validate_srt_telemetry_observation,
)
from .fips_g2_linux import (
    IDENTITY_RE,
    QualificationError,
    _json_value_command,
    _run,
    _validate_executable,
    _wait_for,
    sha256_file,
    utc_now,
)
from .fips_g2_linux_alternate_route import ALTERNATE_PATH_ONE_WAY_DELAY_MS, ROLE_NAMES
from .g4_faulted_diamond import (
    DATAGRAM_BYTES,
    DECODE_OPTIONS,
    DRAIN_NS,
    EXPECTED_FFMPEG_VERSION,
    FIXTURE_ENCODE,
    FIXTURE_FILTER,
    FIXTURE_FRAMES,
    INJECT_AFTER_SOURCE_START_NS,
    MAX_SAMPLES,
    OUTPUT_PORT,
    RECORDER_CAPACITY,
    SOURCE_PORT,
    SOURCE_RATE_BPS,
    SRT_RECEIVE_TIMEOUT_MS,
    SRT_SAMPLE_INTERVAL_NS,
    _adapter_context,
    _bracket,
    _ffmpeg_version,
    _framehash,
    _generate_fixture,
    _positive,
    _sample_values,
    retimed_frame_count,
)
from .g4_srt_over_fips import (
    EXPECTED_SRT_COMMIT,
    EXPECTED_SRT_VERSION,
    EXPECTED_TELEMETRY_COMMIT,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
    _Peer,
    _clock,
    _clock_domain,
    _file_record,
    _parse_prefixed_json,
    _peer_command,
    _read_jsonl,
    _rfc3339_nano,
    _source_revision,
    _write_json,
    _write_jsonl,
)
from .media_frames import assess_media_frames
from .media_stream import GAP_THRESHOLD_NS, datagram_interval_ns
from .srt_adapter import adapt_srt_telemetry_jsonl


EVIDENCE_TYPE = "g5-srt-group"
DEVICE_ID = "four-node-group-diamond"
EVENT_NAMESPACE = uuid.UUID("7c1e4b2a-9d3f-5a6b-8c7d-2e1f0a9b8c7d")

# Predeclared experiment profile (docs/qualification/g5-srt-group-comparison-plan-2026-11-13).
GROUP_TYPES = ("broadcast", "backup")
MEMBERS = 2
# Member i runs over transit MEMBER_TRANSITS[i]; the higher weight is the Backup active member.
MEMBER_TRANSITS = ("r1", "r2")
MEMBER_WEIGHTS = (20, 10)
# One IPv6 /64 per link: a-r1, r1-b, a-r2, r2-b. Host 1 is the left end, host 2 the right.
LINK_PREFIXES = ("fd00:a1::", "fd00:b1::", "fd00:a2::", "fd00:b2::")
MEMBER_LOCAL_ADDRESSES = ("fd00:a1::1", "fd00:a2::1")
MEMBER_REMOTE_ADDRESSES = ("fd00:b1::2", "fd00:b2::2")
LINK_MTU = 1500
SRT_PEER_IDLE_TIMEOUT_MS = 5_000
FAULTED_MEMBER = 0
FAULT_MECHANISM = "netem-loss-100-percent"
# Stop rule 4: the listener's faulted member must receive nothing more within this time.
MEMBER_STOP_BUDGET_NS = 2_000_000_000
USABLE_STATES = ("running", "idle")
MEMBER_STATES = ("pending", "idle", "running", "broken", "removed", "unknown")
ROLES = ("sender", "receiver")

MEMBER_FILES = tuple(
    f"{role}-{kind}.member-{member}.{extension}"
    for role in ROLES for member in range(MEMBERS)
    for kind, extension in (("source", "jsonl"), ("context", "json"), ("observations", "jsonl"))
)
BUNDLE_FILES = (
    "fault-events.jsonl",
    "group-members.json",
    "group-samples.jsonl",
    *MEMBER_FILES,
    "media-source.json",
    "media-collector.json",
    "media-relay.json",
    "reference.framehash",
    "observed.framehash",
    "frame-assessment.json",
)
CLEANUP_FIELDS = ("srt_peers_stopped", "media_processes_stopped", "namespaces_removed",
                  "work_directory_removed")


def member_event_namespace(role: str, member: int) -> str:
    return str(uuid.uuid5(EVENT_NAMESPACE, f"{role}-member-{member}"))


def _envelope(*, source: str, name: str, run_id: str, domain_id: str, monotonic_ns: int,
              unix_ns: int, payload: dict[str, Any]) -> dict[str, Any]:
    envelope = {
        "schema_version": 1,
        "event_id": str(uuid.uuid5(EVENT_NAMESPACE, f"{run_id}:{name}")),
        "source": source,
        "observed_at": _rfc3339_nano(unix_ns),
        "monotonic_ns": monotonic_ns,
        "route_epoch": 1,
        "clock": _clock(domain_id),
        "tenant_id": "qualification",
        "device_id": DEVICE_ID,
        "stream_id": run_id,
        "quality": {"availability": "available", "confidence": 1.0, "reason": None},
        "payload": payload,
    }
    validate_correlation_envelope(envelope)
    return envelope


def _member_context(domain_id: str, role: str, member: int, run_id: str) -> dict:
    """The faulted diamond's adapter context without a route-epoch transition."""
    context = _adapter_context(domain_id, member_event_namespace(role, member), run_id, 0)
    del context["route_epoch_transitions"]
    context["fabric_identity"]["device_id"] = DEVICE_ID
    return context


def compute_group_timeline(
    *,
    fault_events: list[dict],
    group_samples: list[dict],
    observations: dict[str, list[list[dict]]],
    collector: dict,
    group_type: str,
) -> dict[str, Any]:
    """Derive the ordering-only timeline from retained files (runner and validator share it).

    Times are milliseconds from `blackhole-start`. A change is an interval [lower, upper]:
    it happened after `lower` (the last sample without it) and was observed at `upper`.
    Downstream gaps are point arrivals at the collector. Nothing here identifies a cause.

    `observations[role][member]` is that member's adapter output; `group_samples` holds one
    record per endpoint and sample with every member's state.
    """
    by_kind = {event["payload"]["event"]: event for event in fault_events if event["source"] == "fabric"}
    injection = by_kind["blackhole-start"]["monotonic_ns"]

    def first_after(series: list[dict], predicate) -> list[int | None] | None:
        previous = None
        for item in series:
            moment = item["monotonic_ns"]
            if moment > injection and predicate(item):
                return _bracket(previous, moment, injection)
            previous = moment
        return None

    def delta(name: str):
        return lambda item: _sample_values(item)[2].get(name)

    # A gap counts when it ends after the fault: one that only began before it is not the fault's.
    gaps = [[round((gap["start_ns"] - injection) / 1_000_000), round((gap["end_ns"] - injection) / 1_000_000)]
            for gap in collector.get("gaps", []) if gap["end_ns"] > injection]

    def unusable(role: str) -> list[int | None] | None:
        series = [item for item in group_samples if item["role"] == role]
        return first_after(series, lambda item: item["members"][FAULTED_MEMBER]["state"] not in USABLE_STATES)

    received = delta("unique_received_packet_delta")
    sent = delta("unique_sent_packet_delta")
    survivor = 1 - FAULTED_MEMBER
    return {
        "origin": "blackhole-start",
        "units": "ms",
        "fault_applied": round((by_kind["blackhole-applied"]["monotonic_ns"] - injection) / 1_000_000),
        "media_downstream_gaps": gaps,
        "longest_media_downstream_gap_ms": max((end - start for start, end in gaps), default=0),
        "faulted_member_receiver_stall": first_after(
            observations["receiver"][FAULTED_MEMBER], lambda item: received(item) == 0),
        "faulted_member_unusable": {role: unusable(role) for role in ROLES},
        # Only a Backup standby starts carrying media after the fault; a Broadcast member always did.
        "standby_activation": (first_after(observations["sender"][survivor], lambda item: _positive(sent(item)))
                               if group_type == "backup" else None),
        "causal_claim": None,
    }


def _failure_result(run_id: str, started_at: str, project_revision: str, phase: str,
                    cleanup: dict, error: Exception) -> dict:
    return {
        "schema_version": 1,
        "evidence_type": EVIDENCE_TYPE,
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G5"],
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "project_revision": project_revision,
        "failure_phase": phase,
        "failure_class": type(error).__name__,
        "failure_detail": IDENTITY_RE.sub("<redacted-identity>", str(error))[:512],
        "cleanup": cleanup,
        "gate_conclusion": {"G5": "not-passed", "reason": "run failed before a result existed"},
    }


def _sample_group(peer: _Peer, role: str, index: int, unix_nano: int, monotonic_nano: int) -> tuple[dict, dict]:
    """Read one group sample: the group line, then one member sample per sampled member."""
    group = _parse_prefixed_json(peer.wait_for("GROUP_SAMPLE"), "GROUP_SAMPLE")
    members = group.get("members")
    if (group.get("role") != role or group.get("sampleIndex") != index
            or group.get("sampleMonotonicNano") != monotonic_nano
            or not isinstance(members, list) or [item.get("index") for item in members] != list(range(MEMBERS))
            or any(item.get("state") not in MEMBER_STATES or not isinstance(item.get("sampled"), bool)
                   for item in members)):
        raise QualificationError("incident peer returned an invalid group sample")
    samples = {}
    for item in members:
        if not item["sampled"]:
            continue
        sample = _parse_prefixed_json(peer.wait_for("INCIDENT_SAMPLE"), "INCIDENT_SAMPLE")
        if (sample.get("provider") != "robotweax-srt" or sample.get("role") != role
                or sample.get("member") != item["index"] or sample.get("sampleIndex") != index
                or sample.get("observedAtUnixNano") != unix_nano
                or sample.get("sampleMonotonicNano") != monotonic_nano):
            raise QualificationError("incident peer did not preserve coordinator sample identity")
        samples[item["index"]] = sample
    return group, samples


def run_g5_srt_group(
    *,
    srt_source: Path,
    srt_library: Path,
    telemetry_source: Path,
    incident_peer: Path,
    library_dir: Path,
    ffmpeg: Path,
    output_dir: Path,
    project_revision: str,
    group_type: str,
) -> dict[str, Any]:
    if group_type not in GROUP_TYPES:
        raise QualificationError(f"unknown group type {group_type!r}")
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    phase = "preflight"
    if platform.system() != "Linux":
        raise QualificationError("the SRT-group runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the SRT-group runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("git", "ip", "ping", "sysctl", "tc"):
        if shutil.which(utility) is None:
            raise QualificationError(f"required utility is unavailable: {utility}")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise QualificationError("SRT-group output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    incident_peer = _validate_executable(incident_peer, "SRT telemetry incident peer")
    ffmpeg = _validate_executable(ffmpeg, "ffmpeg")
    srt_library = srt_library.resolve()
    library_dir = library_dir.resolve()
    if not srt_library.is_file() or not library_dir.is_dir():
        raise QualificationError("SRT library or runtime library directory is unavailable")
    ffmpeg_version = _ffmpeg_version(ffmpeg)
    if not ffmpeg_version.startswith(EXPECTED_FFMPEG_VERSION + " "):
        raise QualificationError("FFmpeg does not match the pinned decoder version")
    peer_cli = _run(["env", f"LD_LIBRARY_PATH={library_dir}", str(incident_peer), "--help"],
                    label="incident peer CLI", check=False)
    if "--group broadcast|backup" not in peer_cli.stderr or "--media-udp-input HOST:PORT" not in peer_cli.stderr:
        raise QualificationError("incident peer does not expose the connection-group CLI")
    provenance = {
        "project_revision": project_revision,
        "srt_repository": SRT_REPOSITORY,
        "srt_commit": _source_revision(srt_source, EXPECTED_SRT_COMMIT, "Robotweax SRT"),
        "srt_library_sha256": sha256_file(srt_library),
        "telemetry_repository": TELEMETRY_REPOSITORY,
        "telemetry_commit": _source_revision(telemetry_source, EXPECTED_TELEMETRY_COMMIT, "SRT Telemetry"),
        "incident_peer_sha256": sha256_file(incident_peer),
        "ffmpeg_version": ffmpeg_version,
        "ffmpeg_binary_sha256": sha256_file(ffmpeg),
    }

    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    work = Path(tempfile.mkdtemp(prefix="rimf-g5-group-", dir="/tmp"))
    os.chmod(work, 0o755)
    suffix = str(os.getpid())
    namespaces = tuple(f"rg5{name}{suffix}" for name in ROLE_NAMES)
    interfaces = tuple(f"g5{tag}{suffix}" for tag in ("a1", "r1a", "r1b", "b1", "a2", "r2a", "r2b", "b2"))
    if any(len(name) > 15 for name in (*namespaces, *interfaces)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")
    helpers: list[subprocess.Popen] = []
    listener: _Peer | None = None
    caller: _Peer | None = None
    cleanup = {field: False for field in CLEANUP_FIELDS}
    error: Exception | None = None
    result: dict[str, Any] | None = None
    group_samples: list[dict] = []
    fault_events: list[dict] = []

    try:
        phase = "media-fixture"
        fixture = work / "fixture.ts"
        _generate_fixture(ffmpeg, fixture)
        fixture.chmod(0o644)
        _framehash(ffmpeg, fixture, staging / "reference.framehash", "reference decode")
        reference_frames = sum(
            1 for line in (staging / "reference.framehash").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#"))
        if reference_frames != FIXTURE_FRAMES:
            raise QualificationError("reference decode does not hold the predeclared frame count")

        phase = "namespace-setup"
        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
            _run(["ip", "-n", namespace, "link", "set", "lo", "up"], label="bring loopback up")
        # (left interface, right interface, left node, right node), in LINK_PREFIXES order.
        links = ((interfaces[0], interfaces[1], 0, 1), (interfaces[2], interfaces[3], 1, 3),
                 (interfaces[4], interfaces[5], 0, 2), (interfaces[6], interfaces[7], 2, 3))
        for prefix, (left, right, left_node, right_node) in zip(LINK_PREFIXES, links):
            _run(["ip", "link", "add", left, "mtu", str(LINK_MTU), "type", "veth",
                  "peer", "name", right, "mtu", str(LINK_MTU)], label="create diamond veth")
            for interface, node, host in ((left, left_node, 1), (right, right_node, 2)):
                _run(["ip", "link", "set", interface, "netns", namespaces[node]], label="move diamond interface")
                _run(["ip", "-n", namespaces[node], "-6", "addr", "add", f"{prefix}{host}/64",
                      "dev", interface, "nodad"], label="assign diamond address")
                _run(["ip", "-n", namespaces[node], "link", "set", interface, "up"], label="bring interface up")
        for index in (1, 2):
            _run(["ip", "netns", "exec", namespaces[index], "sysctl", "-q", "-w",
                  "net.ipv6.conf.all.forwarding=1"], label=f"enable IPv6 forwarding on {ROLE_NAMES[index]}")
        # Each endpoint reaches the far-side link of a path only through that path's transit.
        for namespace, routes in (
                (namespaces[0], ((LINK_PREFIXES[1], LINK_PREFIXES[0] + "2"), (LINK_PREFIXES[3], LINK_PREFIXES[2] + "2"))),
                (namespaces[3], ((LINK_PREFIXES[0], LINK_PREFIXES[1] + "1"), (LINK_PREFIXES[2], LINK_PREFIXES[3] + "1")))):
            for prefix, gateway in routes:
                _run(["ip", "-n", namespace, "-6", "route", "add", f"{prefix}/64", "via", gateway],
                     label="add path route")
        for index, interface in ((2, interfaces[6]), (3, interfaces[7])):
            _run(["ip", "netns", "exec", namespaces[index], "tc", "qdisc", "add", "dev", interface,
                  "root", "netem", "delay", f"{ALTERNATE_PATH_ONE_WAY_DELAY_MS}ms"],
                 label="apply alternate-path latency stimulus")
        # The four veth ends of r1's two links as (node, interface, node at the other end).
        blackhole_ends = ((1, interfaces[1], 0), (1, interfaces[2], 3), (0, interfaces[0], 1), (3, interfaces[3], 1))

        phase = "initial-data-plane"

        def paths_ready():
            return all(
                _run(["ip", "netns", "exec", namespaces[0], "ping", "-6", "-c", "1", "-W", "1",
                      "-I", local, remote], label="initial path probe", timeout=5, check=False).returncode == 0
                for local, remote in zip(MEMBER_LOCAL_ADDRESSES, MEMBER_REMOTE_ADDRESSES))

        _wait_for(paths_ready, label="both routed paths", timeout=30, interval=1)

        phase = "srt-connect"
        flow_id = f"g5g-{run_id}"
        collector_summary = work / "media-collector.json"
        collector_ready = work / "collector.ready"
        received = work / "received.ts"
        package_root = str(Path(__file__).resolve().parents[1])
        collector = subprocess.Popen(
            ["ip", "netns", "exec", namespaces[3], "env", f"PYTHONPATH={package_root}",
             sys.executable, "-m", "rimf_lab.media_stream", "collect",
             "--bind", f"127.0.0.1:{OUTPUT_PORT}", "--stream", str(received),
             "--output", str(collector_summary), "--ready", str(collector_ready)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)
        helpers.append(collector)

        def collector_up():
            if collector.poll() is not None:
                raise QualificationError("media collector exited before becoming ready")
            return collector_ready.is_file()

        _wait_for(collector_up, label="independent media collector", timeout=10)

        def peer_arguments(role: str, recording: Path) -> list[str]:
            return ["--role", role, "--group", group_type,
                    "--peer-idle-timeout-ms", str(SRT_PEER_IDLE_TIMEOUT_MS),
                    "--receive-timeout-ms", str(SRT_RECEIVE_TIMEOUT_MS),
                    "--message-bytes", str(DATAGRAM_BYTES),
                    "--jsonl-output", str(recording), "--flow-id", flow_id,
                    "--provider-version", EXPECTED_SRT_VERSION, "--provider-revision", EXPECTED_SRT_COMMIT,
                    "--build-profile", "ubuntu-24.04-release-shared-openssl",
                    "--recorder-capacity", str(RECORDER_CAPACITY)]

        listener = _Peer(_peer_command(
            namespaces[3], incident_peer, library_dir,
            peer_arguments("listener", staging / "receiver-source.jsonl")
            + ["--group-members", str(MEMBERS), "--bind-address", "::",
               "--media-udp-output", f"127.0.0.1:{OUTPUT_PORT}"]))
        port = _parse_prefixed_json(listener.wait_for("READY"), "READY").get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port <= 65_535:
            raise QualificationError("SRT listener returned an invalid port")
        member_options = [option for local, remote, weight in
                          zip(MEMBER_LOCAL_ADDRESSES, MEMBER_REMOTE_ADDRESSES, MEMBER_WEIGHTS)
                          for option in ("--member", f"{local},{remote},{weight}")]
        caller = _Peer(_peer_command(
            namespaces[0], incident_peer, library_dir,
            peer_arguments("caller", staging / "sender-source.jsonl")
            + ["--port", str(port), *member_options, "--media-udp-input", f"127.0.0.1:{SOURCE_PORT}"]))
        peers = {"sender": caller, "receiver": listener}
        described: dict[str, dict] = {}
        profiles: dict[str, dict] = {}
        for role, direction in (("receiver", "srt-to-udp"), ("sender", "udp-to-srt")):
            described[role] = _parse_prefixed_json(peers[role].wait_for("GROUP", timeout=40), "GROUP")
            peers[role].wait_for("CONNECTED", timeout=30)
            profile = _parse_prefixed_json(peers[role].wait_for("PROFILE"), "PROFILE")
            if (profile.get("peerIdleTimeoutMillis") != SRT_PEER_IDLE_TIMEOUT_MS
                    or profile.get("receiveTimeoutMillis") != SRT_RECEIVE_TIMEOUT_MS
                    or profile.get("mediaRelay") != direction or profile.get("tooLatePacketDrop") is not True
                    or profile.get("group") != group_type or profile.get("groupMembers") != MEMBERS):
                raise QualificationError(f"{role} SRT profile does not match the predeclared profile")
            profiles[role] = profile
        group_members = group_member_record(described, group_type)
        _write_json(staging / "group-members.json", group_members)
        for role, direction in (("receiver", "srt-to-udp"), ("sender", "udp-to-srt")):
            peers[role].send("START_MEDIA")
            if _parse_prefixed_json(peers[role].wait_for("MEDIA_STARTED"), "MEDIA_STARTED") != {"direction": direction}:
                raise QualificationError("media relay did not start in the expected direction")

        phase = "faulted-capture"
        domain_id = _clock_domain()
        source_summary = work / "media-source.json"
        source = subprocess.Popen(
            ["ip", "netns", "exec", namespaces[0], "env", f"PYTHONPATH={package_root}",
             sys.executable, "-m", "rimf_lab.media_stream", "source", "--fixture", str(fixture),
             "--destination", f"127.0.0.1:{SOURCE_PORT}", "--rate-bps", str(SOURCE_RATE_BPS),
             "--datagram-bytes", str(DATAGRAM_BYTES), "--output", str(source_summary)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)
        helpers.append(source)
        source_started = time.monotonic_ns()
        inject_at = source_started + INJECT_AFTER_SOURCE_START_NS
        injected_ns: int | None = None
        member_stopped = False
        source_done_ns: int | None = None
        missed_intervals = 0
        last_samples: dict[str, dict[int, dict]] = {role: {} for role in ROLES}
        tick = 0

        def sample(index: int) -> dict[str, dict[int, dict]]:
            unix_nano = time.time_ns()
            monotonic_nano = time.monotonic_ns()
            for peer in (listener, caller):
                peer.send(f"SAMPLE {index} {unix_nano} {monotonic_nano}")
            current = {}
            for role in ("receiver", "sender"):
                group, samples = _sample_group(peers[role], role, index, unix_nano, monotonic_nano)
                group_samples.append({
                    "schema_version": 1, "role": role, "sample_index": index,
                    "observed_at": _rfc3339_nano(unix_nano), "monotonic_ns": monotonic_nano,
                    "members_listed": group.get("membersListed"),
                    "group_counters": group.get("groupCounters"),
                    "members": [{"index": item["index"], "state": item["state"], "sampled": item["sampled"]}
                                for item in group["members"]],
                })
                current[role] = samples
                last_samples[role].update(samples)
            return current

        while True:
            target = source_started + tick * SRT_SAMPLE_INTERVAL_NS
            if (remaining := target - time.monotonic_ns()) > 0:
                time.sleep(remaining / 1_000_000_000)
            if time.monotonic_ns() - target >= SRT_SAMPLE_INTERVAL_NS:
                missed_intervals += 1
            if tick >= MAX_SAMPLES:
                raise QualificationError("group capture exceeded its bounded sample count")
            current = sample(tick)
            faulted_received = current["receiver"].get(FAULTED_MEMBER, {}).get("delta", {}).get(
                "unique_received_packet_delta")
            now = time.monotonic_ns()
            if injected_ns is not None and not member_stopped:
                if FAULTED_MEMBER not in current["receiver"] or faulted_received == 0:
                    member_stopped = True
                elif now - injected_ns > MEMBER_STOP_BUDGET_NS + SRT_SAMPLE_INTERVAL_NS:
                    raise QualificationError("the blackholed member kept receiving")
            if injected_ns is None and now >= inject_at:
                # Stop rule 2: media flows, on both members in Broadcast and on member 0 in Backup.
                carried = [_positive(current["receiver"].get(member, {}).get("delta", {}).get(
                    "unique_received_packet_delta")) for member in range(MEMBERS)]
                states = [item["state"] for item in group_samples[-1]["members"]]
                expected = ([True, True], ["running", "running"]) if group_type == "broadcast" else \
                    ([True, False], ["running", "idle"])
                if (carried, states) != expected:
                    raise QualificationError("the group did not carry media as predeclared before the fault")
                injected_ns = time.monotonic_ns()
                fault_events.append(_envelope(
                    source="fabric", name="fault:blackhole-start", run_id=run_id, domain_id=domain_id,
                    monotonic_ns=injected_ns, unix_ns=time.time_ns(),
                    payload={"metric_namespace": "fabric.fault", "metric_semantics": "fault-injection",
                             "event": "blackhole-start", "target_role": MEMBER_TRANSITS[FAULTED_MEMBER],
                             "mechanism": FAULT_MECHANISM, "interfaces": len(blackhole_ends)}))
                for node, interface, _ in blackhole_ends:
                    _run(["ip", "netns", "exec", namespaces[node], "tc", "qdisc", "replace", "dev", interface,
                          "root", "netem", "loss", "100%"], label="apply transit blackhole")
                fault_events.append(_envelope(
                    source="fabric", name="fault:blackhole-applied", run_id=run_id, domain_id=domain_id,
                    monotonic_ns=time.monotonic_ns(), unix_ns=time.time_ns(),
                    payload={"metric_namespace": "fabric.fault", "metric_semantics": "fault-injection",
                             "event": "blackhole-applied", "target_role": MEMBER_TRANSITS[FAULTED_MEMBER],
                             "interfaces": len(blackhole_ends)}))
                up = []
                for node, interface, _ in blackhole_ends:
                    info = _json_value_command(["ip", "-n", namespaces[node], "-j", "link", "show", "dev", interface],
                                               label="faulted underlay state")
                    up.append(isinstance(info, list) and len(info) == 1 and "UP" in info[0].get("flags", []))
                fault_events.append(_envelope(
                    source="os", name="os:faulted-underlay-state", run_id=run_id, domain_id=domain_id,
                    monotonic_ns=time.monotonic_ns(), unix_ns=time.time_ns(),
                    payload={"metric_namespace": "os.link", "metric_semantics": "underlay-interface-state",
                             "interfaces": len(up), "interfaces_up": all(up)}))
                if not all(up):
                    raise QualificationError("a blackholed interface did not stay up")
            if source.poll() is not None and source_done_ns is None:
                if source.returncode != 0:
                    raise QualificationError("media source failed")
                source_done_ns = now
            if source_done_ns is not None and now - source_done_ns >= DRAIN_NS:
                break
            tick += 1
        if injected_ns is None or not member_stopped:
            raise QualificationError("the fixture ended before the fault took effect")

        drops = []
        for node, interface, far in blackhole_ends:
            qdiscs = _json_value_command(
                ["ip", "netns", "exec", namespaces[node], "tc", "-s", "-j", "qdisc", "show", "dev", interface],
                label="blackhole drop counters")
            netem = [item for item in qdiscs if isinstance(item, dict) and item.get("kind") == "netem"] \
                if isinstance(qdiscs, list) else []
            if len(netem) != 1 or not isinstance(netem[0].get("drops"), int):
                raise QualificationError("the blackhole qdisc is missing when the fixture ended")
            drops.append({"node_role": ROLE_NAMES[node], "toward_role": ROLE_NAMES[far],
                          "dropped_packets": netem[0]["drops"]})
        fault_events.append(_envelope(
            source="os", name="os:blackhole-drop-counters", run_id=run_id, domain_id=domain_id,
            monotonic_ns=time.monotonic_ns(), unix_ns=time.time_ns(),
            payload={"metric_namespace": "os.qdisc", "metric_semantics": "netem-drop-counters",
                     "target_role": MEMBER_TRANSITS[FAULTED_MEMBER], "drops": drops,
                     "dropped_packets": sum(item["dropped_packets"] for item in drops)}))
        if sum(item["dropped_packets"] for item in drops) < 1:
            raise QualificationError("the blackhole dropped no packet")

        phase = "media-stop"
        relay = {}
        for role in ROLES:
            peers[role].send("STOP_MEDIA")
            relay[role] = _parse_prefixed_json(peers[role].wait_for("MEDIA_STOPPED", timeout=10), "MEDIA_STOPPED")
        sample(tick + 1)
        if any(relay[role].get("connectionBroken") is not False for role in ROLES):
            raise QualificationError("the group did not stay connected to the end of the fixture")
        recorded: dict[str, dict[int, int]] = {role: {} for role in ROLES}
        for role in ROLES:
            peers[role].send("DONE")
        for role in ROLES:
            for member in range(MEMBERS):
                line = _parse_prefixed_json(peers[role].wait_for("RECORDED", timeout=20), "RECORDED")
                if line.get("member") != member or not _positive(line.get("recordCount")):
                    raise QualificationError("a group member left no recording")
                recorded[role][member] = line["recordCount"]
            peers[role].finish()
        listener = caller = None
        collector.send_signal(signal.SIGTERM)
        try:
            collector.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise QualificationError("media collector did not stop") from exc
        if collector.returncode != 0:
            raise QualificationError("media collector failed")

        phase = "decode-and-adapt"
        _framehash(ffmpeg, received, staging / "observed.framehash", "independent downstream decode")
        assessment = assess_media_frames(staging / "reference.framehash", staging / "observed.framehash")
        retimed = retimed_frame_count(staging / "reference.framehash", staging / "observed.framehash")
        if retimed:
            raise QualificationError(f"downstream decode re-timed {retimed} frames; comparison is invalid")
        _write_json(staging / "frame-assessment.json", assessment)
        for name in ("media-source.json", "media-collector.json"):
            shutil.copyfile(work / name, staging / name)
        _write_json(staging / "media-relay.json", {"schema_version": 1, "profiles": profiles, "stopped": relay})
        observations: dict[str, list[list[dict]]] = {role: [] for role in ROLES}
        for role in ROLES:
            for member in range(MEMBERS):
                # The peer writes each member beside the configured output path.
                source_path = staging / f"{role}-source.member-{member}.jsonl"
                context_path = staging / f"{role}-context.member-{member}.json"
                observation_path = staging / f"{role}-observations.member-{member}.jsonl"
                _write_json(context_path, _member_context(domain_id, role, member, run_id))
                adapt_srt_telemetry_jsonl(source_path, context_path, observation_path)
                observations[role].append(_read_jsonl(observation_path))
        _write_jsonl(staging / "group-samples.jsonl", group_samples)
        _write_jsonl(staging / "fault-events.jsonl", fault_events)
        collector_record = load_json(staging / "media-collector.json")
        source_record = load_json(staging / "media-source.json")
        timeline = compute_group_timeline(
            fault_events=fault_events, group_samples=group_samples, observations=observations,
            collector=collector_record, group_type=group_type)
        result = {
            "schema_version": 1,
            "evidence_type": EVIDENCE_TYPE,
            "status": "passed",
            "classification": "experiment",
            "gate_ids": ["G5"],
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": utc_now(),
            "provenance": provenance,
            "platform": {"system": platform.system(), "release": platform.release(),
                         "machine": platform.machine(), "python": platform.python_version()},
            "clock": {**_clock(domain_id), "same_host": True},
            "topology": {
                "node_count": 4, "isolation": "linux-network-namespaces",
                "underlay": "diamond-veth-ipv6-routed", "overlay": None, "fips": False,
                "link_mtu": LINK_MTU, "alternate_path_one_way_delay_ms": ALTERNATE_PATH_ONE_WAY_DELAY_MS,
                "member_transits": list(MEMBER_TRANSITS), "faulted_transit": MEMBER_TRANSITS[FAULTED_MEMBER],
            },
            "profile": {
                "group_type": group_type,
                "members": MEMBERS,
                "member_weights": list(MEMBER_WEIGHTS),
                "fault": "transit-blackhole",
                "fixture": {"generator": FIXTURE_FILTER, "encode": list(FIXTURE_ENCODE),
                            "frames": FIXTURE_FRAMES, "sha256": source_record["fixture_sha256"]},
                "source_rate_bps": SOURCE_RATE_BPS,
                "datagram_bytes": DATAGRAM_BYTES,
                "inject_after_source_start_ms": INJECT_AFTER_SOURCE_START_NS // 1_000_000,
                "srt_sample_interval_ms": SRT_SAMPLE_INTERVAL_NS // 1_000_000,
                "srt_peer_idle_timeout_ms": SRT_PEER_IDLE_TIMEOUT_MS,
                "srt_receive_timeout_ms": SRT_RECEIVE_TIMEOUT_MS,
                "member_stop_budget_ms": MEMBER_STOP_BUDGET_NS // 1_000_000,
                "collector_gap_threshold_ms": GAP_THRESHOLD_NS // 1_000_000,
                "decode_options": list(DECODE_OPTIONS),
            },
            "capture": {
                "group_samples_per_endpoint": len(group_samples) // len(ROLES),
                "missed_sample_intervals": missed_intervals,
                "member_records": {role: [recorded[role][member] for member in range(MEMBERS)] for role in ROLES},
                "member_wire": member_wire(observations["sender"]),
                "source_datagrams": source_record["datagrams"],
                "collected_datagrams": collector_record["datagrams"],
                "frames": {name: assessment[name] for name in (
                    "status", "expected_frames", "observed_frames", "missing_frames", "unexpected_frames",
                    "changed_frames", "max_consecutive_missing_frames")},
                "hitless": assessment["missing_frames"] == 0 and assessment["changed_frames"] == 0,
            },
            "timeline": timeline,
            "files": {name: _file_record(staging / name) for name in BUNDLE_FILES},
            "cleanup": cleanup,
            "gate_conclusion": {
                "G5": "not-passed",
                "reason": "single faulted run; ordering-only; no budget enforced and no causal claim",
            },
            "limitations": [
                "One run of one topology, one group mode and one fault class (netem loss 100% on both links of "
                "transit r1). It says nothing about partial or one-way loss.",
                "No FIPS is involved: the group runs over plain routed IPv6 with a 1500-byte link MTU.",
                "The two paths are veth pairs on one host; they are separate fault domains for this fault only.",
                "Each layer is observed at its own resolution (collector per datagram, SRT 500 ms); "
                "temporal ordering does not establish a cause.",
                "The downstream decode runs after the run on the collected stream; it is not a live player.",
            ],
        }
        if missed_intervals:
            raise QualificationError("the coordinator missed a complete sampling interval")
    except Exception as exc:
        error = exc
    finally:
        phase_at_failure = phase
        cleanup["srt_peers_stopped"] = all(peer is None or peer.stop() for peer in (listener, caller))
        stopped = []
        for helper in helpers:
            if helper.poll() is None:
                try:
                    os.killpg(helper.pid, signal.SIGTERM)
                    helper.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(helper.pid, signal.SIGKILL)
                        helper.wait(timeout=5)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        pass
            stopped.append(helper.poll() is not None)
        cleanup["media_processes_stopped"] = all(stopped)
        for namespace in namespaces:
            _run(["ip", "netns", "del", namespace], label="remove namespace", timeout=10, check=False)
        listing = _run(["ip", "netns", "list"], label="verify namespace cleanup", check=False).stdout
        cleanup["namespaces_removed"] = all(namespace not in listing for namespace in namespaces)
        shutil.rmtree(work, ignore_errors=True)
        cleanup["work_directory_removed"] = not work.exists()

    if error is None and not all(cleanup.values()):
        error = QualificationError("SRT-group teardown did not complete")
        phase_at_failure = "teardown"
    if error is not None:
        failure = _failure_result(run_id, started_at, project_revision, phase_at_failure, cleanup, error)
        diagnostics = {
            "schema_version": 1,
            "group_samples": group_samples[-40:],
            "fault_events": [item["payload"] | {"monotonic_ns": item["monotonic_ns"]} for item in fault_events],
        }
        if not (staging / "diagnostics.json").exists():
            _write_json(staging / "diagnostics.json", diagnostics)
        if (staging / "result.json").exists():
            os.unlink(staging / "result.json")
        _write_json(staging / "result.json", failure)
        staging.rename(output_dir)
        raise QualificationError(
            f"SRT-group experiment failed during {phase_at_failure}: {failure['failure_detail']}") from error
    assert result is not None
    result["cleanup"] = cleanup
    _write_json(staging / "result.json", result)
    validate_g5_srt_group_bundle(staging)
    staging.rename(output_dir)
    return result


def group_member_record(
    described: dict[str, dict],
    group_type: str,
    local_addresses: tuple[str, ...] = MEMBER_LOCAL_ADDRESSES,
    remote_addresses: tuple[str, ...] = MEMBER_REMOTE_ADDRESSES,
) -> dict:
    """Check both peers' GROUP lines against the predeclared members and keep what identifies them."""
    record: dict[str, Any] = {"schema_version": 1, "type": group_type, "members": []}
    sides = {role: described.get(role, {}) for role in ROLES}
    if any(side.get("type") != group_type or not isinstance(side.get("members"), list)
           or len(side["members"]) != MEMBERS for side in sides.values()):
        raise QualificationError("a peer did not describe the predeclared group")
    for member in range(MEMBERS):
        sender = sides["sender"]["members"][member]
        receiver = sides["receiver"]["members"][member]
        # Stop rule 1: the same path is member i on both endpoints, matched by address and port.
        if (sender.get("index") != member or receiver.get("index") != member
                or sender.get("localAddress") != local_addresses[member]
                or sender.get("peerAddress") != remote_addresses[member]
                or receiver.get("localAddress") != remote_addresses[member]
                or receiver.get("peerAddress") != local_addresses[member]
                or sender.get("localPort") != receiver.get("peerPort")
                or sender.get("peerPort") != receiver.get("localPort")
                or sender.get("weight") != MEMBER_WEIGHTS[member]):
            raise QualificationError("group members do not match the predeclared paths on both endpoints")
        record["members"].append({
            "index": member, "transit": MEMBER_TRANSITS[member], "weight": MEMBER_WEIGHTS[member],
            "caller_address": local_addresses[member], "listener_address": remote_addresses[member],
            "receiver_weight": receiver.get("weight"),
        })
    return record


def member_wire(sender_observations: list[list[dict]]) -> list[dict]:
    """Each sender member's last recorded cumulative packet and wire-byte totals."""
    wire = []
    for member, series in enumerate(sender_observations):
        raw = _sample_values(series[-1])[1] if series else {}
        wire.append({"index": member,
                     **{name: raw.get(name) for name in (
                         "unique_sent_packet_total", "sent_packet_total",
                         "unique_sent_wire_byte_total", "sent_wire_byte_total")}})
    return wire


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_g5_srt_group_result(result: Any) -> None:
    _require(isinstance(result, dict), "SRT-group result must be an object")
    _require(result.get("schema_version") == 1 and result.get("evidence_type") == EVIDENCE_TYPE,
             "SRT-group result schema/evidence_type is invalid")
    _require(result.get("classification") == "experiment" and result.get("gate_ids") == ["G5"],
             "SRT-group result classification/gates are invalid")
    try:
        uuid.UUID(result.get("run_id", ""))
    except (TypeError, ValueError) as exc:
        raise ContractError("SRT-group run_id is invalid") from exc
    conclusion = result.get("gate_conclusion")
    _require(isinstance(conclusion, dict) and set(conclusion) == {"G5", "reason"}
             and conclusion["G5"] == "not-passed" and isinstance(conclusion["reason"], str)
             and bool(conclusion["reason"]), "SRT-group result must record G5 as not-passed")
    cleanup = result.get("cleanup")
    _require(isinstance(cleanup, dict) and set(cleanup) == set(CLEANUP_FIELDS)
             and all(isinstance(value, bool) for value in cleanup.values()), "SRT-group cleanup is invalid")
    common = {"schema_version", "evidence_type", "status", "classification", "gate_ids", "run_id",
              "started_at", "finished_at", "cleanup", "gate_conclusion"}
    if result.get("status") == "failed":
        _require(set(result) == common | {"project_revision", "failure_phase", "failure_class", "failure_detail"},
                 "failed SRT-group result fields are invalid")
        _require(bool(COMMIT_RE.fullmatch(result.get("project_revision", ""))),
                 "failed SRT-group project revision is invalid")
        return
    _require(result.get("status") == "passed", "SRT-group status is invalid")
    _require(set(result) == common | {"provenance", "platform", "clock", "topology", "profile", "capture",
                                      "timeline", "files", "limitations"},
             "passed SRT-group result fields are invalid")
    _require(all(cleanup.values()), "passed SRT-group result requires complete cleanup")
    provenance = result["provenance"]
    for field, expected in (("srt_repository", SRT_REPOSITORY), ("srt_commit", EXPECTED_SRT_COMMIT),
                            ("telemetry_repository", TELEMETRY_REPOSITORY),
                            ("telemetry_commit", EXPECTED_TELEMETRY_COMMIT)):
        _require(provenance.get(field) == expected, f"SRT-group provenance {field} is invalid")
    _require(str(provenance.get("ffmpeg_version", "")).startswith(EXPECTED_FFMPEG_VERSION + " "),
             "SRT-group provenance ffmpeg_version is invalid")
    for field in ("srt_library_sha256", "incident_peer_sha256", "ffmpeg_binary_sha256"):
        value = provenance.get(field)
        _require(isinstance(value, str) and len(value) == 64, f"SRT-group provenance {field} is invalid")
    _require(bool(COMMIT_RE.fullmatch(provenance.get("project_revision", ""))),
             "SRT-group provenance project_revision is invalid")
    clock = result["clock"]
    _require(clock.get("same_host") is True and clock.get("synchronization") == "local-only"
             and clock.get("cross_host_ordering_allowed") is False, "SRT-group clock is invalid")
    topology = result["topology"]
    _require(topology.get("node_count") == 4 and topology.get("fips") is False
             and topology.get("member_transits") == list(MEMBER_TRANSITS)
             and topology.get("faulted_transit") == MEMBER_TRANSITS[FAULTED_MEMBER],
             "SRT-group topology is invalid")
    profile = result["profile"]
    _require(profile.get("group_type") in GROUP_TYPES and profile.get("members") == MEMBERS
             and profile.get("member_weights") == list(MEMBER_WEIGHTS)
             and profile.get("fault") == "transit-blackhole"
             and profile.get("datagram_bytes") == DATAGRAM_BYTES
             and profile.get("srt_peer_idle_timeout_ms") == SRT_PEER_IDLE_TIMEOUT_MS
             and profile.get("inject_after_source_start_ms") == INJECT_AFTER_SOURCE_START_NS // 1_000_000
             and profile.get("fixture", {}).get("frames") == FIXTURE_FRAMES
             and profile.get("fixture", {}).get("encode") == list(FIXTURE_ENCODE)
             and profile.get("decode_options") == list(DECODE_OPTIONS),
             "SRT-group profile is not the predeclared profile")
    capture = result["capture"]
    frames = capture.get("frames", {})
    _require(frames.get("expected_frames") == FIXTURE_FRAMES and capture.get("missed_sample_intervals") == 0,
             "SRT-group capture is incomplete")
    _require(capture.get("hitless") is (frames.get("missing_frames") == 0 and frames.get("changed_frames") == 0),
             "SRT-group hitless flag disagrees with the frame comparison")
    _require(set(result["files"]) == set(BUNDLE_FILES), "SRT-group file inventory is invalid")
    limitations = result["limitations"]
    _require(isinstance(limitations, list) and len(limitations) >= 3, "SRT-group limitations are invalid")
    timeline = result["timeline"]
    _require(isinstance(timeline, dict) and timeline.get("causal_claim") is None,
             "SRT-group timeline must not carry a causal claim")


def validate_g5_srt_group_bundle(directory: Path) -> None:
    directory = directory.resolve()
    result = load_json(directory / "result.json")
    validate_g5_srt_group_result(result)
    if result["status"] == "failed":
        return
    for name, record in result["files"].items():
        try:
            actual = _file_record(directory / name)
        except OSError as exc:
            raise ContractError(f"cannot read SRT-group file {name}: {exc}") from exc
        _require(actual == record, f"SRT-group file digest/size mismatch: {name}")
    timeline = validate_group_files(directory, result)[-1]
    _require(timeline == result["timeline"], "timeline is not reproducible from the retained files")


def validate_group_files(directory: Path, result: dict) -> tuple[list[dict], dict, dict[str, Any]]:
    """Validate the files every group bundle holds; return fault events, collector and timeline.

    Shared by stage 1 and the group-over-FIPS stage. The caller has validated `result` and
    the file digests, and compares the returned timeline with the stored one.
    """
    group_type = result["profile"]["group_type"]
    faults = _read_jsonl(directory / "fault-events.jsonl")
    for envelope in faults:
        validate_correlation_envelope(envelope)
    by_semantics = {item["payload"].get("metric_semantics"): item["payload"] for item in faults
                    if item["source"] == "os"}
    counters = by_semantics.get("netem-drop-counters", {})
    entries = counters.get("drops")
    _require(by_semantics.get("underlay-interface-state", {}).get("interfaces_up") is True
             and isinstance(entries, list) and len(entries) == 4
             and all(isinstance(item.get("dropped_packets"), int) for item in entries)
             and counters.get("dropped_packets") == sum(item["dropped_packets"] for item in entries) >= 1,
             "blackhole fault events do not show a dropping transit with its interfaces up")
    members = load_json(directory / "group-members.json")
    _require(members.get("type") == group_type
             and [item.get("transit") for item in members.get("members", [])] == list(MEMBER_TRANSITS)
             and [item.get("weight") for item in members["members"]] == list(MEMBER_WEIGHTS),
             "group member record does not match the predeclared paths")
    group_samples = _read_jsonl(directory / "group-samples.jsonl")
    _require(bool(group_samples) and all(
        item.get("role") in ROLES and isinstance(item.get("monotonic_ns"), int)
        and isinstance(item.get("members"), list) and len(item["members"]) == MEMBERS
        and all(member.get("state") in MEMBER_STATES for member in item["members"])
        for item in group_samples), "group samples are invalid")
    _require(result["capture"]["group_samples_per_endpoint"] * len(ROLES) == len(group_samples),
             "group sample count disagrees with the retained samples")
    observations: dict[str, list[list[dict]]] = {role: [] for role in ROLES}
    for role in ROLES:
        for member in range(MEMBERS):
            label = f"{role} member {member}"
            suffix = f"member-{member}"
            context = load_json(directory / f"{role}-context.{suffix}.json")
            _require(context.get("event_namespace") == member_event_namespace(role, member)
                     and "route_epoch_transitions" not in context,
                     f"{label} adapter context is not the predeclared context")
            records = _read_jsonl(directory / f"{role}-source.{suffix}.jsonl")
            _require(bool(records) and records[0].get("providerVersion") == EXPECTED_SRT_VERSION
                     and records[0].get("providerRevision") == EXPECTED_SRT_COMMIT,
                     f"{label} provider identity does not match provenance")
            with tempfile.TemporaryDirectory() as scratch:
                replay = Path(scratch) / "replay.jsonl"
                adapt_srt_telemetry_jsonl(directory / f"{role}-source.{suffix}.jsonl",
                                          directory / f"{role}-context.{suffix}.json", replay)
                _require(replay.read_bytes() == (directory / f"{role}-observations.{suffix}.jsonl").read_bytes(),
                         f"{label} observations are not a byte-exact adapter replay")
            series = _read_jsonl(directory / f"{role}-observations.{suffix}.jsonl")
            for observation in series:
                validate_srt_telemetry_observation(observation)
            observations[role].append(series)
    _require(result["capture"]["member_wire"] == member_wire(observations["sender"]),
             "member wire totals are not reproducible from the retained observations")
    stored = load_json(directory / "frame-assessment.json")
    recomputed = assess_media_frames(directory / "reference.framehash", directory / "observed.framehash")
    _require(stored == recomputed, "frame assessment is not reproducible from the retained framehashes")
    _require(all(result["capture"]["frames"][name] == stored[name] for name in result["capture"]["frames"]),
             "result frames disagree with the frame assessment")
    _require(retimed_frame_count(directory / "reference.framehash", directory / "observed.framehash") == 0,
             "downstream decode re-timed frames; the frame comparison is invalid")
    collector = load_json(directory / "media-collector.json")
    timeline = compute_group_timeline(fault_events=faults, group_samples=group_samples,
                                      observations=observations, collector=collector, group_type=group_type)
    stall = timeline["faulted_member_receiver_stall"]
    _require(stall is not None
             and stall[1] <= (MEMBER_STOP_BUDGET_NS + SRT_SAMPLE_INTERVAL_NS) // 1_000_000,
             "the blackholed member did not stop receiving within its budget")
    _require(result["capture"]["collected_datagrams"] == collector.get("datagrams"),
             "collected datagram count disagrees with the collector record")
    relay = load_json(directory / "media-relay.json")
    _require(set(relay.get("stopped", {})) == set(ROLES)
             and all(relay["stopped"][role].get("connectionBroken") is False for role in ROLES)
             and all(relay.get("profiles", {}).get(role, {}).get("group") == group_type for role in ROLES),
             "media relay record does not show a connected group of the predeclared type")
    source = load_json(directory / "media-source.json")
    _require(source.get("fixture_sha256") == result["profile"]["fixture"]["sha256"]
             and source.get("datagram_bytes") == DATAGRAM_BYTES
             and source.get("interval_ns") == datagram_interval_ns(SOURCE_RATE_BPS, DATAGRAM_BYTES)
             and result["capture"]["source_datagrams"] == source.get("datagrams"),
             "media source record disagrees with the profile")
    return faults, collector, timeline
