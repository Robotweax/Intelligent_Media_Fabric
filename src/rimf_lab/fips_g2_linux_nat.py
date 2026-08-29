from __future__ import annotations

import ipaddress
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .fips_g2_linux import (
    COMMIT_RE,
    EFFECTIVE_IPV6_MTU,
    FIPS_REPOSITORY,
    IDENTITY_RE,
    QualificationError,
    TUN_MTU,
    UDP_PAYLOAD_SIZES,
    UDP_PROBE_PORT,
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
    render_config,
    sha256_file,
    utc_now,
    valid_connect_acknowledgement,
)


NODE_A_ADDRESS = "10.204.0.1"
ROUTER_OUTSIDE_ADDRESS = "10.204.0.254"
NODE_B_ADDRESS = "10.205.0.2"
ROUTER_INSIDE_ADDRESS = "10.205.0.254"


def translated_peer_observed(peer_view: dict, expected_host: str) -> bool:
    peers = peer_view.get("peers")
    if not isinstance(peers, list) or len(peers) != 1:
        return False
    transport_address = peers[0].get("transport_addr")
    if not isinstance(transport_address, str):
        return False
    try:
        host, port = transport_address.rsplit(":", 1)
        return ipaddress.ip_address(host) == ipaddress.ip_address(expected_host) and 0 < int(port) < 65536
    except (ValueError, TypeError):
        return False


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
        "evidence_type": "fips-g2-linux-nat",
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


def run_fips_g2_linux_nat(
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
        raise QualificationError("the G2 NAT runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G2 NAT runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("git", "ip", "iptables", "ping", "sysctl"):
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

    suffix = str(os.getpid())
    namespaces = (f"rmg2na{suffix}", f"rmg2nb{suffix}", f"rmg2nr{suffix}")
    interfaces = (
        f"n2a{suffix}",
        f"n2ao{suffix}",
        f"n2b{suffix}",
        f"n2bi{suffix}",
    )
    if any(len(name) > 15 for name in (*namespaces, *interfaces)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")
    node_a_namespace, node_b_namespace, router_namespace = namespaces
    node_a_interface, router_outside_interface, node_b_interface, router_inside_interface = interfaces

    work = Path(tempfile.mkdtemp(prefix="rimf-g2-nat-", dir="/tmp"))
    node_dirs = (work / "node-a", work / "node-b")
    sockets = (node_dirs[0] / "control.sock", node_dirs[1] / "control.sock")
    configs = (node_dirs[0] / "fips.yaml", node_dirs[1] / "fips.yaml")
    daemon_logs = (node_dirs[0] / "daemon.log", node_dirs[1] / "daemon.log")
    daemon_processes: list[subprocess.Popen | None] = [None, None]
    daemon_streams = []
    payload_server: subprocess.Popen | None = None
    observations: dict = {}
    cleanup = {
        "daemons_stopped": False,
        "namespaces_removed": False,
        "ephemeral_identity_directory_removed": False,
    }
    error: Exception | None = None

    try:
        phase = "namespace-setup"
        for node_dir in node_dirs:
            node_dir.mkdir(mode=0o700)
        for config, socket_path, address in zip(
            configs, sockets, (NODE_A_ADDRESS, NODE_B_ADDRESS)
        ):
            config.write_text(render_config(socket_path, address), encoding="utf-8")
            config.chmod(0o600)

        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
            _run(
                ["ip", "-n", namespace, "link", "set", "lo", "up"],
                label=f"bring loopback up in {namespace}",
            )

        _run(
            [
                "ip",
                "link",
                "add",
                node_a_interface,
                "type",
                "veth",
                "peer",
                "name",
                router_outside_interface,
            ],
            label="create outside veth pair",
        )
        _run(
            [
                "ip",
                "link",
                "add",
                node_b_interface,
                "type",
                "veth",
                "peer",
                "name",
                router_inside_interface,
            ],
            label="create inside veth pair",
        )
        for interface, namespace in (
            (node_a_interface, node_a_namespace),
            (router_outside_interface, router_namespace),
            (node_b_interface, node_b_namespace),
            (router_inside_interface, router_namespace),
        ):
            _run(
                ["ip", "link", "set", interface, "netns", namespace],
                label=f"move {interface} into namespace",
            )
        for namespace, interface, address in (
            (node_a_namespace, node_a_interface, NODE_A_ADDRESS),
            (router_namespace, router_outside_interface, ROUTER_OUTSIDE_ADDRESS),
            (node_b_namespace, node_b_interface, NODE_B_ADDRESS),
            (router_namespace, router_inside_interface, ROUTER_INSIDE_ADDRESS),
        ):
            _run(
                ["ip", "-n", namespace, "addr", "add", f"{address}/24", "dev", interface],
                label=f"assign address to {interface}",
            )
            _run(
                ["ip", "-n", namespace, "link", "set", interface, "up"],
                label=f"bring {interface} up",
            )
        _run(
            [
                "ip",
                "-n",
                node_a_namespace,
                "route",
                "add",
                "10.205.0.0/24",
                "via",
                ROUTER_OUTSIDE_ADDRESS,
            ],
            label="install node A route to private segment",
        )
        _run(
            [
                "ip",
                "-n",
                node_b_namespace,
                "route",
                "add",
                "10.204.0.0/24",
                "via",
                ROUTER_INSIDE_ADDRESS,
            ],
            label="install node B route to outside segment",
        )

        phase = "stateful-nat-policy"
        router_exec = ["ip", "netns", "exec", router_namespace]
        _run(
            [*router_exec, "sysctl", "-q", "-w", "net.ipv4.ip_forward=1"],
            label="enable router IPv4 forwarding",
        )
        _run([*router_exec, "iptables", "-P", "FORWARD", "DROP"], label="default-deny forwarding")
        _run(
            [
                *router_exec,
                "iptables",
                "-A",
                "FORWARD",
                "-i",
                router_inside_interface,
                "-o",
                router_outside_interface,
                "-s",
                "10.205.0.0/24",
                "-d",
                "10.204.0.0/24",
                "-m",
                "conntrack",
                "--ctstate",
                "NEW,ESTABLISHED,RELATED",
                "-j",
                "ACCEPT",
            ],
            label="allow private-originated forwarding",
        )
        _run(
            [
                *router_exec,
                "iptables",
                "-A",
                "FORWARD",
                "-i",
                router_outside_interface,
                "-o",
                router_inside_interface,
                "-s",
                "10.204.0.0/24",
                "-d",
                "10.205.0.0/24",
                "-m",
                "conntrack",
                "--ctstate",
                "ESTABLISHED,RELATED",
                "-j",
                "ACCEPT",
            ],
            label="allow stateful return forwarding",
        )
        _run(
            [
                *router_exec,
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-o",
                router_outside_interface,
                "-s",
                "10.205.0.0/24",
                "-j",
                "SNAT",
                "--to-source",
                ROUTER_OUTSIDE_ADDRESS,
            ],
            label="install one-sided SNAT",
        )

        phase = "directional-underlay-proof"
        blocked = _run(
            [
                "ip",
                "netns",
                "exec",
                node_a_namespace,
                "ping",
                "-c",
                "1",
                "-W",
                "1",
                NODE_B_ADDRESS,
            ],
            label="outside-originated new-flow rejection probe",
            timeout=5,
            check=False,
        )
        if blocked.returncode == 0:
            raise QualificationError("node A unexpectedly opened a new flow to private node B")
        _run(
            [
                "ip",
                "netns",
                "exec",
                node_b_namespace,
                "ping",
                "-c",
                "2",
                "-W",
                "2",
                NODE_A_ADDRESS,
            ],
            label="private-originated underlay reachability probe",
            timeout=10,
        )

        phase = "daemon-start"
        for index, (namespace, config, daemon_log) in enumerate(
            zip((node_a_namespace, node_b_namespace), configs, daemon_logs)
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

        def status(index: int) -> dict:
            return _json_command(
                [str(fipsctl_binary), "-s", str(sockets[index]), "show", "status"],
                label=f"node {index} status",
            )

        statuses = [status(0), status(1)]
        node_observations = []
        for index, (namespace, node_status) in enumerate(
            zip((node_a_namespace, node_b_namespace), statuses)
        ):
            if node_status.get("tun_state") != "active" or node_status.get("tun_name") != "fips0":
                raise QualificationError(f"node {index} TUN did not become active")
            if node_status.get("effective_ipv6_mtu") != EFFECTIVE_IPV6_MTU:
                raise QualificationError(f"node {index} reported an unexpected effective IPv6 MTU")
            link_data = _json_value_command(
                ["ip", "-n", namespace, "-j", "link", "show", "dev", "fips0"],
                label=f"node {index} kernel TUN state",
            )
            if not isinstance(link_data, list) or len(link_data) != 1:
                raise QualificationError(f"node {index} kernel TUN state is invalid")
            kernel_mtu = link_data[0].get("mtu")
            if kernel_mtu != TUN_MTU:
                raise QualificationError(f"node {index} kernel TUN MTU is invalid")
            ipv6_address = str(ipaddress.IPv6Address(node_status.get("ipv6_addr", "")))
            if not ipv6_address.startswith("fd"):
                raise QualificationError(f"node {index} did not receive a FIPS ULA")
            node_observations.append(
                {
                    "node": "a" if index == 0 else "b",
                    "tun_state": "active",
                    "tun_name": "fips0",
                    "kernel_tun_mtu": kernel_mtu,
                    "effective_ipv6_mtu": node_status["effective_ipv6_mtu"],
                }
            )

        peer_a = statuses[0].get("npub")
        if not isinstance(peer_a, str) or not peer_a.startswith("npub1"):
            raise QualificationError("node A did not expose a valid public identity")

        phase = "private-initiated-connect-acknowledgement"
        connect_result = _json_command(
            [
                str(fipsctl_binary),
                "-s",
                str(sockets[1]),
                "connect",
                peer_a,
                f"{NODE_A_ADDRESS}:2121",
                "udp",
            ],
            label="connect private node B to node A",
        )
        if not valid_connect_acknowledgement(
            connect_result, peer_a, f"{NODE_A_ADDRESS}:2121"
        ):
            raise QualificationError("FIPS control returned an invalid connect acknowledgement")

        phase = "peer-link-convergence"

        def connected_statuses():
            current = [status(0), status(1)]
            if all(
                item.get("peer_count") == 1 and item.get("link_count") == 1
                for item in current
            ):
                return current
            return None

        statuses = _wait_for(
            connected_statuses, label="authenticated two-node NAT link", timeout=30
        )

        phase = "mesh-size-convergence"

        def converged_mesh_statuses():
            current = [status(0), status(1)]
            if mesh_size_converged(current):
                return current
            return None

        statuses = _wait_for(
            converged_mesh_statuses, label="estimated mesh size of two", timeout=30
        )

        phase = "mmp-and-translated-peer-observation"

        def measured_peer_views():
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
            if not all(
                isinstance(item, dict)
                and item.get("mode") == "full"
                and isinstance(item.get("srtt_ms"), (int, float))
                for item in measurements
            ):
                return None
            if not translated_peer_observed(current[0], ROUTER_OUTSIDE_ADDRESS):
                return None
            return current

        peer_views = _wait_for(
            measured_peer_views, label="full MMP and translated peer observations", timeout=30
        )
        mmp_observations = []
        for index, peer_view in enumerate(peer_views):
            peers = peer_view.get("peers")
            if not isinstance(peers, list) or len(peers) != 1:
                raise QualificationError(f"node {index} peer view is invalid")
            mmp = peers[0].get("mmp")
            if not isinstance(mmp, dict) or mmp.get("mode") != "full":
                raise QualificationError(f"node {index} MMP view is invalid")
            mmp_observations.append(
                {
                    "node": "a" if index == 0 else "b",
                    "mode": mmp["mode"],
                    "loss_rate": mmp.get("loss_rate"),
                    "etx": mmp.get("etx"),
                    "srtt_ms_observed": isinstance(mmp.get("srtt_ms"), (int, float)),
                }
            )

        phase = "icmpv6"
        destination = statuses[1]["ipv6_addr"]
        for size, label in ((32, "small"), (1155, "effective-MTU-boundary")):
            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    node_a_namespace,
                    "ping",
                    "-6",
                    "-c",
                    "2",
                    "-W",
                    "5",
                    "-s",
                    str(size),
                    destination,
                ],
                label=f"{label} ICMPv6 probe through fips0",
                timeout=20,
            )

        phase = "payload-identity"
        ready_path = work / "payload-server.ready"
        server_result_path = work / "payload-server.json"
        client_result_path = work / "payload-client.json"
        payload_server = subprocess.Popen(
            [
                "ip",
                "netns",
                "exec",
                node_b_namespace,
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

        def payload_server_ready():
            if payload_server is None or payload_server.poll() is not None:
                raise QualificationError("payload server exited before becoming ready")
            return ready_path.is_file()

        _wait_for(payload_server_ready, label="payload server", timeout=10)
        _run(
            [
                "ip",
                "netns",
                "exec",
                node_a_namespace,
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
            label="deterministic UDP identity probe",
            timeout=120,
        )
        try:
            payload_server.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise QualificationError("payload server did not finish") from exc
        if payload_server.returncode != 0:
            raise QualificationError("payload server failed")
        server_result = json.loads(server_result_path.read_text(encoding="utf-8"))
        client_result = json.loads(client_result_path.read_text(encoding="utf-8"))
        if server_result.get("records") != [
            {"bytes": item["bytes"], "sha256": item["sha256"]}
            for item in client_result.get("records", [])
        ]:
            raise QualificationError("payload sender and receiver digests disagree")
        payload_records = client_result.get("records")
        if (
            not isinstance(payload_records, list)
            or [item.get("bytes") for item in payload_records] != list(UDP_PAYLOAD_SIZES)
            or not all(item.get("exact_echo") is True for item in payload_records)
        ):
            raise QualificationError("payload identity result is incomplete")

        def sessions_observed():
            current = [status(0), status(1)]
            if all(item.get("session_count", 0) >= 1 for item in current):
                return current
            return None

        statuses = _wait_for(sessions_observed, label="FSP sessions", timeout=30)
        session_counts = [item["session_count"] for item in statuses]

        phase = "controlled-disconnect"
        disconnect_result = _json_command(
            [str(fipsctl_binary), "-s", str(sockets[1]), "disconnect", peer_a],
            label="disconnect private node B from node A",
        )
        if disconnect_result.get("disconnected") is not True:
            raise QualificationError("FIPS control did not acknowledge disconnect")

        def disconnected_statuses():
            current = [status(0), status(1)]
            if all(
                item.get("peer_count") == 0 and item.get("link_count") == 0
                for item in current
            ):
                return current
            return None

        _wait_for(disconnected_statuses, label="clean peer/link removal", timeout=30)
        observations = {
            "directional_reachability": {
                "node_a_to_node_b_new_flow_blocked": True,
                "node_b_to_node_a_new_flow_allowed": True,
                "stateful_return_path_only": True,
            },
            "nat": {
                "mode": "one-sided-snat",
                "private_initiator": "node-b",
                "public_node_observed_translated_source": True,
                "private_source_address_not_retained": True,
            },
            "nodes": node_observations,
            "connection": {
                "control_acknowledged": True,
                "authenticated_peers_per_node": 1,
                "links_per_node": 1,
                "estimated_mesh_size": 2,
                "transport": "udp",
            },
            "mmp": mmp_observations,
            "icmpv6": {
                "small_payload_bytes": 32,
                "effective_mtu_boundary_payload_bytes": 1155,
                "echo_requests_per_size": 2,
                "passed": True,
            },
            "payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0",
                "records": payload_records,
                "all_exact_echo": True,
            },
            "fsp_session_counts": session_counts,
            "disconnect": {
                "control_acknowledged": True,
                "peers_per_node_after": 0,
                "links_per_node_after": 0,
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
        raise QualificationError(f"G2 NAT qualification failed during {phase_at_failure}") from error

    result = {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-nat",
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
            "namespace_count": 3,
            "isolation": "linux-network-namespaces",
            "underlay": "routed-two-segment-ipv4-udp",
            "nat": "one-sided-snat",
            "tun_name": "fips0",
            "configured_tun_mtu": TUN_MTU,
            "configured_udp_mtu": TUN_MTU,
        },
        "observations": observations,
        "cleanup": cleanup,
        "limitations": [
            "One-sided static SNAT with a private-originated direct UDP flow only; STUN, hole punching, symmetric NAT, and relay-assisted connectivity were not exercised.",
            "No loss, delay, reordering, link failure, daemon restart, or route reconvergence was injected.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
            "This run qualifies Linux TUN connectivity for the pinned host architecture only.",
        ],
    }
    _write_result(output, result)
    return result
