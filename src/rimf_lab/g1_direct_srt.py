"""G1 direct-SRT baseline: the control for the SRT-over-FIPS pilots.

The experiment reuses the G4 workload, incident peers, Telemetry adapter and
same-host ordering assessment, but runs the SRT peers directly over a veth pair
with no FIPS data plane, and repeats the transfer several times in one run.
Correctness is fail-closed; distortion indicators (retransmissions, loss, RTT,
completion time, peer CPU and RSS) are recorded without thresholds because the
performance budgets are not frozen (OD-01, OD-04, OD-14).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .contracts import (
    ContractError,
    load_json,
    validate_correlation_envelope,
    validate_srt_telemetry_observation,
)
from .cross_layer import assess_cross_layer_ordering
from .fips_g2_linux import (
    COMMIT_RE,
    QualificationError,
    _run,
    _validate_executable,
    sha256_file,
    utc_now,
)
from .g4_srt_over_fips import (
    ACTIVE_SAMPLE_COUNT,
    EXPECTED_SRT_COMMIT,
    EXPECTED_SRT_VERSION,
    EXPECTED_TELEMETRY_COMMIT,
    MESSAGE_BYTES,
    MESSAGE_COUNT,
    ROUTE_EPOCH,
    SAMPLE_INTERVAL_NS,
    SEND_PACING_MICROSECONDS,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
    _Peer,
    _adapter_context,
    _clock,
    _clock_domain,
    _file_record,
    _media_observation,
    _parse_prefixed_json,
    _peer_command,
    _read_jsonl,
    _recording_arguments,
    _sample_pair,
    _source_revision,
    _write_json,
)
from .srt_adapter import adapt_srt_telemetry_jsonl


EVIDENCE_TYPE = "g1-direct-srt-baseline"
# Retained G1 bundles are evidence only for their own recorded revisions.
# Each historical bundle is accepted solely when its result manifest matches
# the digest recorded here; a new run cannot present an old pin as current.
HISTORICAL_G1_BUNDLES = {
    # 2026-10-28, run 40743995008: SRT v0.3.1, Telemetry 1b12f8d7.
    "c27be270ebbd3b25946644e2f2d6338dc0676e679c557ab546e1c78b71632a75": {
        "srt_commit": "57fcf51a31ec2eecf4189d63c2f998ff1e8daaa1",
        "srt_version": "0.3.1",
        "telemetry_commit": "1b12f8d7d75658cb7b7e00a0575fc77d965dbbec",
    },
    # 2026-10-25, run 40189973066: SRT v0.3.1, Telemetry 1a018dfd.
    "98b352713b76c99a709067c17066a8b5949e048be81e4c896627e0e11acfd85c": {
        "srt_commit": "57fcf51a31ec2eecf4189d63c2f998ff1e8daaa1",
        "srt_version": "0.3.1",
        "telemetry_commit": "1a018dfdc89a964b03159aebc155d39bca524384",
    },
    # 2026-10-22, run 39806840201: SRT v0.3.0, Telemetry 24475483.
    "6b8d341b97ae0eef0d9a5d1b761231a0a17ae189d386b882a9dcb26283ca6827": {
        "srt_commit": "4ae6330d62f2b5030d96964bf3500283f32dd39c",
        "srt_version": "0.3.0",
        "telemetry_commit": "2447548388a47aaac647bb2eafdc4f9e962f0baa",
    },
}
HISTORICAL_G1_SRT_COMMITS = frozenset(
    bundle["srt_commit"] for bundle in HISTORICAL_G1_BUNDLES.values()
)
DEVICE_ID = "two-node-direct-control"
SENDER_EVENT_NAMESPACE = "3f0b1d6e-7a0c-5d5e-9a62-2f8e4a1c9b10"
RECEIVER_EVENT_NAMESPACE = "9c4d2e71-5b8f-5a3a-8e0d-6d1f7b2c3a44"
DEFAULT_REPETITIONS = 3
MAX_REPETITIONS = 10
LINK_MTU = 1500
ENDPOINT_ADDRESSES = ("fd00:1::1", "fd00:1::2")
ADDRESS_FAMILY = 6
ADDRESS_PREFIX_LENGTH = 64
REPETITION_FILES = (
    "sender-source.jsonl",
    "receiver-source.jsonl",
    "sender-context.json",
    "receiver-context.json",
    "sender-observations.jsonl",
    "receiver-observations.jsonl",
    "media-observation.json",
    "selected-srt-observation.json",
    "srt-media-ordering.json",
)
RECORDED_COUNTERS = (
    "sent_packet_total",
    "unique_sent_packet_total",
    "received_packet_total",
    "unique_received_packet_total",
    "retransmitted_packet_total",
    "sender_loss_packet_total",
    "receiver_loss_packet_total",
    "sender_drop_packet_total",
    "receiver_drop_packet_total",
    "sent_wire_byte_total",
    "received_wire_byte_total",
)
CLOCK_TICKS_PER_SECOND = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _counter(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QualificationError(f"incident peer sample {name} is not a non-negative integer")
    return value


def _peer_resources(peer: _Peer) -> dict[str, Any]:
    """Read CPU time and peak RSS of a live peer from /proc before it exits."""
    pid = peer.process.pid
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
    except OSError as exc:
        raise QualificationError("incident peer resource accounting is unavailable") from exc
    fields = stat[stat.rindex(")") + 2 :].split()
    utime_ticks = int(fields[11])
    stime_ticks = int(fields[12])
    peak_rss_kib = None
    for line in status.splitlines():
        if line.startswith("VmHWM:"):
            peak_rss_kib = int(line.split()[1])
    if peak_rss_kib is None:
        raise QualificationError("incident peer peak RSS is unavailable")
    return {
        "cpu_user_ms": round(utime_ticks * 1000 / CLOCK_TICKS_PER_SECOND),
        "cpu_system_ms": round(stime_ticks * 1000 / CLOCK_TICKS_PER_SECOND),
        "peak_rss_kib": peak_rss_kib,
        "accounting": "procfs-before-exit",
    }


def _endpoint_summary(samples: list[dict[str, Any]], resources: dict[str, Any]) -> dict[str, Any]:
    final = samples[-1]
    raw = final.get("raw") if isinstance(final.get("raw"), dict) else final
    counters = {name: _counter(raw.get(name), name) for name in RECORDED_COUNTERS}
    rtts = []
    for sample in samples:
        sample_raw = sample.get("raw") if isinstance(sample.get("raw"), dict) else sample
        rtt = sample_raw.get("rtt_seconds")
        if isinstance(rtt, (int, float)) and not isinstance(rtt, bool) and rtt >= 0:
            rtts.append(float(rtt))
    return {
        **counters,
        "rtt_seconds_min": min(rtts) if rtts else None,
        "rtt_seconds_max": max(rtts) if rtts else None,
        **resources,
    }


def _receiver_complete_sample_index(samples: list[dict[str, Any]]) -> int | None:
    for sample in samples:
        raw = sample.get("raw") if isinstance(sample.get("raw"), dict) else sample
        value = raw.get("unique_received_packet_total")
        if isinstance(value, int) and not isinstance(value, bool) and value >= MESSAGE_COUNT:
            index = sample.get("sampleIndex", sample.get("sample_index"))
            return index if isinstance(index, int) else None
    return None


def _range(values: list[Any]) -> list[Any] | None:
    clean = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if not clean:
        return None
    return [min(clean), max(clean)]


def _failure_result(
    run_id: str,
    started_at: str,
    finished_at: str,
    project_revision: str,
    phase: str,
    cleanup: dict[str, bool],
    error: Exception,
    completed_repetitions: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "evidence_type": EVIDENCE_TYPE,
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G1"],
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "project_revision": project_revision,
        "failure_phase": phase,
        "failure_class": type(error).__name__,
        "failure_detail": str(error)[:512],
        "completed_repetitions": completed_repetitions,
        "cleanup": cleanup,
        "gate_conclusion": {
            "G1": "not-passed",
            "reason": "experiment-failed-before-completion",
        },
    }


def run_g1_direct_srt_baseline(
    *,
    srt_source: Path,
    srt_library: Path,
    telemetry_source: Path,
    incident_peer: Path,
    library_dir: Path,
    output_dir: Path,
    project_revision: str,
    repetitions: int = DEFAULT_REPETITIONS,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    phase = "preflight"
    if platform.system() != "Linux":
        raise QualificationError("the G1 direct-SRT runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G1 direct-SRT runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    if not isinstance(repetitions, int) or not 1 <= repetitions <= MAX_REPETITIONS:
        raise QualificationError(f"repetitions must be between 1 and {MAX_REPETITIONS}")
    for utility in ("git", "ip"):
        if shutil.which(utility) is None:
            raise QualificationError(f"required utility is unavailable: {utility}")

    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise QualificationError("G1 output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    incident_peer = _validate_executable(incident_peer, "SRT telemetry incident peer")
    srt_library = srt_library.resolve()
    library_dir = library_dir.resolve()
    if not srt_library.is_file() or not library_dir.is_dir():
        raise QualificationError("SRT library or runtime library directory is unavailable")
    srt_revision = _source_revision(srt_source, EXPECTED_SRT_COMMIT, "Robotweax SRT")
    telemetry_revision = _source_revision(
        telemetry_source, EXPECTED_TELEMETRY_COMMIT, "SRT Telemetry"
    )
    peer_cli = _run(
        ["env", f"LD_LIBRARY_PATH={library_dir}", str(incident_peer), "--help"],
        label="incident peer CLI",
        check=False,
    )
    if (
        "--bind-address IP" not in peer_cli.stderr
        or "--message-bytes 1..1316" not in peer_cli.stderr
    ):
        raise QualificationError("incident peer does not expose the pinned addressable CLI")
    provenance = {
        "project_revision": project_revision,
        "srt_repository": SRT_REPOSITORY,
        "srt_commit": srt_revision,
        "srt_library_sha256": sha256_file(srt_library),
        "telemetry_repository": TELEMETRY_REPOSITORY,
        "telemetry_commit": telemetry_revision,
        "incident_peer_sha256": sha256_file(incident_peer),
    }
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    work = Path(tempfile.mkdtemp(prefix="rimf-g1-", dir="/tmp"))

    suffix = str(os.getpid())
    namespaces = (f"rimfg1a{suffix}", f"rimfg1b{suffix}")
    veths = (f"g1a{suffix}", f"g1b{suffix}")
    listener: _Peer | None = None
    caller: _Peer | None = None
    cleanup = {
        "srt_peers_stopped": False,
        "namespaces_removed": False,
        "work_directory_removed": False,
    }
    error: Exception | None = None
    result: dict[str, Any] | None = None
    repetition_results: list[dict[str, Any]] = []

    try:
        phase = "namespace-setup"
        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
        _run(
            ["ip", "link", "add", veths[0], "type", "veth", "peer", "name", veths[1]],
            label="create G1 veth pair",
        )
        for namespace, veth, address in zip(namespaces, veths, ENDPOINT_ADDRESSES):
            _run(["ip", "link", "set", veth, "netns", namespace], label="move G1 veth")
            _run(["ip", "-n", namespace, "link", "set", "lo", "up"], label="enable loopback")
            _run(
                ["ip", "-n", namespace, "link", "set", veth, "mtu", str(LINK_MTU)],
                label="set G1 veth MTU",
            )
            _run(
                [
                    "ip", "-n", namespace, f"-{ADDRESS_FAMILY}", "addr", "add",
                    f"{address}/{ADDRESS_PREFIX_LENGTH}", "dev", veth,
                    *(["nodad"] if ADDRESS_FAMILY == 6 else []),
                ],
                label="assign G1 endpoint address",
            )
            _run(["ip", "-n", namespace, "link", "set", veth, "up"], label="enable G1 veth")
        _run(
            [
                "ip", "netns", "exec", namespaces[0],
                "ping", f"-{ADDRESS_FAMILY}", "-c", "1", "-W", "2", ENDPOINT_ADDRESSES[1],
            ],
            label="G1 direct link reachability",
            timeout=5,
        )

        domain_id = _clock_domain()
        for repetition in range(1, repetitions + 1):
            phase = f"repetition-{repetition}-srt-connect"
            rep_dir = staging / f"rep-{repetition}"
            rep_dir.mkdir()
            flow_id = f"g1-{run_id}-{repetition}"
            sender_source = rep_dir / "sender-source.jsonl"
            receiver_source = rep_dir / "receiver-source.jsonl"
            listener = _Peer(
                _peer_command(
                    namespaces[1],
                    incident_peer,
                    library_dir,
                    _recording_arguments("listener", receiver_source, flow_id, EXPECTED_SRT_VERSION)
                    + ["--bind-address", ENDPOINT_ADDRESSES[1]],
                )
            )
            ready = _parse_prefixed_json(listener.wait_for("READY"), "READY")
            port = ready.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or not 0 < port <= 65_535:
                raise QualificationError("G1 SRT listener returned an invalid port")
            caller = _Peer(
                _peer_command(
                    namespaces[0],
                    incident_peer,
                    library_dir,
                    _recording_arguments("caller", sender_source, flow_id, EXPECTED_SRT_VERSION)
                    + ["--remote-address", ENDPOINT_ADDRESSES[1], "--port", str(port)],
                )
            )
            listener.wait_for("CONNECTED")
            caller.wait_for("CONNECTED")

            phase = f"repetition-{repetition}-capture"
            sender_samples: list[dict[str, Any]] = []
            receiver_samples: list[dict[str, Any]] = []
            schedule_errors_ns: list[int] = []
            sender, receiver = _sample_pair(listener, caller, 0)
            sender_samples.append(sender)
            receiver_samples.append(receiver)

            transfer = f"START_TRANSFER 1 {MESSAGE_COUNT} {SEND_PACING_MICROSECONDS}"
            listener.send(transfer)
            listener_started = _parse_prefixed_json(
                listener.wait_for("TRANSFER_STARTED"), "TRANSFER_STARTED"
            )
            caller.send(transfer)
            caller_started = _parse_prefixed_json(
                caller.wait_for("TRANSFER_STARTED"), "TRANSFER_STARTED"
            )
            expected_started = {"transferId": 1, "messages": MESSAGE_COUNT}
            if listener_started != expected_started or caller_started != expected_started:
                raise QualificationError("G1 SRT transfer did not start on both endpoints")

            transfer_started_ns = time.monotonic_ns()
            sampling_started = transfer_started_ns
            for sample_index in range(1, ACTIVE_SAMPLE_COUNT + 1):
                target = sampling_started + sample_index * SAMPLE_INTERVAL_NS
                remaining = target - time.monotonic_ns()
                if remaining > 0:
                    time.sleep(remaining / 1_000_000_000)
                now = time.monotonic_ns()
                if now - target >= SAMPLE_INTERVAL_NS:
                    raise QualificationError("G1 SRT sampling missed a complete 100 ms interval")
                schedule_errors_ns.append(now - target)
                sender, receiver = _sample_pair(listener, caller, sample_index)
                sender_samples.append(sender)
                receiver_samples.append(receiver)

            listener.send(f"WAIT_TRANSFER 1 {MESSAGE_COUNT}")
            caller.send(f"WAIT_TRANSFER 1 {MESSAGE_COUNT}")
            listener_done = _parse_prefixed_json(listener.wait_for("TRANSFERRED"), "TRANSFERRED")
            caller_done = _parse_prefixed_json(caller.wait_for("TRANSFERRED"), "TRANSFERRED")
            transfer_confirmed_ns = time.monotonic_ns()
            if listener_done != expected_started or caller_done != expected_started:
                raise QualificationError("G1 SRT receiver did not validate the complete transfer")
            media = _media_observation(run_id, domain_id)
            media["device_id"] = DEVICE_ID
            media["stream_id"] = flow_id
            media["event_id"] = str(
                uuid.uuid5(uuid.UUID(RECEIVER_EVENT_NAMESPACE), f"{flow_id}:media:complete")
            )
            validate_correlation_envelope(media)

            final_index = ACTIVE_SAMPLE_COUNT + 1
            sender, receiver = _sample_pair(listener, caller, final_index)
            sender_samples.append(sender)
            receiver_samples.append(receiver)
            sender_resources = _peer_resources(caller)
            receiver_resources = _peer_resources(listener)
            listener.send("DONE")
            caller.send("DONE")
            listener.wait_for("RECORDED")
            caller.wait_for("RECORDED")
            listener.finish()
            caller.finish()
            listener = None
            caller = None

            phase = f"repetition-{repetition}-adapter"
            sender_context_path = rep_dir / "sender-context.json"
            receiver_context_path = rep_dir / "receiver-context.json"
            for path, namespace_id in (
                (sender_context_path, SENDER_EVENT_NAMESPACE),
                (receiver_context_path, RECEIVER_EVENT_NAMESPACE),
            ):
                context = _adapter_context(domain_id, namespace_id, flow_id)
                context["fabric_identity"]["device_id"] = DEVICE_ID
                _write_json(path, context)
            sender_observations_path = rep_dir / "sender-observations.jsonl"
            receiver_observations_path = rep_dir / "receiver-observations.jsonl"
            adapt_srt_telemetry_jsonl(sender_source, sender_context_path, sender_observations_path)
            adapt_srt_telemetry_jsonl(
                receiver_source, receiver_context_path, receiver_observations_path
            )
            sender_observations = _read_jsonl(sender_observations_path)
            receiver_observations = _read_jsonl(receiver_observations_path)
            if len(sender_observations) != ACTIVE_SAMPLE_COUNT + 2 or len(
                receiver_observations
            ) != ACTIVE_SAMPLE_COUNT + 2:
                raise QualificationError("G1 adapted SRT observation count is invalid")
            for observation in sender_observations + receiver_observations:
                validate_srt_telemetry_observation(observation)

            media_path = rep_dir / "media-observation.json"
            selected_srt_path = rep_dir / "selected-srt-observation.json"
            ordering_path = rep_dir / "srt-media-ordering.json"
            _write_json(media_path, media)
            _write_json(selected_srt_path, sender_observations[-2])
            srt_media = assess_cross_layer_ordering(selected_srt_path, media_path, ordering_path)
            if srt_media["outcome"] != "ordered":
                raise QualificationError("shared host clock did not authorize G1 event ordering")

            sender_summary = _endpoint_summary(sender_samples, sender_resources)
            receiver_summary = _endpoint_summary(receiver_samples, receiver_resources)
            if (
                sender_summary["sender_drop_packet_total"] != 0
                or receiver_summary["receiver_drop_packet_total"] != 0
            ):
                raise QualificationError("G1 direct control dropped application packets")
            repetition_results.append(
                {
                    "index": repetition,
                    "flow_id": flow_id,
                    "application_exact_delivery": True,
                    "srt_samples_per_endpoint": ACTIVE_SAMPLE_COUNT + 2,
                    "sampling": {
                        "missed_intervals": 0,
                        "schedule_error_ns": schedule_errors_ns,
                        "max_abs_schedule_error_ns": max(abs(value) for value in schedule_errors_ns),
                    },
                    "receiver_complete_sample_index": _receiver_complete_sample_index(
                        receiver_samples
                    ),
                    "transfer_confirmed_after_ms": round(
                        (transfer_confirmed_ns - transfer_started_ns) / 1_000_000
                    ),
                    "endpoints": {"sender": sender_summary, "receiver": receiver_summary},
                    "srt_media_ordering": srt_media["ordering"],
                }
            )

        phase = "summary"
        files = {}
        for repetition in range(1, repetitions + 1):
            for name in REPETITION_FILES:
                relative = f"rep-{repetition}/{name}"
                files[relative] = _file_record(staging / relative)
        result = {
            "schema_version": 1,
            "evidence_type": EVIDENCE_TYPE,
            "status": "passed",
            "classification": "experiment",
            "gate_ids": ["G1"],
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": utc_now(),
            "provenance": provenance,
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "clock": {**_clock(domain_id), "same_host": True},
            "route_epoch": ROUTE_EPOCH,
            "topology": {
                "node_count": 2,
                "isolation": "linux-network-namespaces",
                "underlay": "direct-veth-ipv6",
                "overlay": "none",
                "link_mtu": LINK_MTU,
            },
            "workload": {
                "application_message_count": MESSAGE_COUNT,
                "application_message_bytes": MESSAGE_BYTES,
                "send_pacing_microseconds": SEND_PACING_MICROSECONDS,
                "sample_interval_ns": SAMPLE_INTERVAL_NS,
                "active_sample_count": ACTIVE_SAMPLE_COUNT,
                "repetitions": repetitions,
            },
            "repetitions": repetition_results,
            "summary": _summary(repetition_results),
            "files": files,
            "cleanup": cleanup,
            "gate_conclusion": {
                "G1": "not-passed",
                "reason": "single-run-direct-control-evidence; gate status changes require "
                "owner review of repeated retained runs",
            },
            "limitations": [
                "Direct veth path only; no loss, delay, reordering, bandwidth limit, "
                "backpressure, outage or route change was injected.",
                "Retransmission, loss, RTT, completion-time, CPU and RSS values are recorded "
                "without thresholds because performance budgets are not frozen.",
                "The provider-linked receiver validates application message identity but "
                "is not an independent media decoder.",
                "This is the control for the SRT-over-FIPS pilots, not a direct/FIPS "
                "comparison or a G3 scorecard.",
            ],
        }
    except Exception as exc:
        error = exc
    finally:
        phase_at_failure = phase
        peer_cleanup = [peer is None or peer.stop() for peer in (listener, caller)]
        cleanup["srt_peers_stopped"] = all(peer_cleanup)
        for namespace in namespaces:
            _run(
                ["ip", "netns", "del", namespace],
                label=f"remove G1 namespace {namespace}",
                timeout=10,
                check=False,
            )
        namespace_list = _run(
            ["ip", "netns", "list"], label="verify G1 namespace cleanup", check=False
        ).stdout
        cleanup["namespaces_removed"] = all(
            namespace not in namespace_list for namespace in namespaces
        )
        shutil.rmtree(work, ignore_errors=True)
        cleanup["work_directory_removed"] = not work.exists()

    if error is None and not all(cleanup.values()):
        error = QualificationError("G1 direct-SRT teardown did not complete")
        phase_at_failure = "teardown"
    if error is not None:
        result = _failure_result(
            run_id,
            started_at,
            utc_now(),
            project_revision,
            phase_at_failure,
            cleanup,
            error,
            len(repetition_results),
        )
        _write_json(staging / "result.json", result)
        _publish(staging, output_dir)
        raise QualificationError(
            f"G1 direct-SRT baseline failed during {phase_at_failure}"
        ) from error

    assert result is not None
    result["cleanup"] = cleanup
    result["finished_at"] = utc_now()
    _write_json(staging / "result.json", result)
    validate_g1_direct_srt_bundle(staging)
    _publish(staging, output_dir)
    return result


def _summary(repetitions: list[dict[str, Any]]) -> dict[str, Any]:
    def endpoint_values(role: str, field: str) -> list[Any]:
        return [item["endpoints"][role][field] for item in repetitions]

    return {
        "repetition_count": len(repetitions),
        "all_exact_delivery": all(item["application_exact_delivery"] for item in repetitions),
        "receiver_complete_sample_index_range": _range(
            [item["receiver_complete_sample_index"] for item in repetitions]
        ),
        "transfer_confirmed_after_ms_range": _range(
            [item["transfer_confirmed_after_ms"] for item in repetitions]
        ),
        "max_abs_schedule_error_ns_range": _range(
            [item["sampling"]["max_abs_schedule_error_ns"] for item in repetitions]
        ),
        "sender_retransmitted_packet_total_range": _range(
            endpoint_values("sender", "retransmitted_packet_total")
        ),
        "receiver_loss_packet_total_range": _range(
            endpoint_values("receiver", "receiver_loss_packet_total")
        ),
        "sender_rtt_seconds_max_range": _range(endpoint_values("sender", "rtt_seconds_max")),
        "sender_cpu_total_ms_range": _range(
            [
                item["endpoints"]["sender"]["cpu_user_ms"]
                + item["endpoints"]["sender"]["cpu_system_ms"]
                for item in repetitions
            ]
        ),
        "receiver_cpu_total_ms_range": _range(
            [
                item["endpoints"]["receiver"]["cpu_user_ms"]
                + item["endpoints"]["receiver"]["cpu_system_ms"]
                for item in repetitions
            ]
        ),
        "sender_peak_rss_kib_range": _range(endpoint_values("sender", "peak_rss_kib")),
        "receiver_peak_rss_kib_range": _range(endpoint_values("receiver", "peak_rss_kib")),
    }


def _publish(staging: Path, output_dir: Path) -> None:
    try:
        staging.rename(output_dir)
    except FileExistsError as exc:
        raise QualificationError("G1 output directory already exists") from exc


def _require_non_negative_int(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"{context} must be a non-negative integer")
    return value


def validate_g1_direct_srt_result(
    result: Any,
    *,
    expected_srt_commit: str = EXPECTED_SRT_COMMIT,
    expected_telemetry_commit: str = EXPECTED_TELEMETRY_COMMIT,
) -> None:
    if not isinstance(result, dict):
        raise ContractError("G1 result must be an object")
    common = {
        "schema_version",
        "evidence_type",
        "status",
        "classification",
        "gate_ids",
        "run_id",
        "started_at",
        "finished_at",
        "cleanup",
        "gate_conclusion",
    }
    if result.get("schema_version") != 1 or result.get("evidence_type") != EVIDENCE_TYPE:
        raise ContractError("G1 result schema/evidence_type is invalid")
    if result.get("classification") != "experiment" or result.get("gate_ids") != ["G1"]:
        raise ContractError("G1 result classification/gates are invalid")
    try:
        uuid.UUID(result.get("run_id", ""))
    except (ValueError, TypeError) as exc:
        raise ContractError("G1 result run_id is invalid") from exc
    cleanup = result.get("cleanup")
    expected_cleanup = {"srt_peers_stopped", "namespaces_removed", "work_directory_removed"}
    if not isinstance(cleanup, dict) or set(cleanup) != expected_cleanup or any(
        not isinstance(value, bool) for value in cleanup.values()
    ):
        raise ContractError("G1 result cleanup is invalid")
    conclusion = result.get("gate_conclusion")
    if (
        not isinstance(conclusion, dict)
        or set(conclusion) != {"G1", "reason"}
        or conclusion.get("G1") != "not-passed"
        or not isinstance(conclusion.get("reason"), str)
        or not conclusion["reason"]
    ):
        raise ContractError("G1 result must record G1 as not-passed with a reason")

    status = result.get("status")
    if status == "failed":
        required = common | {
            "project_revision",
            "failure_phase",
            "failure_class",
            "failure_detail",
            "completed_repetitions",
        }
        if set(result) != required:
            raise ContractError("failed G1 result fields are invalid")
        if not COMMIT_RE.fullmatch(result.get("project_revision", "")):
            raise ContractError("failed G1 project revision is invalid")
        _require_non_negative_int(result.get("completed_repetitions"), "completed_repetitions")
        return
    if status != "passed":
        raise ContractError("G1 result status is invalid")
    required = common | {
        "provenance",
        "platform",
        "clock",
        "route_epoch",
        "topology",
        "workload",
        "repetitions",
        "summary",
        "files",
        "limitations",
    }
    if set(result) != required:
        raise ContractError("passed G1 result fields are invalid")
    if not all(cleanup.values()):
        raise ContractError("passed G1 result requires complete cleanup")

    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        raise ContractError("G1 provenance is invalid")
    for field, expected in (
        ("srt_repository", SRT_REPOSITORY),
        ("srt_commit", expected_srt_commit),
        ("telemetry_repository", TELEMETRY_REPOSITORY),
        ("telemetry_commit", expected_telemetry_commit),
    ):
        if provenance.get(field) != expected:
            raise ContractError(f"G1 provenance {field} is invalid")
    if not COMMIT_RE.fullmatch(provenance.get("project_revision", "")):
        raise ContractError("G1 provenance project_revision is invalid")
    for field in ("srt_library_sha256", "incident_peer_sha256"):
        value = provenance.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ContractError(f"G1 provenance {field} is invalid")
    if set(provenance) != {
        "project_revision",
        "srt_repository",
        "srt_commit",
        "srt_library_sha256",
        "telemetry_repository",
        "telemetry_commit",
        "incident_peer_sha256",
    }:
        raise ContractError("G1 provenance fields are invalid")

    clock = result.get("clock")
    if (
        not isinstance(clock, dict)
        or clock.get("same_host") is not True
        or clock.get("synchronization") != "local-only"
        or clock.get("cross_host_ordering_allowed") is not False
        or clock.get("max_error_ns") is not None
        or not isinstance(clock.get("domain_id"), str)
        or not clock["domain_id"].startswith("linux-host-monotonic-")
    ):
        raise ContractError("G1 clock is invalid")
    if result.get("route_epoch") != ROUTE_EPOCH:
        raise ContractError("G1 route epoch is invalid")
    if result.get("topology") != {
        "node_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "direct-veth-ipv6",
        "overlay": "none",
        "link_mtu": LINK_MTU,
    }:
        raise ContractError("G1 topology is invalid")
    workload = result.get("workload")
    if not isinstance(workload, dict) or workload != {
        "application_message_count": MESSAGE_COUNT,
        "application_message_bytes": MESSAGE_BYTES,
        "send_pacing_microseconds": SEND_PACING_MICROSECONDS,
        "sample_interval_ns": SAMPLE_INTERVAL_NS,
        "active_sample_count": ACTIVE_SAMPLE_COUNT,
        "repetitions": workload.get("repetitions") if isinstance(workload, dict) else None,
    }:
        raise ContractError("G1 workload is invalid")
    repetition_count = workload["repetitions"]
    if (
        not isinstance(repetition_count, int)
        or isinstance(repetition_count, bool)
        or not 1 <= repetition_count <= MAX_REPETITIONS
    ):
        raise ContractError("G1 workload repetitions is invalid")

    repetitions = result.get("repetitions")
    if not isinstance(repetitions, list) or len(repetitions) != repetition_count:
        raise ContractError("G1 repetitions do not match the declared workload")
    for position, repetition in enumerate(repetitions, start=1):
        _validate_repetition(repetition, position, result["run_id"])
    if result.get("summary") != _summary(repetitions):
        raise ContractError("G1 summary does not match its repetitions")

    files = result.get("files")
    expected_files = {
        f"rep-{index}/{name}"
        for index in range(1, repetition_count + 1)
        for name in REPETITION_FILES
    }
    if not isinstance(files, dict) or set(files) != expected_files:
        raise ContractError("G1 file inventory is invalid")
    for name, record in files.items():
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or not isinstance(record.get("bytes"), int)
            or isinstance(record.get("bytes"), bool)
            or record["bytes"] <= 0
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
        ):
            raise ContractError(f"G1 file record {name} is invalid")
    limitations = result.get("limitations")
    if not isinstance(limitations, list) or len(limitations) < 3 or any(
        not isinstance(value, str) or not value for value in limitations
    ):
        raise ContractError("G1 limitations are invalid")


def _validate_repetition(repetition: Any, position: int, run_id: str) -> None:
    context = f"G1 repetition {position}"
    if not isinstance(repetition, dict) or set(repetition) != {
        "index",
        "flow_id",
        "application_exact_delivery",
        "srt_samples_per_endpoint",
        "sampling",
        "receiver_complete_sample_index",
        "transfer_confirmed_after_ms",
        "endpoints",
        "srt_media_ordering",
    }:
        raise ContractError(f"{context} fields are invalid")
    if repetition["index"] != position or repetition["flow_id"] != f"g1-{run_id}-{position}":
        raise ContractError(f"{context} identity is invalid")
    if repetition["application_exact_delivery"] is not True:
        raise ContractError(f"{context} did not deliver the application payload exactly")
    if repetition["srt_samples_per_endpoint"] != ACTIVE_SAMPLE_COUNT + 2:
        raise ContractError(f"{context} sample count is invalid")
    sampling = repetition["sampling"]
    if (
        not isinstance(sampling, dict)
        or set(sampling) != {"missed_intervals", "schedule_error_ns", "max_abs_schedule_error_ns"}
        or sampling["missed_intervals"] != 0
        or not isinstance(sampling["schedule_error_ns"], list)
        or len(sampling["schedule_error_ns"]) != ACTIVE_SAMPLE_COUNT
        or any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in sampling["schedule_error_ns"]
        )
        or sampling["max_abs_schedule_error_ns"]
        != max(abs(value) for value in sampling["schedule_error_ns"])
        or sampling["max_abs_schedule_error_ns"] >= SAMPLE_INTERVAL_NS
    ):
        raise ContractError(f"{context} sampling record is invalid")
    complete_index = repetition["receiver_complete_sample_index"]
    if complete_index is not None and (
        not isinstance(complete_index, int)
        or isinstance(complete_index, bool)
        or not 0 <= complete_index <= ACTIVE_SAMPLE_COUNT + 1
    ):
        raise ContractError(f"{context} receiver completion index is invalid")
    _require_non_negative_int(
        repetition["transfer_confirmed_after_ms"], f"{context} transfer_confirmed_after_ms"
    )
    endpoints = repetition["endpoints"]
    if not isinstance(endpoints, dict) or set(endpoints) != {"sender", "receiver"}:
        raise ContractError(f"{context} endpoints are invalid")
    for role, endpoint in endpoints.items():
        expected_fields = set(RECORDED_COUNTERS) | {
            "rtt_seconds_min",
            "rtt_seconds_max",
            "cpu_user_ms",
            "cpu_system_ms",
            "peak_rss_kib",
            "accounting",
        }
        if not isinstance(endpoint, dict) or set(endpoint) != expected_fields:
            raise ContractError(f"{context} {role} summary fields are invalid")
        for name in RECORDED_COUNTERS:
            _require_non_negative_int(endpoint[name], f"{context} {role} {name}")
        for name in ("cpu_user_ms", "cpu_system_ms", "peak_rss_kib"):
            _require_non_negative_int(endpoint[name], f"{context} {role} {name}")
        if endpoint["accounting"] != "procfs-before-exit":
            raise ContractError(f"{context} {role} accounting is invalid")
        for name in ("rtt_seconds_min", "rtt_seconds_max"):
            value = endpoint[name]
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
            ):
                raise ContractError(f"{context} {role} {name} is invalid")
    if (
        endpoints["sender"]["sender_drop_packet_total"] != 0
        or endpoints["receiver"]["receiver_drop_packet_total"] != 0
    ):
        raise ContractError(f"{context} recorded dropped application packets")
    if repetition["srt_media_ordering"] not in ("srt-before-peer", "peer-before-srt", "simultaneous"):
        raise ContractError(f"{context} ordering is invalid")


def validate_g1_direct_srt_bundle(directory: Path) -> None:
    directory = directory.resolve()
    result_path = directory / "result.json"
    result = load_json(result_path)
    provenance = result.get("provenance") if isinstance(result, dict) else None
    expected_srt_commit = EXPECTED_SRT_COMMIT
    expected_srt_version = EXPECTED_SRT_VERSION
    expected_telemetry_commit = EXPECTED_TELEMETRY_COMMIT
    # A bundle is historical when any recorded pin differs from the active set; it is
    # then accepted only through its digest-locked entry, with that entry's pins.
    current = (EXPECTED_SRT_COMMIT, EXPECTED_TELEMETRY_COMMIT)
    if isinstance(provenance, dict) and tuple(
        provenance.get(field) for field in ("srt_commit", "telemetry_commit")
    ) != current and provenance.get("srt_commit") in HISTORICAL_G1_SRT_COMMITS | {EXPECTED_SRT_COMMIT}:
        historical = HISTORICAL_G1_BUNDLES.get(sha256_file(result_path))
        if historical is None or any(
            historical[field] != provenance.get(field) for field in ("srt_commit", "telemetry_commit")
        ):
            raise ContractError("historical G1 result digest mismatch")
        expected_srt_commit = historical["srt_commit"]
        expected_srt_version = historical["srt_version"]
        expected_telemetry_commit = historical["telemetry_commit"]
    validate_g1_direct_srt_result(
        result,
        expected_srt_commit=expected_srt_commit,
        expected_telemetry_commit=expected_telemetry_commit,
    )
    if result["status"] == "failed":
        return
    for name, record in result["files"].items():
        path = directory / name
        try:
            actual = _file_record(path)
        except OSError as exc:
            raise ContractError(f"cannot read G1 bundle file {name}: {exc}") from exc
        if actual != record:
            raise ContractError(f"G1 bundle file digest/size mismatch: {name}")
    for repetition in result["repetitions"]:
        rep_dir = directory / f"rep-{repetition['index']}"
        for role in ("sender", "receiver"):
            records = _read_jsonl(rep_dir / f"{role}-source.jsonl")
            if (
                not records
                or records[0].get("providerVersion") != expected_srt_version
                or records[0].get("providerRevision") != expected_srt_commit
                or records[0].get("flowId") != repetition["flow_id"]
            ):
                raise ContractError(
                    f"G1 {role} provider identity does not match provenance in {rep_dir.name}"
                )
            with tempfile.TemporaryDirectory() as scratch:
                replay = Path(scratch) / f"{role}-observations.jsonl"
                adapt_srt_telemetry_jsonl(
                    rep_dir / f"{role}-source.jsonl",
                    rep_dir / f"{role}-context.json",
                    replay,
                )
                if replay.read_bytes() != (rep_dir / f"{role}-observations.jsonl").read_bytes():
                    raise ContractError(
                        f"G1 {role} observations are not a byte-exact adapter replay in {rep_dir.name}"
                    )
            observations = _read_jsonl(rep_dir / f"{role}-observations.jsonl")
            if len(observations) != ACTIVE_SAMPLE_COUNT + 2:
                raise ContractError(f"G1 {role} observation count is invalid in {rep_dir.name}")
            for observation in observations:
                validate_srt_telemetry_observation(observation)
        media = load_json(rep_dir / "media-observation.json")
        validate_correlation_envelope(media)
        payload = media.get("payload", {})
        if (
            media.get("device_id") != DEVICE_ID
            or media.get("stream_id") != repetition["flow_id"]
            or payload.get("message_count") != MESSAGE_COUNT
            or payload.get("message_bytes") != MESSAGE_BYTES
            or payload.get("exact_delivery") is not True
        ):
            raise ContractError(f"G1 media observation is invalid in {rep_dir.name}")
        selected = load_json(rep_dir / "selected-srt-observation.json")
        sender_observations = _read_jsonl(rep_dir / "sender-observations.jsonl")
        if selected != sender_observations[-2]:
            raise ContractError(f"G1 selected SRT observation is not the final active sample in {rep_dir.name}")
        ordering = load_json(rep_dir / "srt-media-ordering.json")
        inputs = ordering.get("inputs") if isinstance(ordering, dict) else None
        if (
            not isinstance(ordering, dict)
            or ordering.get("outcome") != "ordered"
            or ordering.get("ordering") != repetition["srt_media_ordering"]
            or not isinstance(inputs, dict)
            or inputs.get("srt", {}).get("sha256")
            != sha256_file(rep_dir / "selected-srt-observation.json")
            or inputs.get("peer", {}).get("sha256")
            != sha256_file(rep_dir / "media-observation.json")
        ):
            raise ContractError(f"G1 ordering assessment is invalid in {rep_dir.name}")
