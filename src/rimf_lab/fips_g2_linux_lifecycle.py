from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .fips_g2_linux import (
    COMMIT_RE,
    EFFECTIVE_IPV6_MTU,
    FIPS_REPOSITORY,
    IDENTITY_RE,
    TUN_MTU,
    UDP_PAYLOAD_SIZES,
    QualificationError,
    _json_command,
    _json_value_command,
    _print_redacted_log_tails,
    _run,
    _source_provenance,
    _stop_process,
    _validate_executable,
    _wait_for,
    _write_result,
    mesh_size_converged,
    sha256_file,
    utc_now,
)


LINK_DEAD_TIMEOUT_SECS = 30
HEARTBEAT_INTERVAL_SECS = 10
TICK_INTERVAL_SECS = 1
RETRY_BASE_INTERVAL_SECS = 5
RETRY_MAX_BACKOFF_SECS = 300
FAILURE_DETECTION_BUDGET_SECS = 60
RECONNECT_BUDGET_SECS = 90
UDP_PROBE_PORT = 42044
NPUB_RE = re.compile(r"^npub1[0-9a-z]+$")


def render_lifecycle_config(
    control_socket: Path,
    bind_address: str,
    *,
    peer_npub: str | None = None,
    peer_address: str | None = None,
) -> str:
    if (peer_npub is None) != (peer_address is None):
        raise ValueError("peer npub and address must be supplied together")
    if peer_npub is not None and not NPUB_RE.fullmatch(peer_npub):
        raise ValueError("peer npub is invalid")

    peers = "peers: []"
    if peer_npub is not None and peer_address is not None:
        peers = f'''peers:
  - npub: "{peer_npub}"
    alias: "node-b"
    addresses:
      - transport: "udp"
        addr: "{peer_address}:2121"
        priority: 100
    connect_policy: "auto_connect"
    auto_reconnect: true
    via_nostr: false'''

    return f'''node:
  identity:
    persistent: true
  control:
    enabled: true
    socket_path: "{control_socket}"
  tick_interval_secs: {TICK_INTERVAL_SECS}
  heartbeat_interval_secs: {HEARTBEAT_INTERVAL_SECS}
  link_dead_timeout_secs: {LINK_DEAD_TIMEOUT_SECS}
  retry:
    max_retries: 5
    base_interval_secs: {RETRY_BASE_INTERVAL_SECS}
    max_backoff_secs: {RETRY_MAX_BACKOFF_SECS}
  log_level: warn

tun:
  enabled: true
  name: "fips0"
  mtu: {TUN_MTU}

dns:
  enabled: false

transports:
  udp:
    bind_addr: "{bind_address}:2121"
    mtu: {TUN_MTU}

{peers}
'''


def lifecycle_timings_within_contract(
    failure_detection_elapsed_ms: int, reconnect_elapsed_ms: int
) -> bool:
    return (
        0 < failure_detection_elapsed_ms <= FAILURE_DETECTION_BUDGET_SECS * 1000
        and 0 < reconnect_elapsed_ms <= RECONNECT_BUDGET_SECS * 1000
    )


def _hard_kill_process(process: subprocess.Popen | None) -> bool:
    if process is None or process.poll() is not None:
        return False
    try:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        return False
    return process.returncode == -signal.SIGKILL


def _safe_failure_result(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    phase: str,
    project_revision: str,
    cleanup: dict,
    error: Exception,
) -> dict:
    return {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-lifecycle",
        "run_id": run_id,
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G2"],
        "started_at": started_at,
        "finished_at": finished_at,
        "project_revision": project_revision,
        "failure_phase": phase,
        "failure_class": type(error).__name__,
        "failure_detail": IDENTITY_RE.sub("<redacted-identity>", str(error))[:512],
        "cleanup": cleanup,
    }


def run_fips_g2_linux_lifecycle(
    *,
    fips_source: Path,
    fips_binary: Path,
    fipsctl_binary: Path,
    output: Path,
    project_revision: str,
) -> dict:
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    phase = "preflight"
    if platform.system() != "Linux":
        raise QualificationError("the G2 lifecycle runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G2 lifecycle runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("git", "ip", "ping"):
        if shutil.which(utility) is None:
            raise QualificationError(f"required utility is unavailable: {utility}")

    fips_binary = _validate_executable(fips_binary, "fips")
    fipsctl_binary = _validate_executable(fipsctl_binary, "fipsctl")
    provenance = _source_provenance(fips_source)
    provenance.update(
        {
            "project_revision": project_revision,
            "fips_binary_sha256": sha256_file(fips_binary),
            "fipsctl_binary_sha256": sha256_file(fipsctl_binary),
            "reported_version": _run(
                [str(fips_binary), "--version"], label="FIPS version"
            ).stdout.strip(),
        }
    )
    if provenance["fips_repository"] != FIPS_REPOSITORY:
        raise QualificationError("unexpected FIPS repository provenance")

    suffix = str(os.getpid())
    namespaces = (f"rimfg2la{suffix}", f"rimfg2lb{suffix}")
    veths = (f"g2la{suffix}", f"g2lb{suffix}")
    if any(len(name) > 15 for name in (*namespaces, *veths)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")

    work = Path(tempfile.mkdtemp(prefix="rimf-g2-lifecycle-", dir="/tmp"))
    node_dirs = (work / "node-a", work / "node-b")
    sockets = (node_dirs[0] / "control.sock", node_dirs[1] / "control.sock")
    configs = (node_dirs[0] / "fips.yaml", node_dirs[1] / "fips.yaml")
    daemon_logs = (node_dirs[0] / "daemon.log", node_dirs[1] / "daemon.log")
    underlay_addresses = ("10.206.0.1", "10.206.0.2")
    daemon_processes: list[subprocess.Popen | None] = [None, None]
    daemon_streams: list[object | None] = [None, None]
    payload_processes: list[subprocess.Popen] = []
    cleanup = {
        "daemons_stopped": False,
        "faulted_daemon_reaped": False,
        "namespaces_removed": False,
        "persistent_identity_directory_removed": False,
    }
    observations: dict = {}
    error: Exception | None = None

    def start_daemon(index: int, *, append: bool) -> None:
        previous_stream = daemon_streams[index]
        if previous_stream is not None:
            previous_stream.close()
        stream = daemon_logs[index].open("a" if append else "w", encoding="utf-8")
        daemon_streams[index] = stream
        daemon_processes[index] = subprocess.Popen(
            [
                "ip",
                "netns",
                "exec",
                namespaces[index],
                str(fips_binary),
                "-c",
                str(configs[index]),
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

    def status(index: int) -> dict:
        return _json_command(
            [str(fipsctl_binary), "-s", str(sockets[index]), "show", "status"],
            label=f"node {index} status",
        )

    def wait_for_control(index: int, *, old_pid: int | None = None) -> dict:
        def ready():
            process = daemon_processes[index]
            if process is None or process.poll() is not None:
                raise QualificationError(
                    f"node {index} daemon exited before its control socket was ready"
                )
            try:
                current = status(index)
            except QualificationError:
                return None
            pid = current.get("pid")
            if old_pid is not None and pid == old_pid:
                return None
            return current

        return _wait_for(ready, label=f"node {index} FIPS control socket", timeout=30)

    def validate_node(index: int, node_status: dict) -> dict:
        if (
            node_status.get("tun_state") != "active"
            or node_status.get("tun_name") != "fips0"
            or node_status.get("effective_ipv6_mtu") != EFFECTIVE_IPV6_MTU
            or node_status.get("persistent") is not True
        ):
            raise QualificationError(f"node {index} runtime state is invalid")
        link_data = _json_value_command(
            ["ip", "-n", namespaces[index], "-j", "link", "show", "dev", "fips0"],
            label=f"node {index} kernel TUN state",
        )
        if (
            not isinstance(link_data, list)
            or len(link_data) != 1
            or link_data[0].get("mtu") != TUN_MTU
        ):
            raise QualificationError(f"node {index} kernel TUN state is invalid")
        try:
            ipv6_address = str(ipaddress.IPv6Address(node_status.get("ipv6_addr", "")))
        except ipaddress.AddressValueError as exc:
            raise QualificationError(f"node {index} mesh address is invalid") from exc
        if not ipv6_address.startswith("fd"):
            raise QualificationError(f"node {index} did not receive a FIPS ULA")
        return {
            "node": "a" if index == 0 else "b",
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": TUN_MTU,
            "effective_ipv6_mtu": EFFECTIVE_IPV6_MTU,
            "persistent_identity": True,
        }

    def connected_statuses(*, timeout: float) -> list[dict]:
        def connected():
            current = [status(0), status(1)]
            if all(
                item.get("peer_count") == 1 and item.get("link_count") == 1
                for item in current
            ) and mesh_size_converged(current):
                return current
            return None

        return _wait_for(connected, label="authenticated two-node link", timeout=timeout)

    def measured_peer_views() -> list[dict]:
        def measured():
            current = [
                _json_command(
                    [str(fipsctl_binary), "-s", str(sockets[index]), "show", "peers"],
                    label=f"node {index} peer view",
                )
                for index in range(2)
            ]
            peers = [item.get("peers") for item in current]
            if not all(isinstance(items, list) and len(items) == 1 for items in peers):
                return None
            measurements = [items[0].get("mmp") for items in peers]
            if all(
                isinstance(item, dict)
                and item.get("mode") == "full"
                and isinstance(item.get("srtt_ms"), (int, float))
                for item in measurements
            ):
                return current
            return None

        return _wait_for(measured, label="full MMP observations", timeout=30)

    def summarize_mmp(peer_views: list[dict]) -> list[dict]:
        result = []
        for index, peer_view in enumerate(peer_views):
            peers = peer_view.get("peers")
            mmp = peers[0].get("mmp") if isinstance(peers, list) and peers else None
            if not isinstance(mmp, dict) or mmp.get("mode") != "full":
                raise QualificationError(f"node {index} MMP view is invalid")
            result.append(
                {
                    "node": "a" if index == 0 else "b",
                    "mode": "full",
                    "loss_rate": mmp.get("loss_rate"),
                    "etx": mmp.get("etx"),
                    "srtt_ms_observed": isinstance(mmp.get("srtt_ms"), (int, float)),
                }
            )
        return result

    def run_payload_probe(label: str, destination: str) -> list[dict]:
        ready_path = work / f"payload-{label}.ready"
        server_result_path = work / f"payload-{label}-server.json"
        client_result_path = work / f"payload-{label}-client.json"
        server = subprocess.Popen(
            [
                "ip",
                "netns",
                "exec",
                namespaces[1],
                sys.executable,
                "-m",
                "rimf_lab.payload_probe",
                "server",
                "--bind",
                destination,
                "--port",
                str(UDP_PROBE_PORT),
                "--count",
                str(len(UDP_PAYLOAD_SIZES)),
                "--ready",
                str(ready_path),
                "--output",
                str(server_result_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        payload_processes.append(server)

        def server_ready():
            if server.poll() is not None:
                raise QualificationError(f"{label} payload server exited before becoming ready")
            return ready_path.is_file()

        _wait_for(server_ready, label=f"{label} payload server", timeout=10)
        _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                sys.executable,
                "-m",
                "rimf_lab.payload_probe",
                "client",
                "--destination",
                destination,
                "--port",
                str(UDP_PROBE_PORT),
                "--sizes",
                *[str(size) for size in UDP_PAYLOAD_SIZES],
                "--output",
                str(client_result_path),
            ],
            label=f"{label} deterministic UDP identity probe",
            timeout=120,
        )
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise QualificationError(f"{label} payload server did not finish") from exc
        if server.returncode != 0:
            raise QualificationError(f"{label} payload server failed")
        try:
            server_result = json.loads(server_result_path.read_text(encoding="utf-8"))
            client_result = json.loads(client_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualificationError(f"{label} payload result is invalid") from exc
        records = client_result.get("records")
        if server_result.get("records") != [
            {"bytes": item["bytes"], "sha256": item["sha256"]}
            for item in records or []
        ]:
            raise QualificationError(f"{label} payload sender and receiver digests disagree")
        if (
            not isinstance(records, list)
            or [item.get("bytes") for item in records] != list(UDP_PAYLOAD_SIZES)
            or not all(item.get("exact_echo") is True for item in records)
        ):
            raise QualificationError(f"{label} payload identity result is incomplete")
        return records

    try:
        phase = "namespace-and-identity-setup"
        for node_dir in node_dirs:
            node_dir.mkdir(mode=0o700)
            _run(
                [str(fipsctl_binary), "keygen", "--dir", str(node_dir)],
                label="generate temporary persistent identity",
            )
        identities = tuple(
            (node_dir / "fips.pub").read_text(encoding="utf-8").strip()
            for node_dir in node_dirs
        )
        if not all(NPUB_RE.fullmatch(identity) for identity in identities):
            raise QualificationError("temporary key generation did not expose valid public keys")
        if not all(
            stat.S_IMODE((node_dir / "fips.key").stat().st_mode) == 0o600
            and stat.S_IMODE((node_dir / "fips.pub").stat().st_mode) == 0o644
            for node_dir in node_dirs
        ):
            raise QualificationError("temporary identity file modes are invalid")

        configs[0].write_text(
            render_lifecycle_config(
                sockets[0],
                underlay_addresses[0],
                peer_npub=identities[1],
                peer_address=underlay_addresses[1],
            ),
            encoding="utf-8",
        )
        configs[1].write_text(
            render_lifecycle_config(sockets[1], underlay_addresses[1]),
            encoding="utf-8",
        )
        for config in configs:
            config.chmod(0o600)

        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
        _run(
            ["ip", "link", "add", veths[0], "type", "veth", "peer", "name", veths[1]],
            label="create underlay veth pair",
        )
        for namespace, veth, address in zip(namespaces, veths, underlay_addresses):
            _run(["ip", "link", "set", veth, "netns", namespace], label="move underlay interface")
            _run(["ip", "-n", namespace, "link", "set", "lo", "up"], label="bring loopback up")
            _run(
                ["ip", "-n", namespace, "addr", "add", f"{address}/30", "dev", veth],
                label="assign underlay address",
            )
            _run(
                ["ip", "-n", namespace, "link", "set", veth, "up"],
                label="bring underlay interface up",
            )

        phase = "initial-daemon-start"
        start_daemon(1, append=False)
        initial_b_status = wait_for_control(1)
        start_daemon(0, append=False)
        initial_a_status = wait_for_control(0)
        initial_statuses = connected_statuses(timeout=45)
        initial_nodes = [
            validate_node(index, node_status)
            for index, node_status in enumerate(initial_statuses)
        ]
        if (
            initial_a_status.get("npub") != identities[0]
            or initial_b_status.get("npub") != identities[1]
        ):
            raise QualificationError("daemon identity did not match the temporary key file")
        initial_b_pid = initial_b_status.get("pid")
        if not isinstance(initial_b_pid, int):
            raise QualificationError("node B did not expose a numeric daemon pid")
        initial_b_mesh_address = initial_b_status.get("ipv6_addr")

        phase = "initial-data-plane"
        initial_mmp = summarize_mmp(measured_peer_views())
        destination = initial_statuses[1].get("ipv6_addr")
        _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                "ping",
                "-6",
                "-c",
                "2",
                "-W",
                "5",
                "-s",
                "1155",
                destination,
            ],
            label="initial effective-MTU-boundary ICMPv6 probe",
            timeout=20,
        )
        initial_payload = run_payload_probe("before-restart", destination)

        def sessions_observed():
            current = [status(0), status(1)]
            if all(item.get("session_count", 0) >= 1 for item in current):
                return current
            return None

        initial_session_statuses = _wait_for(
            sessions_observed, label="initial FSP sessions", timeout=30
        )
        initial_session_counts = [item["session_count"] for item in initial_session_statuses]

        phase = "hard-daemon-failure"
        failure_started = time.monotonic()
        if not _hard_kill_process(daemon_processes[1]):
            raise QualificationError("node B did not terminate from SIGKILL")
        cleanup["faulted_daemon_reaped"] = True
        daemon_processes[1] = None
        if daemon_streams[1] is not None:
            daemon_streams[1].close()
            daemon_streams[1] = None

        phase = "link-dead-detection"

        def link_dead_detected():
            current = status(0)
            if (
                current.get("peer_count") == 0
                and current.get("link_count") == 0
                and current.get("session_count") == 0
            ):
                return current
            return None

        _wait_for(
            link_dead_detected,
            label="link-dead peer/link/session removal",
            timeout=FAILURE_DETECTION_BUDGET_SECS,
        )
        failure_detection_elapsed_ms = round((time.monotonic() - failure_started) * 1000)
        outage_probe = _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                "ping",
                "-6",
                "-c",
                "1",
                "-W",
                "2",
                "-s",
                "32",
                destination,
            ],
            label="outage data-plane probe",
            timeout=5,
            check=False,
        )
        if outage_probe.returncode == 0:
            raise QualificationError("data-plane probe unexpectedly succeeded during outage")

        phase = "daemon-restart-and-auto-reconnect"
        restart_started = time.monotonic()
        start_daemon(1, append=True)
        restarted_b_status = wait_for_control(1, old_pid=initial_b_pid)
        if (
            restarted_b_status.get("npub") != identities[1]
            or restarted_b_status.get("ipv6_addr") != initial_b_mesh_address
            or restarted_b_status.get("persistent") is not True
        ):
            raise QualificationError("node B identity changed across restart")
        restarted_statuses = connected_statuses(timeout=RECONNECT_BUDGET_SECS)
        reconnect_elapsed_ms = round((time.monotonic() - restart_started) * 1000)
        if not lifecycle_timings_within_contract(
            failure_detection_elapsed_ms, reconnect_elapsed_ms
        ):
            raise QualificationError("lifecycle timing exceeded the qualification budget")
        restarted_nodes = [
            validate_node(index, node_status)
            for index, node_status in enumerate(restarted_statuses)
        ]

        phase = "post-restart-data-plane"
        post_restart_mmp = summarize_mmp(measured_peer_views())
        _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                "ping",
                "-6",
                "-c",
                "2",
                "-W",
                "5",
                "-s",
                "1155",
                destination,
            ],
            label="post-restart effective-MTU-boundary ICMPv6 probe",
            timeout=20,
        )
        post_restart_payload = run_payload_probe("after-restart", destination)
        post_restart_session_statuses = _wait_for(
            sessions_observed, label="post-restart FSP sessions", timeout=30
        )
        post_restart_session_counts = [
            item["session_count"] for item in post_restart_session_statuses
        ]

        phase = "controlled-disconnect"
        disconnect_result = _json_command(
            [str(fipsctl_binary), "-s", str(sockets[0]), "disconnect", identities[1]],
            label="disconnect node A from node B",
        )
        if disconnect_result.get("disconnected") is not True:
            raise QualificationError("FIPS control did not acknowledge disconnect")

        def disconnected_statuses():
            current = [status(0), status(1)]
            if all(
                item.get("peer_count") == 0
                and item.get("link_count") == 0
                and item.get("session_count") == 0
                for item in current
            ):
                return current
            return None

        _wait_for(
            disconnected_statuses,
            label="clean post-restart peer/link/session removal",
            timeout=30,
        )

        observations = {
            "nodes_before_failure": initial_nodes,
            "initial_connection": {
                "configured_auto_connect_peers": 1,
                "manual_connect_commands": 0,
                "authenticated_peers_per_node": 1,
                "links_per_node": 1,
                "estimated_mesh_size": 2,
                "transport": "udp",
            },
            "initial_mmp": initial_mmp,
            "initial_payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0",
                "records": initial_payload,
                "all_exact_echo": True,
            },
            "initial_fsp_session_counts": initial_session_counts,
            "failure_injection": {
                "failed_node": "b",
                "signal": "SIGKILL",
                "graceful_disconnect_sent": False,
                "process_exit_observed": True,
            },
            "link_dead_detection": {
                "tick_interval_secs": TICK_INTERVAL_SECS,
                "heartbeat_interval_secs": HEARTBEAT_INTERVAL_SECS,
                "link_dead_timeout_secs": LINK_DEAD_TIMEOUT_SECS,
                "detection_budget_secs": FAILURE_DETECTION_BUDGET_SECS,
                "detection_elapsed_ms": failure_detection_elapsed_ms,
                "observer": "node-a",
                "peers_after": 0,
                "links_after": 0,
                "fsp_sessions_after": 0,
                "outage_probe_blocked": True,
            },
            "identity_continuity": {
                "persistent_identity_configured_per_node": [True, True],
                "private_key_file_mode": "0600",
                "public_key_file_mode": "0644",
                "restarted_node": "b",
                "public_identity_unchanged": True,
                "mesh_address_unchanged": True,
                "daemon_pid_changed": restarted_b_status.get("pid") != initial_b_pid,
                "identity_values_retained": False,
            },
            "automatic_reconnect": {
                "configured": True,
                "retry_base_interval_secs": RETRY_BASE_INTERVAL_SECS,
                "retry_max_backoff_secs": RETRY_MAX_BACKOFF_SECS,
                "manual_reconnect_commands": 0,
                "reconnect_budget_secs": RECONNECT_BUDGET_SECS,
                "reconnect_elapsed_ms": reconnect_elapsed_ms,
                "authenticated_peers_per_node": 1,
                "links_per_node": 1,
                "estimated_mesh_size": 2,
            },
            "nodes_after_restart": restarted_nodes,
            "post_restart_mmp": post_restart_mmp,
            "post_restart_icmpv6": {
                "effective_mtu_boundary_payload_bytes": 1155,
                "echo_requests": 2,
                "passed": True,
            },
            "post_restart_payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0",
                "records": post_restart_payload,
                "all_exact_echo": True,
            },
            "post_restart_fsp_session_counts": post_restart_session_counts,
            "disconnect": {
                "control_acknowledged": True,
                "peers_per_node_after": 0,
                "links_per_node_after": 0,
                "fsp_sessions_per_node_after": 0,
            },
        }
    except Exception as exc:
        error = exc
        for stream in daemon_streams:
            if stream is not None:
                stream.flush()
        _print_redacted_log_tails(daemon_logs)
    finally:
        phase_at_failure = phase
        for process in payload_processes:
            _stop_process(process)
        cleanup["daemons_stopped"] = all(
            _stop_process(process) for process in daemon_processes
        )
        for stream in daemon_streams:
            if stream is not None:
                stream.close()
        for namespace in namespaces:
            _run(
                ["ip", "netns", "del", namespace],
                label=f"remove namespace {namespace}",
                timeout=10,
                check=False,
            )
        namespace_list = _run(
            ["ip", "netns", "list"], label="verify namespace cleanup", check=False
        ).stdout
        cleanup["namespaces_removed"] = all(
            namespace not in namespace_list for namespace in namespaces
        )
        shutil.rmtree(work, ignore_errors=True)
        cleanup["persistent_identity_directory_removed"] = not work.exists()

    if error is None and not all(cleanup.values()):
        error = QualificationError("qualification teardown did not complete")
        phase_at_failure = "teardown"

    finished_at = utc_now()
    if error is not None:
        result = _safe_failure_result(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            phase=phase_at_failure,
            project_revision=project_revision,
            cleanup=cleanup,
            error=error,
        )
        _write_result(output, result)
        raise QualificationError(
            f"G2 lifecycle qualification failed during {phase_at_failure}"
        ) from error

    result = {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-lifecycle",
        "run_id": run_id,
        "status": "passed",
        "classification": "experiment",
        "gate_ids": ["G2"],
        "started_at": started_at,
        "finished_at": finished_at,
        "provenance": provenance,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "topology": {
            "node_count": 2,
            "isolation": "linux-network-namespaces",
            "underlay": "direct-veth-ipv4-udp",
            "tun_name": "fips0",
            "configured_tun_mtu": TUN_MTU,
            "configured_udp_mtu": TUN_MTU,
            "identity_storage": "temporary-config-adjacent-key-files",
            "restarted_node": "b",
        },
        "observations": observations,
        "cleanup": cleanup,
        "limitations": [
            "One hard failure and restart of node B was exercised on a direct veth underlay.",
            "No alternate route, managed transit, NAT rebinding, public discovery, or signaling relay was exercised.",
            "Recovery timing is an observation from one GitHub-hosted runner and is not a production SLO.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
            "Private keys, public identities, mesh addresses, process identifiers, raw payloads, and daemon logs were not retained.",
            "This run qualifies Linux lifecycle behavior for the pinned host architecture only.",
        ],
    }
    _write_result(output, result)
    return result
