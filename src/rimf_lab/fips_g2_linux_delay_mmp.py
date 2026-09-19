from __future__ import annotations

import ipaddress
import json
import os
import platform
import shutil
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
    valid_connect_acknowledgement,
)


HEARTBEAT_INTERVAL_SECS = 1
NETEM_ONE_WAY_DELAY_MS = 40
BASELINE_SRTT_MAX_MS = 25.0
DEGRADED_SRTT_MIN_MS = 55.0
DEGRADED_SRTT_MAX_MS = 200.0
RECOVERED_SRTT_MAX_MS = 25.0
MIN_SRTT_INCREASE_MS = 30.0
DEGRADED_CONVERGENCE_BUDGET_SECS = 60
RECOVERY_CONVERGENCE_BUDGET_SECS = 60
UDP_PAYLOAD_SIZES = (1, 1024, 1155)
UDP_PROBE_PORT = 42046


def render_delay_mmp_config(control_socket: Path, bind_address: str) -> str:
    return f'''node:
  identity:
    persistent: false
  control:
    enabled: true
    socket_path: "{control_socket}"
  tick_interval_secs: 1
  heartbeat_interval_secs: {HEARTBEAT_INTERVAL_SECS}
  link_dead_timeout_secs: 30
  mmp:
    mode: "full"
  session_mmp:
    mode: "full"
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
  name: "fips0"
  mtu: {TUN_MTU}

dns:
  enabled: false

transports:
  udp:
    bind_addr: "{bind_address}:2121"
    mtu: {TUN_MTU}

peers: []
'''


def delay_mmp_transition_within_contract(
    baseline: list[float],
    degraded: list[float],
    recovered: list[float],
    degraded_elapsed_ms: int,
    recovery_elapsed_ms: int,
) -> bool:
    values = (*baseline, *degraded, *recovered)
    if (
        len(baseline) != 2
        or len(degraded) != 2
        or len(recovered) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values)
    ):
        return False
    return (
        all(0 <= value <= BASELINE_SRTT_MAX_MS for value in baseline)
        and all(DEGRADED_SRTT_MIN_MS <= value <= DEGRADED_SRTT_MAX_MS for value in degraded)
        and all(after - before >= MIN_SRTT_INCREASE_MS for before, after in zip(baseline, degraded))
        and all(0 <= value <= RECOVERED_SRTT_MAX_MS for value in recovered)
        and 0 < degraded_elapsed_ms <= DEGRADED_CONVERGENCE_BUDGET_SECS * 1000
        and 0 < recovery_elapsed_ms <= RECOVERY_CONVERGENCE_BUDGET_SECS * 1000
    )


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
        "evidence_type": "fips-g2-linux-delay-mmp",
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


def run_fips_g2_linux_delay_mmp(
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
        raise QualificationError("the G2 delay/MMP runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G2 delay/MMP runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("git", "ip", "ping", "tc"):
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
    namespaces = (f"rimfg2da{suffix}", f"rimfg2db{suffix}")
    interfaces = (f"g2da{suffix}", f"g2db{suffix}")
    if any(len(name) > 15 for name in (*namespaces, *interfaces)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")

    work = Path(tempfile.mkdtemp(prefix="rimf-g2-delay-mmp-", dir="/tmp"))
    node_dirs = (work / "node-a", work / "node-b")
    sockets = (node_dirs[0] / "control.sock", node_dirs[1] / "control.sock")
    addresses = ("10.208.0.1", "10.208.0.2")
    configs = (node_dirs[0] / "fips.yaml", node_dirs[1] / "fips.yaml")
    daemon_logs = (node_dirs[0] / "daemon.log", node_dirs[1] / "daemon.log")
    daemon_processes: list[subprocess.Popen | None] = [None, None]
    daemon_streams = []
    payload_server: subprocess.Popen | None = None
    netem_installed = [False, False]
    observations: dict = {}
    cleanup = {
        "netem_removed": False,
        "daemons_stopped": False,
        "namespaces_removed": False,
        "ephemeral_identity_directory_removed": False,
    }
    error: Exception | None = None

    def control(index: int, *arguments: str) -> dict:
        return _json_command(
            [str(fipsctl_binary), "-s", str(sockets[index]), *arguments],
            label=f"node {('a', 'b')[index]} {' '.join(arguments)}",
        )

    def status(index: int) -> dict:
        return control(index, "show", "status")

    def mmp_srtte() -> list[float] | None:
        values: list[float] = []
        for index in range(2):
            view = control(index, "show", "peers")
            peers = view.get("peers")
            if not isinstance(peers, list) or len(peers) != 1:
                return None
            mmp = peers[0].get("mmp")
            if not isinstance(mmp, dict) or mmp.get("mode") != "full":
                return None
            srtt = mmp.get("srtt_ms")
            if isinstance(srtt, bool) or not isinstance(srtt, (int, float)):
                return None
            values.append(float(srtt))
        return values

    def session_starts(expected_npubs: tuple[str, str]) -> tuple[int, int] | None:
        starts: list[int] = []
        for index, expected_npub in enumerate(expected_npubs):
            view = control(index, "show", "sessions")
            sessions = view.get("sessions")
            if not isinstance(sessions, list) or len(sessions) != 1:
                return None
            session = sessions[0]
            if (
                not isinstance(session, dict)
                or session.get("npub") != expected_npub
                or session.get("state") != "established"
                or isinstance(session.get("session_start_ms"), bool)
                or not isinstance(session.get("session_start_ms"), int)
            ):
                return None
            starts.append(session["session_start_ms"])
        return starts[0], starts[1]

    def run_payload_probe(label: str, destination: str) -> list[dict]:
        nonlocal payload_server
        ready_path = work / f"payload-{label}.ready"
        server_result_path = work / f"payload-{label}-server.json"
        client_result_path = work / f"payload-{label}-client.json"
        payload_server = subprocess.Popen(
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

        def server_ready():
            if payload_server is None or payload_server.poll() is not None:
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
            payload_server.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise QualificationError(f"{label} payload server did not finish") from exc
        if payload_server.returncode != 0:
            raise QualificationError(f"{label} payload server failed")
        payload_server = None
        try:
            server_result = json.loads(server_result_path.read_text(encoding="utf-8"))
            client_result = json.loads(client_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualificationError(f"{label} payload results are invalid") from exc
        records = client_result.get("records")
        if (
            not isinstance(records, list)
            or [record.get("bytes") for record in records if isinstance(record, dict)]
            != list(UDP_PAYLOAD_SIZES)
            or not all(record.get("exact_echo") is True for record in records)
            or server_result.get("records")
            != [{"bytes": record["bytes"], "sha256": record["sha256"]} for record in records]
        ):
            raise QualificationError(f"{label} payload identity result is incomplete")
        return records

    def remove_netem() -> bool:
        for index, (namespace, interface) in enumerate(zip(namespaces, interfaces)):
            _run(
                ["ip", "netns", "exec", namespace, "tc", "qdisc", "del", "dev", interface, "root"],
                label=f"remove node {('a', 'b')[index]} netem",
                check=False,
            )
            netem_installed[index] = False
        for index, (namespace, interface) in enumerate(zip(namespaces, interfaces)):
            result = _run(
                ["ip", "netns", "exec", namespace, "tc", "qdisc", "show", "dev", interface],
                label=f"verify node {('a', 'b')[index]} netem removal",
                check=False,
            )
            if "netem" in result.stdout:
                return False
        return True

    try:
        phase = "namespace-setup"
        for node_dir in node_dirs:
            node_dir.mkdir(mode=0o700)
        for config, socket_path, address in zip(configs, sockets, addresses):
            config.write_text(render_delay_mmp_config(socket_path, address), encoding="utf-8")
            config.chmod(0o600)

        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
        _run(
            ["ip", "link", "add", interfaces[0], "type", "veth", "peer", "name", interfaces[1]],
            label="create delay-test underlay veth pair",
        )
        for namespace, interface, address in zip(namespaces, interfaces, addresses):
            _run(["ip", "link", "set", interface, "netns", namespace], label="move underlay interface")
            _run(["ip", "-n", namespace, "link", "set", "lo", "up"], label="bring loopback up")
            _run(
                ["ip", "-n", namespace, "addr", "add", f"{address}/30", "dev", interface],
                label="assign delay-test underlay address",
            )
            _run(
                ["ip", "-n", namespace, "link", "set", interface, "up"],
                label="bring delay-test underlay interface up",
            )

        phase = "daemon-start"
        for index, (namespace, config, daemon_log) in enumerate(
            zip(namespaces, configs, daemon_logs)
        ):
            stream = daemon_log.open("w", encoding="utf-8")
            daemon_streams.append(stream)
            daemon_processes[index] = subprocess.Popen(
                ["ip", "netns", "exec", namespace, str(fips_binary), "-c", str(config)],
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

        def controls_ready():
            if any(process is None or process.poll() is not None for process in daemon_processes):
                raise QualificationError("a FIPS daemon exited before its control socket was ready")
            return all(socket_path.is_socket() for socket_path in sockets)

        _wait_for(controls_ready, label="FIPS control sockets", timeout=30)
        statuses = [status(0), status(1)]
        nodes = []
        identities: list[str] = []
        for index, (namespace, node_status) in enumerate(zip(namespaces, statuses)):
            if (
                node_status.get("tun_state") != "active"
                or node_status.get("tun_name") != "fips0"
                or node_status.get("effective_ipv6_mtu") != EFFECTIVE_IPV6_MTU
            ):
                raise QualificationError(f"node {index} runtime state is invalid")
            link_data = _json_value_command(
                ["ip", "-n", namespace, "-j", "link", "show", "dev", "fips0"],
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
            npub = node_status.get("npub")
            if not isinstance(npub, str) or not npub.startswith("npub1"):
                raise QualificationError(f"node {index} public identity is invalid")
            identities.append(npub)
            nodes.append(
                {
                    "node": ("a", "b")[index],
                    "tun_state": "active",
                    "tun_name": "fips0",
                    "kernel_tun_mtu": TUN_MTU,
                    "effective_ipv6_mtu": EFFECTIVE_IPV6_MTU,
                }
            )

        phase = "connect-acknowledgement"
        connect_result = control(0, "connect", identities[1], f"{addresses[1]}:2121", "udp")
        if not valid_connect_acknowledgement(
            connect_result, identities[1], f"{addresses[1]}:2121"
        ):
            raise QualificationError("FIPS control returned an invalid connect acknowledgement")

        def connected_statuses():
            current = [status(0), status(1)]
            if all(
                item.get("peer_count") == 1 and item.get("link_count") == 1
                for item in current
            ) and mesh_size_converged(current):
                return current
            return None

        statuses = _wait_for(
            connected_statuses, label="authenticated two-node link and mesh", timeout=30
        )
        destination = statuses[1]["ipv6_addr"]

        phase = "baseline-route-and-session"
        _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                "ping",
                "-6",
                "-c",
                "4",
                "-i",
                "0.2",
                "-W",
                "3",
                "-s",
                "32",
                destination,
            ],
            label="baseline overlay probe",
            timeout=20,
        )
        expected_session_npubs = (identities[1], identities[0])
        initial_session_starts = _wait_for(
            lambda: session_starts(expected_session_npubs),
            label="baseline FSP sessions",
            timeout=30,
        )

        phase = "baseline-mmp"
        baseline_srtte = _wait_for(
            lambda: (
                values
                if (values := mmp_srtte()) is not None
                and all(0 <= value <= BASELINE_SRTT_MAX_MS for value in values)
                else None
            ),
            label="bounded baseline MMP SRTT",
            timeout=30,
        )

        phase = "delay-injection"
        for index, (namespace, interface) in enumerate(zip(namespaces, interfaces)):
            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    namespace,
                    "tc",
                    "qdisc",
                    "replace",
                    "dev",
                    interface,
                    "root",
                    "netem",
                    "delay",
                    f"{NETEM_ONE_WAY_DELAY_MS}ms",
                ],
                label=f"inject node {('a', 'b')[index]} fixed delay",
            )
            netem_installed[index] = True
        verified_netem = 0
        for index, (namespace, interface) in enumerate(zip(namespaces, interfaces)):
            qdiscs = _json_value_command(
                ["ip", "netns", "exec", namespace, "tc", "-j", "qdisc", "show", "dev", interface],
                label=f"verify node {('a', 'b')[index]} netem",
            )
            if not isinstance(qdiscs, list) or not any(
                isinstance(qdisc, dict) and qdisc.get("kind") == "netem" for qdisc in qdiscs
            ):
                raise QualificationError("netem delay was not visible on both underlay directions")
            verified_netem += 1

        phase = "degraded-mmp-convergence"
        degraded_started = time.monotonic()
        _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                "ping",
                "-6",
                "-c",
                "12",
                "-i",
                "0.25",
                "-W",
                "3",
                "-s",
                "32",
                destination,
            ],
            label="delay-stimulus overlay probes",
            timeout=30,
        )
        degraded_srtte = _wait_for(
            lambda: (
                values
                if (values := mmp_srtte()) is not None
                and all(
                    DEGRADED_SRTT_MIN_MS <= value <= DEGRADED_SRTT_MAX_MS
                    for value in values
                )
                and all(
                    after - before >= MIN_SRTT_INCREASE_MS
                    for before, after in zip(baseline_srtte, values)
                )
                else None
            ),
            label="degraded MMP SRTT",
            timeout=DEGRADED_CONVERGENCE_BUDGET_SECS,
            interval=1,
        )
        degraded_elapsed_ms = max(1, int((time.monotonic() - degraded_started) * 1000))

        phase = "impaired-delivery"
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
                "3",
                "-s",
                "1155",
                destination,
            ],
            label="delayed effective-MTU-boundary ICMPv6 probe",
            timeout=20,
        )
        impaired_payload_records = run_payload_probe("impaired", destination)
        impaired_session_starts = session_starts(expected_session_npubs)
        if impaired_session_starts != initial_session_starts:
            raise QualificationError("endpoint FSP session changed during fixed delay")
        impaired_statuses = [status(0), status(1)]
        if not all(
            item.get("peer_count") == 1
            and item.get("link_count") == 1
            and item.get("session_count") == 1
            for item in impaired_statuses
        ):
            raise QualificationError("peer, link, or session continuity failed during fixed delay")

        phase = "delay-removal"
        if not remove_netem():
            raise QualificationError("netem delay did not clear from both underlay directions")
        cleanup["netem_removed"] = True

        phase = "recovery-mmp-convergence"
        recovery_started = time.monotonic()
        _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                "ping",
                "-6",
                "-c",
                "20",
                "-i",
                "0.1",
                "-W",
                "2",
                "-s",
                "32",
                destination,
            ],
            label="post-delay recovery stimulus",
            timeout=30,
        )
        recovered_srtte = _wait_for(
            lambda: (
                values
                if (values := mmp_srtte()) is not None
                and all(0 <= value <= RECOVERED_SRTT_MAX_MS for value in values)
                else None
            ),
            label="recovered MMP SRTT",
            timeout=RECOVERY_CONVERGENCE_BUDGET_SECS,
            interval=1,
        )
        recovery_elapsed_ms = max(1, int((time.monotonic() - recovery_started) * 1000))
        recovered_session_starts = session_starts(expected_session_npubs)
        if recovered_session_starts != initial_session_starts:
            raise QualificationError("endpoint FSP session changed during delay recovery")
        if not delay_mmp_transition_within_contract(
            baseline_srtte,
            degraded_srtte,
            recovered_srtte,
            degraded_elapsed_ms,
            recovery_elapsed_ms,
        ):
            raise QualificationError("MMP SRTT transition did not satisfy the frozen contract")

        phase = "controlled-disconnect"
        disconnect_result = control(0, "disconnect", identities[1])
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

        _wait_for(disconnected_statuses, label="clean peer/link/session removal", timeout=30)
        observations = {
            "nodes": nodes,
            "connection": {
                "control_acknowledged": True,
                "authenticated_peers_per_node": 1,
                "links_per_node": 1,
                "estimated_mesh_size": 2,
                "transport": "udp",
            },
            "baseline_mmp": {
                "mode": "full",
                "srtt_ms_per_node": baseline_srtte,
                "maximum_srtt_ms": BASELINE_SRTT_MAX_MS,
            },
            "delay_injection": {
                "mechanism": "linux-tc-netem",
                "configured_one_way_delay_ms": NETEM_ONE_WAY_DELAY_MS,
                "configured_loss_percent": 0,
                "impaired_underlay_directions": 2,
                "verified_netem_qdiscs": verified_netem,
            },
            "degraded_mmp": {
                "srtt_ms_per_node": degraded_srtte,
                "minimum_srtt_ms": DEGRADED_SRTT_MIN_MS,
                "maximum_srtt_ms": DEGRADED_SRTT_MAX_MS,
                "minimum_increase_ms": MIN_SRTT_INCREASE_MS,
                "convergence_budget_secs": DEGRADED_CONVERGENCE_BUDGET_SECS,
                "convergence_elapsed_ms": degraded_elapsed_ms,
            },
            "session_continuity": {
                "session_start_unchanged_during_delay": [True, True],
                "session_start_unchanged_after_recovery": [True, True],
                "peer_counts_during_delay": [1, 1],
                "link_counts_during_delay": [1, 1],
                "fsp_session_counts_during_delay": [1, 1],
            },
            "impaired_icmpv6": {
                "effective_mtu_boundary_payload_bytes": 1155,
                "echo_requests": 2,
                "passed": True,
            },
            "impaired_payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0",
                "records": impaired_payload_records,
                "all_exact_echo": True,
            },
            "recovery_mmp": {
                "netem_removed_per_direction": [True, True],
                "srtt_ms_per_node": recovered_srtte,
                "maximum_srtt_ms": RECOVERED_SRTT_MAX_MS,
                "convergence_budget_secs": RECOVERY_CONVERGENCE_BUDGET_SECS,
                "convergence_elapsed_ms": recovery_elapsed_ms,
            },
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
            stream.flush()
        _print_redacted_log_tails(daemon_logs)
    finally:
        phase_at_failure = phase
        _stop_process(payload_server)
        if any(netem_installed):
            cleanup["netem_removed"] = remove_netem()
        cleanup["daemons_stopped"] = all(_stop_process(process) for process in daemon_processes)
        for stream in daemon_streams:
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
        cleanup["ephemeral_identity_directory_removed"] = not work.exists()

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
            f"G2 delay/MMP qualification failed during {phase_at_failure}"
        ) from error

    result = {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-delay-mmp",
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
            "namespace_count": 2,
            "isolation": "linux-network-namespaces",
            "underlay": "direct-veth-ipv4-udp",
            "tun_name": "fips0",
            "configured_tun_mtu": TUN_MTU,
            "configured_udp_mtu": TUN_MTU,
            "heartbeat_interval_secs": HEARTBEAT_INTERVAL_SECS,
        },
        "observations": observations,
        "cleanup": cleanup,
        "limitations": [
            "One direct veth underlay and one fixed-delay step were exercised.",
            "No loss, jitter, reordering, duplication, corruption, bandwidth limit, or queue pressure was injected.",
            "The SRTT bounds are qualification controls for this CI runner class, not production SLOs.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
            "No route change, NAT, discovery service, or FIPS process restart was exercised.",
        ],
    }
    _write_result(output, result)
    return result
