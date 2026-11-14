"""G5 SRT-group comparison, stage 2: one SRT connection group over two FIPS overlays.

The faulted diamond's four namespaces and IPv4 underlay carry two separate FIPS overlays:
overlay 1 is a/1 - r1 - b/1 and overlay 2 is a/2 - r2 - b/2. Each endpoint runs two FIPS
daemons with separate identities and TUN devices. FIPS v0.5.3 does not support that: every
daemon installs `fd00::/8` on its own TUN, and the second add fails. The lab therefore
removes that route after each endpoint daemon starts and routes each remote overlay address
to the matching TUN. All binaries are unmodified.

The SRT Telemetry incident peer on `a` opens a Broadcast or Backup group with one member per
overlay to the peer on `b`. Stream, source, collector, decode, frame comparison, fault and
group sampling are stage 1's. The result is ordering-only and records `G5: not-passed`. See
docs/qualification/g5-srt-group-over-fips-plan-2026-11-14.md.
"""

from __future__ import annotations

import ipaddress
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .contracts import COMMIT_RE, ContractError, load_json, validate_correlation_envelope
from .fips_g2_linux import (
    EFFECTIVE_IPV6_MTU,
    EXPECTED_FIPS_COMMIT,
    FIPS_REPOSITORY,
    IDENTITY_RE,
    TUN_MTU,
    QualificationError,
    _json_command,
    _json_value_command,
    _print_redacted_log_tails,
    _run,
    _source_provenance,
    _stop_process,
    _validate_executable,
    _wait_for,
    sha256_file,
    utc_now,
)
from .fips_g2_linux_alternate_route import (
    ALTERNATE_PATH_ONE_WAY_DELAY_MS,
    HEARTBEAT_INTERVAL_SECS,
    LINK_DEAD_TIMEOUT_SECS,
    NODE_ADDR_RE,
    NODE_ADDRESSES,
    NPUB_RE,
    RETRY_BASE_INTERVAL_SECS,
    RETRY_MAX_BACKOFF_SECS,
    ROLE_NAMES,
    SESSION_IDLE_TIMEOUT_SECS,
    TICK_INTERVAL_SECS,
    node_addr_from_npub,
)
from .g4_faulted_diamond import (
    DATAGRAM_BYTES,
    DECODE_OPTIONS,
    DRAIN_NS,
    EXPECTED_FFMPEG_VERSION,
    FIPS_OBSERVATION_EVERY,
    FIXTURE_ENCODE,
    FIXTURE_FILTER,
    FIXTURE_FRAMES,
    INJECT_AFTER_SOURCE_START_NS,
    MAX_SAMPLES,
    OUTPUT_PORT,
    RECORDER_CAPACITY,
    SOURCE_PORT,
    SOURCE_RATE_BPS,
    SRT_IPV6_UDP_HEADER_BYTES,
    SRT_RECEIVE_TIMEOUT_MS,
    SRT_SAMPLE_INTERVAL_NS,
    _bracket,
    _ffmpeg_version,
    _framehash,
    _generate_fixture,
    _positive,
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
from .g5_srt_group import (
    BUNDLE_FILES as GROUP_BUNDLE_FILES,
    CLEANUP_FIELDS as GROUP_CLEANUP_FIELDS,
    FAULT_MECHANISM,
    FAULTED_MEMBER,
    GROUP_TYPES,
    MEMBER_STOP_BUDGET_NS,
    MEMBER_TRANSITS,
    MEMBER_WEIGHTS,
    MEMBERS,
    ROLES,
    SRT_PEER_IDLE_TIMEOUT_MS,
    _member_context,
    _sample_group,
    compute_group_timeline,
    group_member_record,
    member_wire,
    validate_group_files,
)
from .media_frames import assess_media_frames
from .media_stream import GAP_THRESHOLD_NS, TS_PACKET_BYTES
from .srt_adapter import adapt_srt_telemetry_jsonl


EVIDENCE_TYPE = "g5-srt-group-fips"
DEVICE_ID = "four-node-group-diamond-two-fips-overlays"
EVENT_NAMESPACE = uuid.UUID("3d9a6f10-5b7c-5e2d-9a41-6c0f8e2b7d15")

# Predeclared experiment profile (docs/qualification/g5-srt-group-over-fips-plan-2026-11-14).
OVERLAYS = 2
# Overlay k carries member k through transit MEMBER_TRANSITS[k].
ENDPOINT_TUN_NAMES = ("fipsg1", "fipsg2")
TRANSIT_TUN_NAME = "fips0"
FIPS_PREFIX = "fd00::/8"
FIPS_UDP_PORT = 2121
# Endpoint daemon k answers FIPS DNS on ::1 at this port plus k; the lookup teaches the daemon
# the remote identity behind an overlay address, as in the faulted diamond.
FIPS_DNS_BASE_PORT = 5354
FIPS_TIMERS = {
    "name": "g2-alternate-route",
    "tick_interval_secs": TICK_INTERVAL_SECS,
    "heartbeat_interval_secs": HEARTBEAT_INTERVAL_SECS,
    "link_dead_timeout_secs": LINK_DEAD_TIMEOUT_SECS,
}
ENDPOINT_ROUTING = "lab-host-routes-replace-fips-prefix-route"
# What an intact overlay looks like from its three nodes (stop rules 1 and 5).
INTACT_OVERLAY = {
    "a_peer_count": 1, "a_link_count": 1,
    "transit_peer_count": 2, "transit_link_count": 2,
    "b_peer_count": 1, "b_link_count": 1,
    "b_parent_role": "transit", "b_root_role": "a", "b_depth": 2,
}

BUNDLE_FILES = (*GROUP_BUNDLE_FILES, "fips-observations.jsonl")
CLEANUP_FIELDS = (*GROUP_CLEANUP_FIELDS, "fips_daemons_stopped")

# The six daemons as (overlay, role in the overlay, namespace index, TUN name).
# Role order within an overlay is a, transit, b; identities are assigned in that order.
DAEMONS = tuple(
    (overlay, role, namespace, ENDPOINT_TUN_NAMES[overlay] if role != "transit" else TRANSIT_TUN_NAME)
    for overlay in range(OVERLAYS)
    for role, namespace in (("a", 0), ("transit", 1 + overlay), ("b", 3))
)


def render_overlay_config(
    control_socket: Path,
    *,
    tun_name: str,
    bind_address: str,
    peers: list[tuple[str, str, str]],
    dns_port: int | None = None,
) -> str:
    """FIPS configuration of one overlay node: the alternate-route profile with a configurable
    TUN name, UDP bind address and DNS port so two daemons can share a namespace."""
    try:
        ipaddress.IPv4Address(bind_address)
    except ipaddress.AddressValueError as exc:
        raise ValueError("FIPS UDP bind address is invalid") from exc
    if not tun_name.isalnum() or len(tun_name) > 15:
        raise ValueError("FIPS TUN name is invalid")
    peer_lines: list[str] = []
    for alias, npub, address in peers:
        if not alias or not NPUB_RE.fullmatch(npub):
            raise ValueError("static peer specification is invalid")
        peer_lines.append(
            f'''  - npub: "{npub}"
    alias: "{alias}"
    addresses:
      - transport: "udp"
        addr: "{address}:{FIPS_UDP_PORT}"
        priority: 100
    connect_policy: "auto_connect"
    auto_reconnect: true
    via_nostr: false''')
    peers_yaml = "peers: []" if not peer_lines else "peers:\n" + "\n".join(peer_lines)
    if dns_port is not None and not (isinstance(dns_port, int) and 1024 <= dns_port <= 65_535):
        raise ValueError("FIPS DNS port is invalid")
    dns_yaml = "  enabled: false" if dns_port is None else f'  enabled: true\n  bind_addr: "::1"\n  port: {dns_port}'
    return f'''node:
  identity:
    persistent: true
  control:
    enabled: true
    socket_path: "{control_socket}"
  tick_interval_secs: {FIPS_TIMERS["tick_interval_secs"]}
  heartbeat_interval_secs: {FIPS_TIMERS["heartbeat_interval_secs"]}
  link_dead_timeout_secs: {FIPS_TIMERS["link_dead_timeout_secs"]}
  retry:
    max_retries: 5
    base_interval_secs: {RETRY_BASE_INTERVAL_SECS}
    max_backoff_secs: {RETRY_MAX_BACKOFF_SECS}
  session:
    idle_timeout_secs: {SESSION_IDLE_TIMEOUT_SECS}
  log_level: warn
  native_api:
    enabled: false
  rendezvous:
    nostr:
      enabled: false
    lan:
      enabled: false

tun:
  enabled: true
  name: "{tun_name}"
  mtu: {TUN_MTU}

dns:
{dns_yaml}

transports:
  udp:
    bind_addr: "{bind_address}:{FIPS_UDP_PORT}"
    mtu: {TUN_MTU}

{peers_yaml}
'''


def overlay_state(statuses: list[dict], b_tree: dict, node_addrs: list[str]) -> dict[str, Any]:
    """One overlay's observed state from its a, transit and b status and b's tree view."""
    roles = dict(zip(node_addrs, ("a", "transit", "b")))
    return {
        "a_peer_count": statuses[0].get("peer_count"), "a_link_count": statuses[0].get("link_count"),
        "transit_peer_count": statuses[1].get("peer_count"),
        "transit_link_count": statuses[1].get("link_count"),
        "b_peer_count": statuses[2].get("peer_count"), "b_link_count": statuses[2].get("link_count"),
        "b_parent_role": roles.get(b_tree.get("parent"), "unknown"),
        "b_root_role": roles.get(b_tree.get("root"), "unknown"),
        "b_depth": b_tree.get("depth"),
    }


def overlay_relationships(peer_views: list[dict], tree_views: list[dict],
                          identities: list[str], node_addrs: list[str]) -> bool:
    """Stop rule 1 for one overlay: its peers and tree are exactly a - transit - b."""
    if len(peer_views) != 3 or len(tree_views) != 3 or len(identities) != 3 or len(node_addrs) != 3:
        return False
    observed = []
    for view in peer_views:
        peers = view.get("peers")
        if not isinstance(peers, list):
            return False
        npubs = {item.get("npub") for item in peers if isinstance(item, dict)}
        if len(npubs) != len(peers):
            return False
        observed.append(npubs)
    node_a, transit, node_b = identities
    return (observed == [{transit}, {node_a, node_b}, {transit}]
            and all(item.get("root") == node_addrs[0] for item in tree_views)
            and [item.get("depth") for item in tree_views] == [0, 1, 2]
            and tree_views[1].get("parent") == node_addrs[0]
            and tree_views[2].get("parent") == node_addrs[1])


def compute_fips_group_timeline(base: dict[str, Any], fault_events: list[dict],
                                fips_observations: list[dict]) -> dict[str, Any]:
    """Stage 1's timeline plus what the two overlays' FIPS control state showed.

    `faulted_overlay_link_loss` brackets, per endpoint, the first observation after the fault
    in which that endpoint of the blackholed overlay no longer had its one link.
    `surviving_overlay_stable` is stop rule 5: every observation was available and showed the
    other overlay intact.
    """
    injection = next(event["monotonic_ns"] for event in fault_events
                     if event["source"] == "fabric" and event["payload"]["event"] == "blackhole-start")
    survivor = 1 - FAULTED_MEMBER

    def loss(endpoint: str) -> list[int | None] | None:
        previous = None
        for item in fips_observations:
            moment = item["monotonic_ns"]
            state = item["payload"]["overlays"][FAULTED_MEMBER]
            if moment > injection and state[f"{endpoint}_link_count"] != 1:
                return _bracket(previous, moment, injection)
            previous = moment
        return None

    stable = bool(fips_observations) and all(
        item["quality"]["availability"] == "available"
        and {name: item["payload"]["overlays"][survivor].get(name) for name in INTACT_OVERLAY} == INTACT_OVERLAY
        for item in fips_observations)
    return {**base,
            "faulted_overlay_link_loss": {endpoint: loss(endpoint) for endpoint in ("a", "b")},
            "surviving_overlay_stable": stable}


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


def run_g5_srt_group_fips(
    *,
    fips_source: Path,
    fips_binary: Path,
    fipsctl_binary: Path,
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
        raise QualificationError("the SRT-group-over-FIPS runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the SRT-group-over-FIPS runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("dig", "git", "ip", "ping", "sysctl", "tc"):
        if shutil.which(utility) is None:
            raise QualificationError(f"required utility is unavailable: {utility}")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise QualificationError("SRT-group-over-FIPS output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    fips_binary = _validate_executable(fips_binary, "fips")
    fipsctl_binary = _validate_executable(fipsctl_binary, "fipsctl")
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
    provenance = _source_provenance(fips_source)
    provenance.update({
        "project_revision": project_revision,
        "srt_repository": SRT_REPOSITORY,
        "srt_commit": _source_revision(srt_source, EXPECTED_SRT_COMMIT, "Robotweax SRT"),
        "srt_library_sha256": sha256_file(srt_library),
        "telemetry_repository": TELEMETRY_REPOSITORY,
        "telemetry_commit": _source_revision(telemetry_source, EXPECTED_TELEMETRY_COMMIT, "SRT Telemetry"),
        "incident_peer_sha256": sha256_file(incident_peer),
        "fips_binary_sha256": sha256_file(fips_binary),
        "fipsctl_binary_sha256": sha256_file(fipsctl_binary),
        "ffmpeg_version": ffmpeg_version,
        "ffmpeg_binary_sha256": sha256_file(ffmpeg),
    })
    if provenance["fips_repository"] != FIPS_REPOSITORY:
        raise QualificationError("unexpected FIPS repository provenance")

    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    work = Path(tempfile.mkdtemp(prefix="rimf-g5-fips-", dir="/tmp"))
    os.chmod(work, 0o755)
    suffix = str(os.getpid())
    namespaces = tuple(f"rg5f{name}{suffix}" for name in ROLE_NAMES)
    interfaces = tuple(f"g5f{tag}{suffix}" for tag in ("a1", "r1a", "r1b", "b1", "a2", "r2a", "r2b", "b2"))
    if any(len(name) > 15 for name in (*namespaces, *interfaces)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")
    daemons: list[subprocess.Popen | None] = [None] * len(DAEMONS)
    streams: list[Any] = [None] * len(DAEMONS)
    daemon_logs: tuple[Path, ...] = ()
    helpers: list[subprocess.Popen] = []
    listener: _Peer | None = None
    caller: _Peer | None = None
    cleanup = {field: False for field in CLEANUP_FIELDS}
    error: Exception | None = None
    result: dict[str, Any] | None = None
    group_samples: list[dict] = []
    fault_events: list[dict] = []
    fips_observations: list[dict] = []

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

        phase = "identity-and-config-setup"
        # Per overlay three identities, assigned a, transit, b in node-address order so that
        # `a` is the tree root, as in the faulted diamond.
        identities: list[str] = []
        node_addrs: list[str] = []
        role_dirs: list[Path] = []
        generated = []
        for group in range(OVERLAYS):
            records = []
            for index in range(3):
                directory = work / f"identity-{group}-{index}"
                directory.mkdir(mode=0o700)
                _run([str(fipsctl_binary), "keygen", "--dir", str(directory)], label="generate identity")
                npub = (directory / "fips.pub").read_text(encoding="utf-8").strip()
                records.append((node_addr_from_npub(npub), npub, directory))
            generated.append(sorted(records, key=lambda item: item[0]))
        # The incident peer's listener numbers its members by the caller's address. An overlay
        # address is derived from the node address, so the overlay whose `a` has the lower node
        # address becomes overlay 1 and member 0 on both endpoints.
        for records in sorted(generated, key=lambda items: items[0][0]):
            node_addrs.extend(item[0] for item in records)
            identities.extend(item[1] for item in records)
            role_dirs.extend(item[2] for item in records)
        if len(set(node_addrs)) != len(DAEMONS) or not all(NODE_ADDR_RE.fullmatch(item) for item in node_addrs):
            raise QualificationError("temporary identities did not produce unique node addresses")
        if not all(stat.S_IMODE((d / "fips.key").stat().st_mode) == 0o600 for d in role_dirs):
            raise QualificationError("temporary identity file modes are invalid")
        sockets = tuple(d / "control.sock" for d in role_dirs)
        configs = tuple(d / "fips.yaml" for d in role_dirs)
        daemon_logs = tuple(d / "daemon.log" for d in role_dirs)
        # Underlay addresses: a's and b's end of each overlay's links, and the transit's b side.
        a_underlay = (NODE_ADDRESSES[0][0], NODE_ADDRESSES[0][1])
        b_underlay = (NODE_ADDRESSES[3][0], NODE_ADDRESSES[3][1])
        transit_b_side = (NODE_ADDRESSES[1][1], NODE_ADDRESSES[2][1])
        for index, (overlay, role, _, tun_name) in enumerate(DAEMONS):
            base = overlay * 3
            if role == "a":
                bind, peers = a_underlay[overlay], []
            elif role == "transit":
                bind, peers = "0.0.0.0", [("endpoint-a", identities[base], a_underlay[overlay])]
            else:
                bind, peers = b_underlay[overlay], [("transit", identities[base + 1], transit_b_side[overlay])]
            configs[index].write_text(
                render_overlay_config(sockets[index], tun_name=tun_name, bind_address=bind, peers=peers,
                                      dns_port=None if role == "transit" else FIPS_DNS_BASE_PORT + overlay),
                encoding="utf-8")
            configs[index].chmod(0o600)

        def control(index: int, *arguments: str, timeout: float = 30) -> dict:
            overlay, role, _, _ = DAEMONS[index]
            return _json_command([str(fipsctl_binary), "-s", str(sockets[index]), *arguments],
                                 label=f"overlay {overlay + 1} node {role} {' '.join(arguments)}",
                                 timeout=timeout)

        phase = "namespace-setup"
        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
            _run(["ip", "-n", namespace, "link", "set", "lo", "up"], label="bring loopback up")
        links = (
            (interfaces[0], interfaces[1], 0, 1, NODE_ADDRESSES[0][0], NODE_ADDRESSES[1][0]),
            (interfaces[2], interfaces[3], 1, 3, NODE_ADDRESSES[1][1], NODE_ADDRESSES[3][0]),
            (interfaces[4], interfaces[5], 0, 2, NODE_ADDRESSES[0][1], NODE_ADDRESSES[2][0]),
            (interfaces[6], interfaces[7], 2, 3, NODE_ADDRESSES[2][1], NODE_ADDRESSES[3][1]),
        )
        for left, right, left_node, right_node, left_address, right_address in links:
            _run(["ip", "link", "add", left, "type", "veth", "peer", "name", right], label="create diamond veth")
            for interface, node, address in ((left, left_node, left_address), (right, right_node, right_address)):
                _run(["ip", "link", "set", interface, "netns", namespaces[node]], label="move diamond interface")
                _run(["ip", "-n", namespaces[node], "addr", "add", f"{address}/30", "dev", interface],
                     label="assign diamond underlay address")
                _run(["ip", "-n", namespaces[node], "link", "set", interface, "up"], label="bring interface up")
        for index in (1, 2):
            _run(["ip", "netns", "exec", namespaces[index], "sysctl", "-q", "-w", "net.ipv4.ip_forward=0"],
                 label=f"disable IPv4 forwarding on {ROLE_NAMES[index]}")
        for index, interface in ((2, interfaces[6]), (3, interfaces[7])):
            _run(["ip", "netns", "exec", namespaces[index], "tc", "qdisc", "add", "dev", interface,
                  "root", "netem", "delay", f"{ALTERNATE_PATH_ONE_WAY_DELAY_MS}ms"],
                 label="apply alternate-path latency stimulus")
        # The four veth ends of r1's two links as (node, interface, node at the other end).
        blackhole_ends = ((1, interfaces[1], 0), (1, interfaces[2], 3), (0, interfaces[0], 1), (3, interfaces[3], 1))
        # Stop rule 2, underlay half: a must not reach b without the overlays.
        direct = _run(["ip", "netns", "exec", namespaces[0], "ping", "-c", "1", "-W", "1", NODE_ADDRESSES[3][0]],
                      label="direct-underlay exclusion probe", timeout=5, check=False)
        if direct.returncode == 0:
            raise QualificationError("endpoint A unexpectedly reached B over the IPv4 underlay")

        phase = "daemon-start"

        def start_daemon(index: int) -> None:
            namespace = namespaces[DAEMONS[index][2]]
            streams[index] = daemon_logs[index].open("w", encoding="utf-8")
            daemons[index] = subprocess.Popen(
                ["ip", "netns", "exec", namespace, str(fips_binary), "-c", str(configs[index])],
                stdout=streams[index], stderr=subprocess.STDOUT, text=True, start_new_session=True)

        def prefix_route_present(index: int) -> bool:
            _, _, namespace, tun_name = DAEMONS[index]
            if daemons[index] is None or daemons[index].poll() is not None:
                raise QualificationError("a FIPS daemon exited before its TUN was configured")
            routes = _run(["ip", "-n", namespaces[namespace], "-6", "route", "show", FIPS_PREFIX, "dev", tun_name],
                          label="FIPS prefix route", timeout=5, check=False)
            return routes.returncode == 0 and FIPS_PREFIX in routes.stdout

        # Transits first; then, per endpoint, one daemon at a time. The lab removes each endpoint
        # daemon's fd00::/8 route once it exists, so the next daemon's own add succeeds.
        for index, (_, role, _, _) in enumerate(DAEMONS):
            if role == "transit":
                start_daemon(index)
        for index, (_, role, namespace, tun_name) in enumerate(DAEMONS):
            if role == "transit":
                continue
            start_daemon(index)
            _wait_for(lambda index=index: prefix_route_present(index), label="FIPS prefix route on an endpoint TUN",
                      timeout=30, interval=0.2)
            _run(["ip", "-n", namespaces[namespace], "-6", "route", "del", FIPS_PREFIX, "dev", tun_name],
                 label="remove FIPS prefix route")

        def controls_ready():
            if any(process is None or process.poll() is not None for process in daemons):
                raise QualificationError("a FIPS daemon exited before control became ready")
            if not all(path.is_socket() for path in sockets):
                return None
            try:
                return [control(index, "show", "status") for index in range(len(DAEMONS))]
            except QualificationError:
                return None

        statuses = _wait_for(controls_ready, label="six FIPS control sockets", timeout=30)
        if [item.get("npub") for item in statuses] != identities:
            raise QualificationError("daemon identities did not match role-assigned key files")
        endpoint_indexes = [index for index, item in enumerate(DAEMONS) if item[1] != "transit"]
        endpoint_mtus = [statuses[index].get("effective_ipv6_mtu") for index in endpoint_indexes]
        packet_budget = {
            "endpoint_effective_ipv6_mtu": endpoint_mtus,
            "srt_ipv6_udp_header_bytes": SRT_IPV6_UDP_HEADER_BYTES,
            "clear_srt_payload_budget_bytes": min(endpoint_mtus) - SRT_IPV6_UDP_HEADER_BYTES
            if all(isinstance(value, int) for value in endpoint_mtus) else None,
            "media_datagram_bytes": DATAGRAM_BYTES,
            "ts_packets_per_datagram": DATAGRAM_BYTES // TS_PACKET_BYTES,
        }
        # Stop rule 3.
        if (packet_budget["clear_srt_payload_budget_bytes"] is None
                or DATAGRAM_BYTES > packet_budget["clear_srt_payload_budget_bytes"]):
            raise QualificationError("media datagrams do not fit the clear SRT payload budget of the overlays")
        for index, ((overlay, role, namespace, tun_name), node_status) in enumerate(zip(DAEMONS, statuses)):
            if (node_status.get("tun_state") != "active" or node_status.get("tun_name") != tun_name
                    or node_status.get("effective_ipv6_mtu") != EFFECTIVE_IPV6_MTU):
                raise QualificationError(f"overlay {overlay + 1} node {role} runtime state is invalid")
            link = _json_value_command(["ip", "-n", namespaces[namespace], "-j", "link", "show", "dev", tun_name],
                                       label="kernel TUN state")
            if not isinstance(link, list) or len(link) != 1 or link[0].get("mtu") != TUN_MTU:
                raise QualificationError(f"overlay {overlay + 1} node {role} kernel TUN state is invalid")

        phase = "overlay-convergence"

        def observe_overlay(overlay: int, timeout: float = 30) -> dict[str, Any]:
            base = overlay * 3
            return overlay_state([control(base + offset, "show", "status", timeout=timeout) for offset in range(3)],
                                 control(base + 2, "show", "tree", timeout=timeout), node_addrs[base:base + 3])

        def converged():
            for overlay in range(OVERLAYS):
                base = overlay * 3
                if observe_overlay(overlay) != INTACT_OVERLAY:
                    return None
                if not overlay_relationships(
                        [control(base + offset, "show", "peers") for offset in range(3)],
                        [control(base + offset, "show", "tree") for offset in range(3)],
                        identities[base:base + 3], node_addrs[base:base + 3]):
                    return None
            return [control(index, "show", "status") for index in range(len(DAEMONS))]

        statuses = _wait_for(converged, label="two authenticated overlays and their trees", timeout=60)

        phase = "endpoint-identity-resolution"
        for overlay in range(OVERLAYS):
            base = overlay * 3
            for namespace, remote in ((namespaces[0], base + 2), (namespaces[3], base)):
                query = _run(["ip", "netns", "exec", namespace, "dig", "@::1", "-p", str(FIPS_DNS_BASE_PORT + overlay),
                              f"{identities[remote]}.fips", "AAAA", "+short"],
                             label="local FIPS DNS resolution", timeout=10)
                answers = set()
                for line in query.stdout.splitlines():
                    try:
                        answers.add(ipaddress.IPv6Address(line.strip()))
                    except ipaddress.AddressValueError:
                        continue
                if ipaddress.IPv6Address(statuses[remote]["ipv6_addr"]) not in answers:
                    raise QualificationError("FIPS DNS did not return the remote overlay address")

        phase = "endpoint-routing"
        local_addresses = tuple(str(ipaddress.IPv6Address(statuses[overlay * 3]["ipv6_addr"]))
                                for overlay in range(OVERLAYS))
        remote_addresses = tuple(str(ipaddress.IPv6Address(statuses[overlay * 3 + 2]["ipv6_addr"]))
                                 for overlay in range(OVERLAYS))
        if len({*local_addresses, *remote_addresses}) != 2 * OVERLAYS:
            raise QualificationError("overlay endpoint addresses are not distinct")
        if [ipaddress.IPv6Address(item) for item in local_addresses] != sorted(
                ipaddress.IPv6Address(item) for item in local_addresses):
            raise QualificationError("overlay addresses on `a` are not in member order")
        for overlay in range(OVERLAYS):
            for namespace, address in ((namespaces[0], remote_addresses[overlay]),
                                       (namespaces[3], local_addresses[overlay])):
                _run(["ip", "-n", namespace, "-6", "route", "add", f"{address}/128",
                      "dev", ENDPOINT_TUN_NAMES[overlay]], label="add overlay host route")

        phase = "initial-data-plane"

        def probe(local: str, remote: str) -> bool:
            return _run(["ip", "netns", "exec", namespaces[0], "ping", "-6", "-c", "1", "-W", "2", "-s", "32",
                         "-I", local, remote], label="overlay probe", timeout=5, check=False).returncode == 0

        _wait_for(lambda: all(probe(local, remote) for local, remote in zip(local_addresses, remote_addresses)),
                  label="both overlay paths", timeout=45, interval=1)
        # Stop rule 2, overlay half: an address of one overlay must not reach the other overlay.
        if probe(local_addresses[0], remote_addresses[1]) or probe(local_addresses[1], remote_addresses[0]):
            raise QualificationError("the two overlays are not separate")

        phase = "srt-connect"
        flow_id = f"g5f-{run_id}"
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
        member_options = [option for local, remote, weight in zip(local_addresses, remote_addresses, MEMBER_WEIGHTS)
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
        _write_json(staging / "group-members.json",
                    group_member_record(described, group_type, local_addresses, remote_addresses))
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
            return current

        def observe_fips() -> None:
            unix_ns = time.time_ns()
            moment = time.monotonic_ns()
            overlays = [{"transit": MEMBER_TRANSITS[overlay], **observe_overlay(overlay, timeout=2)}
                        for overlay in range(OVERLAYS)]
            fips_observations.append(_envelope(
                source="fips", name=f"fips:{len(fips_observations)}", run_id=run_id, domain_id=domain_id,
                monotonic_ns=moment, unix_ns=unix_ns,
                payload={"metric_namespace": "fips.control", "metric_semantics": "overlay-link-state",
                         "observation_index": len(fips_observations), "overlays": overlays}))
            survivor = overlays[1 - FAULTED_MEMBER]
            # Stop rule 5.
            if {name: survivor.get(name) for name in INTACT_OVERLAY} != INTACT_OVERLAY:
                raise QualificationError("the overlay that was not faulted changed during the run")

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
                # Stage 1's stop rule 2: media flows, on both members in Broadcast, on member 0 in Backup.
                carried = [_positive(current["receiver"].get(member, {}).get("delta", {}).get(
                    "unique_received_packet_delta")) for member in range(MEMBERS)]
                states = [item["state"] for item in group_samples[-1]["members"]]
                expected = ([True, True], ["running", "running"]) if group_type == "broadcast" else \
                    ([True, False], ["running", "idle"])
                if (carried, states) != expected:
                    raise QualificationError("the group did not carry media as predeclared before the fault")
                if not fips_observations or fips_observations[-1]["payload"]["overlays"][FAULTED_MEMBER] != {
                        "transit": MEMBER_TRANSITS[FAULTED_MEMBER], **INTACT_OVERLAY}:
                    raise QualificationError("the overlay to be faulted was not intact before the fault")
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
            elif tick % FIPS_OBSERVATION_EVERY == 0:
                observe_fips()
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
                source_path = staging / f"{role}-source.member-{member}.jsonl"
                context_path = staging / f"{role}-context.member-{member}.json"
                observation_path = staging / f"{role}-observations.member-{member}.jsonl"
                _write_json(context_path, _member_context(domain_id, role, member, run_id))
                adapt_srt_telemetry_jsonl(source_path, context_path, observation_path)
                observations[role].append(_read_jsonl(observation_path))
        _write_jsonl(staging / "group-samples.jsonl", group_samples)
        _write_jsonl(staging / "fault-events.jsonl", fault_events)
        _write_jsonl(staging / "fips-observations.jsonl", fips_observations)
        collector_record = load_json(staging / "media-collector.json")
        source_record = load_json(staging / "media-source.json")
        timeline = compute_fips_group_timeline(
            compute_group_timeline(fault_events=fault_events, group_samples=group_samples,
                                   observations=observations, collector=collector_record, group_type=group_type),
            fault_events, fips_observations)
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
                "underlay": "diamond-veth-ipv4-udp", "overlay": "srt-ipv6-over-two-fips-overlays", "fips": True,
                "fips_daemons": len(DAEMONS), "overlays": OVERLAYS,
                "endpoint_tun_names": list(ENDPOINT_TUN_NAMES), "endpoint_routing": ENDPOINT_ROUTING,
                "alternate_path_one_way_delay_ms": ALTERNATE_PATH_ONE_WAY_DELAY_MS,
                "member_transits": list(MEMBER_TRANSITS), "faulted_transit": MEMBER_TRANSITS[FAULTED_MEMBER],
            },
            "profile": {
                "group_type": group_type,
                "members": MEMBERS,
                "member_weights": list(MEMBER_WEIGHTS),
                "fault": "transit-blackhole",
                "fips_timers": dict(FIPS_TIMERS),
                "fips_observation_interval_ms": SRT_SAMPLE_INTERVAL_NS * FIPS_OBSERVATION_EVERY // 1_000_000,
                "packet_budget": packet_budget,
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
                "fips_observations": len(fips_observations),
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
                "The endpoint routing is a lab workaround: FIPS v0.5.3 does not support two daemons in one "
                "namespace, so the lab removes the fd00::/8 route FIPS installs and adds host routes. The result "
                "does not show that FIPS supports this.",
                "Each overlay has exactly one route, so FIPS reconvergence is not exercised.",
                "The two overlays share one host, kernel and clock, and four of the six daemons share two "
                "namespaces; they are separate fault domains for this fault only.",
                "Each layer is observed at its own resolution (collector per datagram, SRT 500 ms, FIPS about "
                "1 s); temporal ordering does not establish a cause.",
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
        cleanup["fips_daemons_stopped"] = all(_stop_process(process) for process in daemons)
        for item in streams:
            if item is not None:
                item.close()
        if error is not None:
            _print_redacted_log_tails(daemon_logs)
        for namespace in namespaces:
            _run(["ip", "netns", "del", namespace], label="remove namespace", timeout=10, check=False)
        listing = _run(["ip", "netns", "list"], label="verify namespace cleanup", check=False).stdout
        cleanup["namespaces_removed"] = all(namespace not in listing for namespace in namespaces)
        shutil.rmtree(work, ignore_errors=True)
        cleanup["work_directory_removed"] = not work.exists()

    if error is None and not all(cleanup.values()):
        error = QualificationError("SRT-group-over-FIPS teardown did not complete")
        phase_at_failure = "teardown"
    if error is not None:
        failure = _failure_result(run_id, started_at, project_revision, phase_at_failure, cleanup, error)
        # Partial diagnostics stay beside the failed result; they are not evidence.
        diagnostics = {
            "schema_version": 1,
            "group_samples": group_samples[-40:],
            "fault_events": [item["payload"] | {"monotonic_ns": item["monotonic_ns"]} for item in fault_events],
            "fips_observations": [item["payload"] | {"monotonic_ns": item["monotonic_ns"]}
                                  for item in fips_observations[-20:]],
        }
        if not (staging / "diagnostics.json").exists():
            _write_json(staging / "diagnostics.json", diagnostics)
        if (staging / "result.json").exists():
            os.unlink(staging / "result.json")
        _write_json(staging / "result.json", failure)
        staging.rename(output_dir)
        raise QualificationError(
            f"SRT-group-over-FIPS experiment failed during {phase_at_failure}: {failure['failure_detail']}") from error
    assert result is not None
    result["cleanup"] = cleanup
    _write_json(staging / "result.json", result)
    validate_g5_srt_group_fips_bundle(staging)
    staging.rename(output_dir)
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_g5_srt_group_fips_result(result: Any) -> None:
    _require(isinstance(result, dict), "SRT-group-over-FIPS result must be an object")
    _require(result.get("schema_version") == 1 and result.get("evidence_type") == EVIDENCE_TYPE,
             "SRT-group-over-FIPS result schema/evidence_type is invalid")
    _require(result.get("classification") == "experiment" and result.get("gate_ids") == ["G5"],
             "SRT-group-over-FIPS result classification/gates are invalid")
    try:
        uuid.UUID(result.get("run_id", ""))
    except (TypeError, ValueError) as exc:
        raise ContractError("SRT-group-over-FIPS run_id is invalid") from exc
    conclusion = result.get("gate_conclusion")
    _require(isinstance(conclusion, dict) and set(conclusion) == {"G5", "reason"}
             and conclusion["G5"] == "not-passed" and isinstance(conclusion["reason"], str)
             and bool(conclusion["reason"]), "SRT-group-over-FIPS result must record G5 as not-passed")
    cleanup = result.get("cleanup")
    _require(isinstance(cleanup, dict) and set(cleanup) == set(CLEANUP_FIELDS)
             and all(isinstance(value, bool) for value in cleanup.values()),
             "SRT-group-over-FIPS cleanup is invalid")
    common = {"schema_version", "evidence_type", "status", "classification", "gate_ids", "run_id",
              "started_at", "finished_at", "cleanup", "gate_conclusion"}
    if result.get("status") == "failed":
        _require(set(result) == common | {"project_revision", "failure_phase", "failure_class", "failure_detail"},
                 "failed SRT-group-over-FIPS result fields are invalid")
        _require(bool(COMMIT_RE.fullmatch(result.get("project_revision", ""))),
                 "failed SRT-group-over-FIPS project revision is invalid")
        return
    _require(result.get("status") == "passed", "SRT-group-over-FIPS status is invalid")
    _require(set(result) == common | {"provenance", "platform", "clock", "topology", "profile", "capture",
                                      "timeline", "files", "limitations"},
             "passed SRT-group-over-FIPS result fields are invalid")
    _require(all(cleanup.values()), "passed SRT-group-over-FIPS result requires complete cleanup")
    provenance = result["provenance"]
    for field, expected in (("srt_repository", SRT_REPOSITORY), ("srt_commit", EXPECTED_SRT_COMMIT),
                            ("telemetry_repository", TELEMETRY_REPOSITORY),
                            ("telemetry_commit", EXPECTED_TELEMETRY_COMMIT),
                            ("fips_repository", FIPS_REPOSITORY), ("fips_commit", EXPECTED_FIPS_COMMIT),
                            ("fips_source_tree_state", "clean")):
        _require(provenance.get(field) == expected, f"SRT-group-over-FIPS provenance {field} is invalid")
    _require(str(provenance.get("ffmpeg_version", "")).startswith(EXPECTED_FFMPEG_VERSION + " "),
             "SRT-group-over-FIPS provenance ffmpeg_version is invalid")
    for field in ("srt_library_sha256", "incident_peer_sha256", "ffmpeg_binary_sha256",
                  "fips_binary_sha256", "fipsctl_binary_sha256", "cargo_lock_sha256", "rust_toolchain_sha256"):
        value = provenance.get(field)
        _require(isinstance(value, str) and len(value) == 64, f"SRT-group-over-FIPS provenance {field} is invalid")
    _require(bool(COMMIT_RE.fullmatch(provenance.get("project_revision", ""))),
             "SRT-group-over-FIPS provenance project_revision is invalid")
    clock = result["clock"]
    _require(clock.get("same_host") is True and clock.get("synchronization") == "local-only"
             and clock.get("cross_host_ordering_allowed") is False, "SRT-group-over-FIPS clock is invalid")
    topology = result["topology"]
    _require(topology.get("node_count") == 4 and topology.get("fips") is True
             and topology.get("fips_daemons") == len(DAEMONS) and topology.get("overlays") == OVERLAYS
             and topology.get("endpoint_tun_names") == list(ENDPOINT_TUN_NAMES)
             and topology.get("endpoint_routing") == ENDPOINT_ROUTING
             and topology.get("member_transits") == list(MEMBER_TRANSITS)
             and topology.get("faulted_transit") == MEMBER_TRANSITS[FAULTED_MEMBER],
             "SRT-group-over-FIPS topology is invalid")
    profile = result["profile"]
    budget = profile.get("packet_budget", {})
    _require(profile.get("group_type") in GROUP_TYPES and profile.get("members") == MEMBERS
             and profile.get("member_weights") == list(MEMBER_WEIGHTS)
             and profile.get("fault") == "transit-blackhole"
             and profile.get("fips_timers") == FIPS_TIMERS
             and profile.get("datagram_bytes") == DATAGRAM_BYTES
             and profile.get("srt_peer_idle_timeout_ms") == SRT_PEER_IDLE_TIMEOUT_MS
             and profile.get("inject_after_source_start_ms") == INJECT_AFTER_SOURCE_START_NS // 1_000_000
             and profile.get("fixture", {}).get("frames") == FIXTURE_FRAMES
             and profile.get("fixture", {}).get("encode") == list(FIXTURE_ENCODE)
             and profile.get("decode_options") == list(DECODE_OPTIONS),
             "SRT-group-over-FIPS profile is not the predeclared profile")
    _require(budget.get("endpoint_effective_ipv6_mtu") == [EFFECTIVE_IPV6_MTU] * (2 * OVERLAYS)
             and budget.get("clear_srt_payload_budget_bytes") == EFFECTIVE_IPV6_MTU - SRT_IPV6_UDP_HEADER_BYTES
             and budget.get("media_datagram_bytes") == DATAGRAM_BYTES <= budget["clear_srt_payload_budget_bytes"],
             "SRT-group-over-FIPS packet budget is invalid")
    capture = result["capture"]
    frames = capture.get("frames", {})
    _require(frames.get("expected_frames") == FIXTURE_FRAMES and capture.get("missed_sample_intervals") == 0,
             "SRT-group-over-FIPS capture is incomplete")
    _require(capture.get("hitless") is (frames.get("missing_frames") == 0 and frames.get("changed_frames") == 0),
             "SRT-group-over-FIPS hitless flag disagrees with the frame comparison")
    _require(set(result["files"]) == set(BUNDLE_FILES), "SRT-group-over-FIPS file inventory is invalid")
    limitations = result["limitations"]
    _require(isinstance(limitations, list) and len(limitations) >= 4
             and any("workaround" in item for item in limitations),
             "SRT-group-over-FIPS limitations are invalid")
    timeline = result["timeline"]
    _require(isinstance(timeline, dict) and timeline.get("causal_claim") is None,
             "SRT-group-over-FIPS timeline must not carry a causal claim")
    _require(timeline.get("surviving_overlay_stable") is True,
             "a passed SRT-group-over-FIPS result requires the other overlay to stay intact")


def validate_g5_srt_group_fips_bundle(directory: Path) -> None:
    directory = directory.resolve()
    result = load_json(directory / "result.json")
    validate_g5_srt_group_fips_result(result)
    if result["status"] == "failed":
        return
    for name, record in result["files"].items():
        try:
            actual = _file_record(directory / name)
        except OSError as exc:
            raise ContractError(f"cannot read SRT-group-over-FIPS file {name}: {exc}") from exc
        _require(actual == record, f"SRT-group-over-FIPS file digest/size mismatch: {name}")
    faults, _, base_timeline = validate_group_files(directory, result)
    fips = _read_jsonl(directory / "fips-observations.jsonl")
    _require(bool(fips) and result["capture"]["fips_observations"] == len(fips),
             "FIPS observation count disagrees with the retained observations")
    injection = next(event["monotonic_ns"] for event in faults
                     if event["source"] == "fabric" and event["payload"]["event"] == "blackhole-start")
    for index, envelope in enumerate(fips):
        validate_correlation_envelope(envelope)
        payload = envelope["payload"]
        overlays = payload.get("overlays")
        _require(envelope["source"] == "fips" and payload.get("metric_semantics") == "overlay-link-state"
                 and payload.get("observation_index") == index
                 and isinstance(overlays, list) and len(overlays) == OVERLAYS
                 and [item.get("transit") for item in overlays] == list(MEMBER_TRANSITS)
                 and all(set(item) == {"transit", *INTACT_OVERLAY} for item in overlays),
                 "FIPS observations are invalid")
    before = [item for item in fips if item["monotonic_ns"] < injection]
    _require(bool(before) and {name: before[-1]["payload"]["overlays"][FAULTED_MEMBER][name]
                               for name in INTACT_OVERLAY} == INTACT_OVERLAY,
             "the faulted overlay was not intact before the fault")
    members = load_json(directory / "group-members.json")
    addresses = []
    for item in members["members"]:
        for field in ("caller_address", "listener_address"):
            try:
                address = ipaddress.IPv6Address(item.get(field))
            except (ipaddress.AddressValueError, TypeError) as exc:
                raise ContractError("group member address is not an IPv6 address") from exc
            _require(address in ipaddress.IPv6Network(FIPS_PREFIX), "group member address is not a FIPS address")
            addresses.append(address)
    _require(len(set(addresses)) == 2 * MEMBERS, "group members do not use four distinct FIPS addresses")
    timeline = compute_fips_group_timeline(base_timeline, faults, fips)
    _require(timeline == result["timeline"], "timeline is not reproducible from the retained files")
