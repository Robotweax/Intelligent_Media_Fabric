from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    COMMIT_RE,
    ContractError,
    load_json,
    validate_correlation_envelope,
    validate_g4_ordering_assessment,
    validate_srt_telemetry_observation,
)
from .cross_layer import assess_cross_layer_ordering
from .fips_g2_linux import (
    EXPECTED_FIPS_COMMIT,
    FIPS_REPOSITORY,
    IDENTITY_RE,
    QualificationError,
    _json_command,
    _json_value_command,
    _run,
    _source_provenance,
    _stop_process,
    _validate_executable,
    _wait_for,
    mesh_size_converged,
    render_config,
    sha256_file,
    utc_now,
    valid_connect_acknowledgement,
)
from .srt_adapter import adapt_srt_telemetry_jsonl


EXPECTED_SRT_COMMIT = "def14a7b6d8a2ba1860677414e415fd86bbc953a"
EXPECTED_TELEMETRY_COMMIT = "bf10da0431fdf23772210262755f745b62b6ff58"
SRT_REPOSITORY = "https://github.com/Robotweax/srt.git"
TELEMETRY_REPOSITORY = "https://github.com/Robotweax/srt_telemetry.git"
SENDER_EVENT_NAMESPACE = "86b17e98-889a-5e37-af06-9456c88e70bc"
RECEIVER_EVENT_NAMESPACE = "77498a2d-e83f-575f-8349-d6980f42269d"
EVENT_NAMESPACE = uuid.UUID("6f93a984-675d-5e9e-9195-eb76d8f6d27b")
ROUTE_EPOCH = 1
SAMPLE_INTERVAL_NS = 100_000_000
ACTIVE_SAMPLE_COUNT = 12
MESSAGE_COUNT = 240
MESSAGE_BYTES = 1_024
SEND_PACING_MICROSECONDS = 5_000
EXPECTED_BUNDLE_FILES = {
    "sender-source.jsonl",
    "receiver-source.jsonl",
    "sender-context.json",
    "receiver-context.json",
    "sender-observations.jsonl",
    "receiver-observations.jsonl",
    "fips-observations.jsonl",
    "media-observation.json",
    "selected-srt-observation.json",
    "selected-fips-observation.json",
    "srt-fips-ordering.json",
    "srt-media-ordering.json",
}


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        stream.write("\n")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for value in values:
            stream.write(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            stream.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read JSONL {path}: {exc}") from exc
    for index, line in enumerate(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid JSONL record {index} in {path}") from exc
        if not isinstance(value, dict):
            raise ContractError(f"JSONL record {index} in {path} is not an object")
        values.append(value)
    return values


def _file_record(path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _source_revision(source: Path, expected: str, label: str) -> str:
    source = source.resolve()
    if not source.is_dir():
        raise QualificationError(f"{label} source directory does not exist")
    revision = _run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], label=f"{label} source revision"
    ).stdout.strip()
    if revision != expected:
        raise QualificationError(f"{label} source revision does not match the pinned baseline")
    dirty = _run(
        ["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=no"],
        label=f"{label} source tree state",
    ).stdout.strip()
    if dirty:
        raise QualificationError(f"{label} tracked source tree is dirty")
    return revision


def _clock_domain() -> str:
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise QualificationError("Linux boot identity is unavailable") from exc
    if not boot_id:
        raise QualificationError("Linux boot identity is empty")
    digest = hashlib.sha256(boot_id.encode("ascii")).hexdigest()[:24]
    return f"linux-host-monotonic-{digest}"


def _clock(domain_id: str) -> dict[str, Any]:
    return {
        "domain_id": domain_id,
        "synchronization": "local-only",
        "max_error_ns": None,
        "cross_host_ordering_allowed": False,
    }


def _rfc3339_nano(unix_nano: int) -> str:
    seconds, fraction = divmod(unix_nano, 1_000_000_000)
    base = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{fraction:09d}Z"


def _parse_prefixed_json(line: str, prefix: str) -> dict[str, Any]:
    marker = f"{prefix} "
    if not line.startswith(marker):
        raise QualificationError(f"unexpected incident peer output while waiting for {prefix}")
    try:
        value = json.loads(line[len(marker) :])
    except json.JSONDecodeError as exc:
        raise QualificationError(f"incident peer returned invalid {prefix} JSON") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"incident peer {prefix} payload is not an object")
    return value


class _Peer:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._stdout: queue.Queue[str] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=40)
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, args=(self.process.stdout,), daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, args=(self.process.stderr,), daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self, stream) -> None:
        for line in stream:
            self._stdout.put(line.rstrip("\n"))

    def _read_stderr(self, stream) -> None:
        for line in stream:
            self._stderr.append(IDENTITY_RE.sub("<redacted-identity>", line.rstrip("\n")))

    def send(self, command: str) -> None:
        if self.process.poll() is not None or self.process.stdin is None:
            raise QualificationError("incident peer exited before coordinator command")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def wait_for(self, prefix: str, timeout: float = 20) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self._stdout.get(timeout=min(0.25, deadline - time.monotonic()))
            except queue.Empty:
                if self.process.poll() is not None:
                    detail = "; ".join(self._stderr)[:512]
                    raise QualificationError(
                        f"incident peer exited before {prefix}: {detail or 'no diagnostic'}"
                    )
                continue
            if line == prefix or line.startswith(prefix + " "):
                return line
        raise QualificationError(f"timed out waiting for incident peer {prefix}")

    def finish(self) -> None:
        try:
            return_code = self.process.wait(timeout=20)
        except subprocess.TimeoutExpired as exc:
            raise QualificationError("incident peer did not exit after DONE") from exc
        if return_code != 0:
            detail = "; ".join(self._stderr)[:512]
            raise QualificationError(f"incident peer failed: {detail or return_code}")

    def stop(self) -> bool:
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGINT)
                self.process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if self.process.poll() is None:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        return False
        return self.process.poll() is not None


def _peer_command(
    namespace: str,
    peer: Path,
    library_dir: Path,
    arguments: list[str],
) -> list[str]:
    return [
        "ip",
        "netns",
        "exec",
        namespace,
        "env",
        f"LD_LIBRARY_PATH={library_dir}",
        str(peer),
        *arguments,
    ]


def _recording_arguments(
    role: str, output: Path, flow_id: str, srt_version: str
) -> list[str]:
    return [
        "--role",
        role,
        "--jsonl-output",
        str(output),
        "--flow-id",
        flow_id,
        "--provider-version",
        srt_version,
        "--provider-revision",
        EXPECTED_SRT_COMMIT,
        "--build-profile",
        "ubuntu-24.04-release-shared-openssl",
        "--message-bytes",
        str(MESSAGE_BYTES),
        "--recorder-capacity",
        str(ACTIVE_SAMPLE_COUNT + 2),
    ]


def _sample_pair(
    listener: _Peer, caller: _Peer, sample_index: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    unix_nano = time.time_ns()
    monotonic_nano = time.monotonic_ns()
    command = f"SAMPLE {sample_index} {unix_nano} {monotonic_nano}"
    listener.send(command)
    caller.send(command)
    receiver = _parse_prefixed_json(listener.wait_for("INCIDENT_SAMPLE"), "INCIDENT_SAMPLE")
    sender = _parse_prefixed_json(caller.wait_for("INCIDENT_SAMPLE"), "INCIDENT_SAMPLE")
    for value, role in ((sender, "sender"), (receiver, "receiver")):
        if (
            value.get("provider") != "robotweax-srt"
            or value.get("role") != role
            or value.get("sampleIndex") != sample_index
            or value.get("observedAtUnixNano") != unix_nano
            or value.get("sampleMonotonicNano") != monotonic_nano
        ):
            raise QualificationError("incident peer did not preserve coordinator sample identity")
    return sender, receiver


def _mmp_observation(
    fipsctl: Path,
    socket: Path,
    run_id: str,
    sample_index: int,
    domain_id: str,
) -> dict[str, Any]:
    peer_view = _json_command(
        [str(fipsctl), "-s", str(socket), "show", "peers"],
        label="FIPS MMP capture",
    )
    peers = peer_view.get("peers")
    if not isinstance(peers, list) or len(peers) != 1:
        raise QualificationError("FIPS MMP capture did not expose exactly one peer")
    mmp = peers[0].get("mmp")
    if not isinstance(mmp, dict) or mmp.get("mode") != "full":
        raise QualificationError("FIPS MMP capture is not full")
    payload: dict[str, Any] = {
        "metric_namespace": "fips.mmp",
        "metric_semantics": "link-estimator",
        "mode": "full",
    }
    for field in ("loss_rate", "etx", "srtt_ms"):
        value = mmp.get(field)
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise QualificationError(f"FIPS MMP {field} is not finite")
        payload[field] = value
    unix_nano = time.time_ns()
    monotonic_nano = time.monotonic_ns()
    envelope = {
        "schema_version": 1,
        "event_id": str(uuid.uuid5(EVENT_NAMESPACE, f"{run_id}:fips:{sample_index}")),
        "source": "fips",
        "observed_at": _rfc3339_nano(unix_nano),
        "monotonic_ns": monotonic_nano,
        "route_epoch": ROUTE_EPOCH,
        "clock": _clock(domain_id),
        "tenant_id": "qualification",
        "device_id": "two-node-pilot",
        "stream_id": run_id,
        "quality": {"availability": "available", "confidence": 1.0, "reason": None},
        "payload": payload,
    }
    validate_correlation_envelope(envelope)
    return envelope


def _media_observation(run_id: str, domain_id: str) -> dict[str, Any]:
    unix_nano = time.time_ns()
    monotonic_nano = time.monotonic_ns()
    payload_digest = hashlib.sha256(
        bytes([ord("A") + 1]) * MESSAGE_BYTES * MESSAGE_COUNT
    ).hexdigest()
    envelope = {
        "schema_version": 1,
        "event_id": str(uuid.uuid5(EVENT_NAMESPACE, f"{run_id}:media:complete")),
        "source": "media-validator",
        "observed_at": _rfc3339_nano(unix_nano),
        "monotonic_ns": monotonic_nano,
        "route_epoch": ROUTE_EPOCH,
        "clock": _clock(domain_id),
        "tenant_id": "qualification",
        "device_id": "two-node-pilot",
        "stream_id": run_id,
        "quality": {"availability": "available", "confidence": 1.0, "reason": None},
        "payload": {
            "metric_namespace": "media.application",
            "metric_semantics": "receiver-byte-identity",
            "message_count": MESSAGE_COUNT,
            "message_bytes": MESSAGE_BYTES,
            "stream_sha256": payload_digest,
            "exact_delivery": True,
        },
    }
    validate_correlation_envelope(envelope)
    return envelope


def _adapter_context(domain_id: str, event_namespace: str, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_namespace": event_namespace,
        "route_epoch": ROUTE_EPOCH,
        "clock": _clock(domain_id),
        "fabric_identity": {
            "tenant_id": "qualification",
            "device_id": "two-node-pilot",
            "stream_id": run_id,
            "mapping": {
                "tenant_id": "explicit-policy",
                "device_id": "explicit-policy",
                "stream_id": "explicit-policy",
            },
        },
        "source_identifiers_pseudonymous": True,
        "telemetry_revision": EXPECTED_TELEMETRY_COMMIT,
    }


def _publish_staging(staging: Path, output_dir: Path) -> None:
    try:
        staging.rename(output_dir)
    except FileExistsError as exc:
        raise QualificationError("G4 output directory already exists") from exc


def _failure_result(
    run_id: str,
    started_at: str,
    finished_at: str,
    project_revision: str,
    phase: str,
    cleanup: dict[str, bool],
    error: Exception,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "evidence_type": "g4-srt-over-fips-live",
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G3", "G4"],
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "project_revision": project_revision,
        "failure_phase": phase,
        "failure_class": type(error).__name__,
        "failure_detail": IDENTITY_RE.sub("<redacted-identity>", str(error))[:512],
        "cleanup": cleanup,
        "gate_conclusion": {
            "G3": "not-passed",
            "G4": "not-passed",
            "reason": "live-capture-failed",
        },
    }


def run_g4_srt_over_fips_live(
    *,
    fips_source: Path,
    fips_binary: Path,
    fipsctl_binary: Path,
    srt_source: Path,
    srt_library: Path,
    telemetry_source: Path,
    incident_peer: Path,
    library_dir: Path,
    output_dir: Path,
    project_revision: str,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    phase = "preflight"
    if platform.system() != "Linux":
        raise QualificationError("the G4 SRT-over-FIPS runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G4 SRT-over-FIPS runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("git", "ip"):
        if shutil.which(utility) is None:
            raise QualificationError(f"required utility is unavailable: {utility}")

    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise QualificationError("G4 output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    fips_binary = _validate_executable(fips_binary, "fips")
    fipsctl_binary = _validate_executable(fipsctl_binary, "fipsctl")
    incident_peer = _validate_executable(incident_peer, "SRT telemetry incident peer")
    srt_library = srt_library.resolve()
    library_dir = library_dir.resolve()
    if not srt_library.is_file() or not library_dir.is_dir():
        raise QualificationError("SRT library or runtime library directory is unavailable")
    provenance = _source_provenance(fips_source)
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
    provenance.update(
        {
            "project_revision": project_revision,
            "srt_repository": SRT_REPOSITORY,
            "srt_commit": srt_revision,
            "srt_library_sha256": sha256_file(srt_library),
            "telemetry_repository": TELEMETRY_REPOSITORY,
            "telemetry_commit": telemetry_revision,
            "incident_peer_sha256": sha256_file(incident_peer),
            "fips_binary_sha256": sha256_file(fips_binary),
            "fipsctl_binary_sha256": sha256_file(fipsctl_binary),
        }
    )
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    work = Path(tempfile.mkdtemp(prefix="rimf-g4-", dir="/tmp"))

    suffix = str(os.getpid())
    namespaces = (f"rimfg4a{suffix}", f"rimfg4b{suffix}")
    veths = (f"g4a{suffix}", f"g4b{suffix}")
    node_dirs = (work / "node-a", work / "node-b")
    sockets = (node_dirs[0] / "control.sock", node_dirs[1] / "control.sock")
    configs = (node_dirs[0] / "fips.yaml", node_dirs[1] / "fips.yaml")
    logs = (node_dirs[0] / "daemon.log", node_dirs[1] / "daemon.log")
    underlay = ("10.204.0.1", "10.204.0.2")
    daemons: list[subprocess.Popen | None] = [None, None]
    daemon_streams = []
    listener: _Peer | None = None
    caller: _Peer | None = None
    cleanup = {
        "srt_peers_stopped": False,
        "fips_daemons_stopped": False,
        "namespaces_removed": False,
        "ephemeral_identity_directory_removed": False,
    }
    error: Exception | None = None
    result: dict[str, Any] | None = None

    try:
        phase = "namespace-setup"
        for node_dir in node_dirs:
            node_dir.mkdir(mode=0o700)
        for config, socket_path, address in zip(configs, sockets, underlay):
            config.write_text(render_config(socket_path, address), encoding="utf-8")
            config.chmod(0o600)
        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
        _run(
            ["ip", "link", "add", veths[0], "type", "veth", "peer", "name", veths[1]],
            label="create G4 underlay veth pair",
        )
        for namespace, veth, address in zip(namespaces, veths, underlay):
            _run(["ip", "link", "set", veth, "netns", namespace], label="move G4 veth")
            _run(["ip", "-n", namespace, "link", "set", "lo", "up"], label="enable loopback")
            _run(
                ["ip", "-n", namespace, "addr", "add", f"{address}/30", "dev", veth],
                label="assign G4 underlay",
            )
            _run(["ip", "-n", namespace, "link", "set", veth, "up"], label="enable G4 veth")

        phase = "fips-start"
        for index, (namespace, config, log) in enumerate(zip(namespaces, configs, logs)):
            stream = log.open("w", encoding="utf-8")
            daemon_streams.append(stream)
            daemons[index] = subprocess.Popen(
                ["ip", "netns", "exec", namespace, str(fips_binary), "-c", str(config)],
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

        def controls_ready():
            if any(process is None or process.poll() is not None for process in daemons):
                raise QualificationError(
                    "a FIPS daemon exited before its control socket was ready"
                )
            return all(path.is_socket() for path in sockets)

        _wait_for(controls_ready, label="G4 FIPS control sockets", timeout=30)

        def status(index: int) -> dict[str, Any]:
            return _json_command(
                [str(fipsctl_binary), "-s", str(sockets[index]), "show", "status"],
                label=f"G4 node {index} status",
            )

        statuses = [status(0), status(1)]
        for node_status in statuses:
            if node_status.get("tun_state") != "active" or node_status.get("tun_name") != "fips0":
                raise QualificationError("G4 FIPS TUN did not become active")
        peer_b = statuses[1].get("npub")
        if not isinstance(peer_b, str) or not peer_b.startswith("npub1"):
            raise QualificationError("G4 node B identity is invalid")
        phase = "fips-connect"
        acknowledgement = _json_command(
            [
                str(fipsctl_binary),
                "-s",
                str(sockets[0]),
                "connect",
                peer_b,
                f"{underlay[1]}:2121",
                "udp",
            ],
            label="connect G4 FIPS nodes",
        )
        if not valid_connect_acknowledgement(acknowledgement, peer_b, f"{underlay[1]}:2121"):
            raise QualificationError("G4 FIPS connect acknowledgement is invalid")

        def connected():
            current = [status(0), status(1)]
            if all(
                item.get("peer_count") == 1 and item.get("link_count") == 1
                for item in current
            ) and mesh_size_converged(current):
                return current
            return None

        statuses = _wait_for(connected, label="G4 authenticated FIPS link", timeout=30)
        destination = statuses[1].get("ipv6_addr")
        if not isinstance(destination, str) or not destination.startswith("fd"):
            raise QualificationError("G4 destination FIPS address is invalid")

        def full_mmp_ready():
            peer_view = _json_command(
                [str(fipsctl_binary), "-s", str(sockets[0]), "show", "peers"],
                label="G4 initial MMP view",
            )
            peers = peer_view.get("peers")
            if not isinstance(peers, list) or len(peers) != 1:
                return None
            mmp = peers[0].get("mmp")
            return peer_view if isinstance(mmp, dict) and mmp.get("mode") == "full" else None

        _wait_for(full_mmp_ready, label="G4 full MMP observation", timeout=30)

        phase = "srt-connect"
        sender_source = staging / "sender-source.jsonl"
        receiver_source = staging / "receiver-source.jsonl"
        flow_id = f"g4-{run_id}"
        listener = _Peer(
            _peer_command(
                namespaces[1],
                incident_peer,
                library_dir,
                _recording_arguments("listener", receiver_source, flow_id, "0.2.4")
                + ["--bind-address", destination],
            )
        )
        ready = _parse_prefixed_json(listener.wait_for("READY"), "READY")
        port = ready.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port <= 65_535:
            raise QualificationError("G4 SRT listener returned an invalid port")
        caller = _Peer(
            _peer_command(
                namespaces[0],
                incident_peer,
                library_dir,
                _recording_arguments("caller", sender_source, flow_id, "0.2.4")
                + ["--remote-address", destination, "--port", str(port)],
            )
        )
        listener.wait_for("CONNECTED")
        caller.wait_for("CONNECTED")

        domain_id = _clock_domain()
        fips_observations = []
        sender_samples = []
        receiver_samples = []
        phase = "simultaneous-capture"
        sender, receiver = _sample_pair(listener, caller, 0)
        sender_samples.append(sender)
        receiver_samples.append(receiver)
        fips_observations.append(
            _mmp_observation(fipsctl_binary, sockets[0], run_id, 0, domain_id)
        )

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
            raise QualificationError("G4 SRT transfer did not start on both endpoints")

        sampling_started = time.monotonic_ns()
        for sample_index in range(1, ACTIVE_SAMPLE_COUNT + 1):
            target = sampling_started + sample_index * SAMPLE_INTERVAL_NS
            remaining = target - time.monotonic_ns()
            if remaining > 0:
                time.sleep(remaining / 1_000_000_000)
            if time.monotonic_ns() - target >= SAMPLE_INTERVAL_NS:
                raise QualificationError("G4 SRT sampling missed a complete 100 ms interval")
            sender, receiver = _sample_pair(listener, caller, sample_index)
            sender_samples.append(sender)
            receiver_samples.append(receiver)
            fips_observations.append(
                _mmp_observation(
                    fipsctl_binary, sockets[0], run_id, sample_index, domain_id
                )
            )

        listener.send(f"WAIT_TRANSFER 1 {MESSAGE_COUNT}")
        caller.send(f"WAIT_TRANSFER 1 {MESSAGE_COUNT}")
        listener_done = _parse_prefixed_json(listener.wait_for("TRANSFERRED"), "TRANSFERRED")
        caller_done = _parse_prefixed_json(caller.wait_for("TRANSFERRED"), "TRANSFERRED")
        if listener_done != expected_started or caller_done != expected_started:
            raise QualificationError("G4 SRT receiver did not validate the complete transfer")
        media = _media_observation(run_id, domain_id)

        final_index = ACTIVE_SAMPLE_COUNT + 1
        sender, receiver = _sample_pair(listener, caller, final_index)
        sender_samples.append(sender)
        receiver_samples.append(receiver)
        fips_observations.append(
            _mmp_observation(fipsctl_binary, sockets[0], run_id, final_index, domain_id)
        )
        listener.send("DONE")
        caller.send("DONE")
        listener.wait_for("RECORDED")
        caller.wait_for("RECORDED")
        listener.finish()
        caller.finish()

        phase = "adapter-and-correlation"
        sender_context_path = staging / "sender-context.json"
        receiver_context_path = staging / "receiver-context.json"
        _write_json(
            sender_context_path,
            _adapter_context(domain_id, SENDER_EVENT_NAMESPACE, run_id),
        )
        _write_json(
            receiver_context_path,
            _adapter_context(domain_id, RECEIVER_EVENT_NAMESPACE, run_id),
        )
        sender_observations_path = staging / "sender-observations.jsonl"
        receiver_observations_path = staging / "receiver-observations.jsonl"
        adapt_srt_telemetry_jsonl(sender_source, sender_context_path, sender_observations_path)
        adapt_srt_telemetry_jsonl(
            receiver_source, receiver_context_path, receiver_observations_path
        )
        sender_observations = _read_jsonl(sender_observations_path)
        receiver_observations = _read_jsonl(receiver_observations_path)
        if len(sender_observations) != ACTIVE_SAMPLE_COUNT + 2 or len(
            receiver_observations
        ) != ACTIVE_SAMPLE_COUNT + 2:
            raise QualificationError("G4 adapted SRT observation count is invalid")
        for observation in sender_observations + receiver_observations:
            validate_srt_telemetry_observation(observation)

        fips_path = staging / "fips-observations.jsonl"
        media_path = staging / "media-observation.json"
        _write_jsonl(fips_path, fips_observations)
        _write_json(media_path, media)
        selected_srt_path = staging / "selected-srt-observation.json"
        selected_fips_path = staging / "selected-fips-observation.json"
        _write_json(selected_srt_path, sender_observations[-2])
        _write_json(selected_fips_path, fips_observations[-2])
        srt_fips_path = staging / "srt-fips-ordering.json"
        srt_media_path = staging / "srt-media-ordering.json"
        srt_fips = assess_cross_layer_ordering(
            selected_srt_path, selected_fips_path, srt_fips_path
        )
        srt_media = assess_cross_layer_ordering(
            selected_srt_path, media_path, srt_media_path
        )
        if srt_fips["outcome"] != "ordered" or srt_media["outcome"] != "ordered":
            raise QualificationError("shared host clock did not authorize G4 event ordering")

        files = {
            name: _file_record(staging / name) for name in sorted(EXPECTED_BUNDLE_FILES)
        }
        result = {
            "schema_version": 1,
            "evidence_type": "g4-srt-over-fips-live",
            "status": "passed",
            "classification": "experiment",
            "gate_ids": ["G3", "G4"],
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
                "underlay": "direct-veth-ipv4-udp",
                "overlay": "srt-ipv6-over-fips0",
            },
            "capture": {
                "srt_samples_per_endpoint": ACTIVE_SAMPLE_COUNT + 2,
                "fips_observation_count": len(fips_observations),
                "sample_interval_ns": SAMPLE_INTERVAL_NS,
                "application_message_count": MESSAGE_COUNT,
                "application_message_bytes": MESSAGE_BYTES,
                "application_exact_delivery": True,
                "srt_fips_ordering": srt_fips["ordering"],
                "srt_media_ordering": srt_media["ordering"],
            },
            "files": files,
            "cleanup": cleanup,
            "gate_conclusion": {
                "G3": "not-passed",
                "G4": "not-passed",
                "reason": "single-healthy-live-pilot-without-fault-or-route-transition",
            },
            "limitations": [
                "One healthy direct-veth FIPS path only; no loss, delay, outage, "
                "or route transition was injected.",
                "The provider-linked receiver validates application message identity but "
                "is not yet an independent media decoder.",
                "Authorized temporal ordering does not identify a first divergent layer, "
                "fault domain, or root cause.",
                "This experiment does not authorize route, SRT, encoder, relay, "
                "or other control mutation.",
            ],
        }
    except Exception as exc:
        error = exc
    finally:
        phase_at_failure = phase
        peer_cleanup = [peer is None or peer.stop() for peer in (listener, caller)]
        cleanup["srt_peers_stopped"] = all(peer_cleanup)
        daemon_cleanup = [_stop_process(process) for process in daemons]
        cleanup["fips_daemons_stopped"] = all(daemon_cleanup)
        for stream in daemon_streams:
            stream.close()
        for namespace in namespaces:
            _run(
                ["ip", "netns", "del", namespace],
                label=f"remove G4 namespace {namespace}",
                timeout=10,
                check=False,
            )
        namespace_list = _run(
            ["ip", "netns", "list"], label="verify G4 namespace cleanup", check=False
        ).stdout
        cleanup["namespaces_removed"] = all(
            namespace not in namespace_list for namespace in namespaces
        )
        shutil.rmtree(work, ignore_errors=True)
        cleanup["ephemeral_identity_directory_removed"] = not work.exists()

    if error is None and not all(cleanup.values()):
        error = QualificationError("G4 live-capture teardown did not complete")
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
        )
        _write_json(staging / "result.json", result)
        _publish_staging(staging, output_dir)
        raise QualificationError(
            f"G4 SRT-over-FIPS live capture failed during {phase_at_failure}"
        ) from error

    assert result is not None
    result["cleanup"] = cleanup
    result["finished_at"] = utc_now()
    _write_json(staging / "result.json", result)
    validate_g4_live_capture_bundle(staging)
    _publish_staging(staging, output_dir)
    return result


def validate_g4_live_capture_result(result: Any) -> None:
    if not isinstance(result, dict):
        raise ContractError("G4 live result must be an object")
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
    if result.get("schema_version") != 1 or result.get("evidence_type") != "g4-srt-over-fips-live":
        raise ContractError("G4 live result schema/evidence_type is invalid")
    if result.get("classification") != "experiment" or result.get("gate_ids") != ["G3", "G4"]:
        raise ContractError("G4 live result classification/gates are invalid")
    try:
        uuid.UUID(result.get("run_id", ""))
    except (ValueError, TypeError) as exc:
        raise ContractError("G4 live result run_id is invalid") from exc
    cleanup = result.get("cleanup")
    expected_cleanup = {
        "srt_peers_stopped",
        "fips_daemons_stopped",
        "namespaces_removed",
        "ephemeral_identity_directory_removed",
    }
    if not isinstance(cleanup, dict) or set(cleanup) != expected_cleanup or any(
        not isinstance(value, bool) for value in cleanup.values()
    ):
        raise ContractError("G4 live result cleanup is invalid")
    conclusion = result.get("gate_conclusion")
    if conclusion != {
        "G3": "not-passed",
        "G4": "not-passed",
        "reason": conclusion.get("reason") if isinstance(conclusion, dict) else None,
    }:
        raise ContractError("G4 live result must not claim G3 or G4 passage")
    if not isinstance(conclusion.get("reason"), str) or not conclusion["reason"]:
        raise ContractError("G4 live result gate conclusion reason is invalid")

    status = result.get("status")
    if status == "failed":
        required = common | {
            "project_revision",
            "failure_phase",
            "failure_class",
            "failure_detail",
        }
        if set(result) != required:
            raise ContractError("failed G4 live result fields are invalid")
        if not COMMIT_RE.fullmatch(result.get("project_revision", "")):
            raise ContractError("failed G4 live project revision is invalid")
        return
    if status != "passed":
        raise ContractError("G4 live result status is invalid")
    required = common | {
        "provenance",
        "platform",
        "clock",
        "route_epoch",
        "topology",
        "capture",
        "files",
        "limitations",
    }
    if set(result) != required:
        raise ContractError("passed G4 live result fields are invalid")
    if not all(cleanup.values()):
        raise ContractError("passed G4 live result requires complete cleanup")
    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        raise ContractError("G4 live provenance is invalid")
    for field, expected in (
        ("fips_repository", FIPS_REPOSITORY),
        ("fips_commit", EXPECTED_FIPS_COMMIT),
        ("fips_source_tree_state", "clean"),
        ("srt_repository", SRT_REPOSITORY),
        ("srt_commit", EXPECTED_SRT_COMMIT),
        ("telemetry_repository", TELEMETRY_REPOSITORY),
        ("telemetry_commit", EXPECTED_TELEMETRY_COMMIT),
    ):
        if provenance.get(field) != expected:
            raise ContractError(f"G4 live provenance {field} is invalid")
    if not COMMIT_RE.fullmatch(provenance.get("project_revision", "")):
        raise ContractError("G4 live provenance project_revision is invalid")
    for field in (
        "cargo_lock_sha256",
        "rust_toolchain_sha256",
        "srt_library_sha256",
        "incident_peer_sha256",
        "fips_binary_sha256",
        "fipsctl_binary_sha256",
    ):
        digest = provenance.get(field)
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ContractError(f"G4 live provenance {field} is invalid")
    clock = result.get("clock")
    if (
        not isinstance(clock, dict)
        or clock.get("synchronization") != "local-only"
        or clock.get("same_host") is not True
        or clock.get("cross_host_ordering_allowed") is not False
        or clock.get("max_error_ns") is not None
    ):
        raise ContractError("G4 live clock contract is invalid")
    if result.get("route_epoch") != ROUTE_EPOCH:
        raise ContractError("G4 live route epoch is invalid")
    capture = result.get("capture")
    if (
        not isinstance(capture, dict)
        or capture.get("srt_samples_per_endpoint") != ACTIVE_SAMPLE_COUNT + 2
        or capture.get("fips_observation_count") != ACTIVE_SAMPLE_COUNT + 2
        or capture.get("application_message_count") != MESSAGE_COUNT
        or capture.get("application_message_bytes") != MESSAGE_BYTES
        or capture.get("application_exact_delivery") is not True
    ):
        raise ContractError("G4 live capture summary is invalid")
    files = result.get("files")
    if not isinstance(files, dict) or set(files) != EXPECTED_BUNDLE_FILES:
        raise ContractError("G4 live bundle file inventory is invalid")
    for name, record in files.items():
        if (
            not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or not isinstance(record.get("bytes"), int)
            or record["bytes"] <= 0
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
        ):
            raise ContractError(f"G4 live bundle file record is invalid: {name}")
    limitations = result.get("limitations")
    if not isinstance(limitations, list) or len(limitations) < 3 or any(
        not isinstance(value, str) or not value for value in limitations
    ):
        raise ContractError("G4 live limitations are invalid")


def validate_g4_live_capture_bundle(directory: Path) -> None:
    directory = directory.resolve()
    result = load_json(directory / "result.json")
    validate_g4_live_capture_result(result)
    if result["status"] == "failed":
        return
    for name, record in result["files"].items():
        path = directory / name
        try:
            actual = _file_record(path)
        except OSError as exc:
            raise ContractError(f"cannot read G4 live bundle file {name}: {exc}") from exc
        if actual != record:
            raise ContractError(f"G4 live bundle file digest/size mismatch: {name}")

    sender = _read_jsonl(directory / "sender-observations.jsonl")
    receiver = _read_jsonl(directory / "receiver-observations.jsonl")
    fips = _read_jsonl(directory / "fips-observations.jsonl")
    if len(sender) != ACTIVE_SAMPLE_COUNT + 2 or len(receiver) != ACTIVE_SAMPLE_COUNT + 2:
        raise ContractError("G4 live adapted SRT sample count is invalid")
    if len(fips) != ACTIVE_SAMPLE_COUNT + 2:
        raise ContractError("G4 live FIPS sample count is invalid")
    for observation in sender + receiver:
        validate_srt_telemetry_observation(observation)
    for observation in fips:
        validate_correlation_envelope(observation)
    media = load_json(directory / "media-observation.json")
    validate_correlation_envelope(media)
    selected_srt = load_json(directory / "selected-srt-observation.json")
    selected_fips = load_json(directory / "selected-fips-observation.json")
    validate_srt_telemetry_observation(selected_srt)
    validate_correlation_envelope(selected_fips)
    if selected_srt != sender[-2] or selected_fips != fips[-2]:
        raise ContractError("G4 live selected observations are not the declared timeline entries")
    assessments = {}
    for name in ("srt-fips-ordering.json", "srt-media-ordering.json"):
        assessment = load_json(directory / name)
        validate_g4_ordering_assessment(assessment)
        if assessment.get("outcome") != "ordered":
            raise ContractError(f"G4 live assessment is not ordered: {name}")
        assessments[name] = assessment
    selected_srt_digest = sha256_file(directory / "selected-srt-observation.json")
    selected_fips_digest = sha256_file(directory / "selected-fips-observation.json")
    media_digest = sha256_file(directory / "media-observation.json")
    if (
        assessments["srt-fips-ordering.json"]["inputs"]["srt"]["sha256"]
        != selected_srt_digest
        or assessments["srt-fips-ordering.json"]["inputs"]["peer"]["sha256"]
        != selected_fips_digest
        or assessments["srt-media-ordering.json"]["inputs"]["srt"]["sha256"]
        != selected_srt_digest
        or assessments["srt-media-ordering.json"]["inputs"]["peer"]["sha256"]
        != media_digest
    ):
        raise ContractError("G4 live assessment input digests do not match selected artifacts")
    if (
        result["capture"]["srt_fips_ordering"]
        != assessments["srt-fips-ordering.json"]["ordering"]
        or result["capture"]["srt_media_ordering"]
        != assessments["srt-media-ordering.json"]["ordering"]
    ):
        raise ContractError("G4 live capture summary differs from ordering assessments")

    with tempfile.TemporaryDirectory(prefix="rimf-g4-replay-") as temporary:
        replay = Path(temporary)
        for role in ("sender", "receiver"):
            output = replay / f"{role}-observations.jsonl"
            adapt_srt_telemetry_jsonl(
                directory / f"{role}-source.jsonl",
                directory / f"{role}-context.json",
                output,
            )
            if output.read_bytes() != (directory / f"{role}-observations.jsonl").read_bytes():
                raise ContractError(f"G4 live {role} adapter output is not byte-reproducible")
