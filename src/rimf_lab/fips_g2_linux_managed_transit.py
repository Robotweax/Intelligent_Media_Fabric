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
    render_config,
    sha256_file,
    utc_now,
    valid_connect_acknowledgement,
)


NODE_A_ADDRESS = "10.206.0.1"
TRANSIT_LEFT_ADDRESS = "10.206.0.2"
TRANSIT_RIGHT_ADDRESS = "10.207.0.1"
NODE_B_ADDRESS = "10.207.0.2"


def line_peer_relationships(peer_views: list[dict], identities: list[str]) -> bool:
    if len(peer_views) != 3 or len(identities) != 3:
        return False
    observed: list[set[str]] = []
    for view in peer_views:
        peers = view.get("peers")
        if not isinstance(peers, list):
            return False
        npubs = {item.get("npub") for item in peers if isinstance(item, dict)}
        if any(not isinstance(item, str) for item in npubs):
            return False
        observed.append(npubs)
    node_a, transit, node_b = identities
    return observed == [{transit}, {node_a, node_b}, {transit}]


def forwarding_counters(value: dict) -> tuple[int, int]:
    forwarding = value.get("forwarding")
    if not isinstance(forwarding, dict):
        raise QualificationError("routing view did not contain forwarding counters")
    packets = forwarding.get("forwarded_packets")
    byte_count = forwarding.get("forwarded_bytes")
    if (
        not isinstance(packets, int)
        or isinstance(packets, bool)
        or not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
    ):
        raise QualificationError("routing view contained invalid forwarding counters")
    return packets, byte_count


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
        "evidence_type": "fips-g2-linux-managed-transit",
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


def run_fips_g2_linux_managed_transit(
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
        raise QualificationError("the G2 managed-transit runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G2 managed-transit runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("git", "ip", "ping", "sysctl"):
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
    namespaces = (f"rmg2ta{suffix}", f"rmg2tr{suffix}", f"rmg2tb{suffix}")
    interfaces = (
        f"t2a{suffix}",
        f"t2rl{suffix}",
        f"t2rr{suffix}",
        f"t2b{suffix}",
    )
    if any(len(name) > 15 for name in (*namespaces, *interfaces)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")
    node_a_namespace, transit_namespace, node_b_namespace = namespaces
    node_a_interface, transit_left_interface, transit_right_interface, node_b_interface = interfaces

    work = Path(tempfile.mkdtemp(prefix="rimf-g2-transit-", dir="/tmp"))
    node_dirs = (work / "node-a", work / "transit-r", work / "node-b")
    sockets = tuple(node_dir / "control.sock" for node_dir in node_dirs)
    configs = tuple(node_dir / "fips.yaml" for node_dir in node_dirs)
    daemon_logs = tuple(node_dir / "daemon.log" for node_dir in node_dirs)
    daemon_processes: list[subprocess.Popen | None] = [None, None, None]
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
        bind_addresses = (NODE_A_ADDRESS, "0.0.0.0", NODE_B_ADDRESS)
        for config, socket_path, address in zip(configs, sockets, bind_addresses):
            config.write_text(render_config(socket_path, address), encoding="utf-8")
            config.chmod(0o600)

        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
            _run(
                ["ip", "-n", namespace, "link", "set", "lo", "up"],
                label=f"bring loopback up in {namespace}",
            )

        for left, right, label in (
            (node_a_interface, transit_left_interface, "left"),
            (transit_right_interface, node_b_interface, "right"),
        ):
            _run(
                ["ip", "link", "add", left, "type", "veth", "peer", "name", right],
                label=f"create {label} veth pair",
            )
        for interface, namespace in (
            (node_a_interface, node_a_namespace),
            (transit_left_interface, transit_namespace),
            (transit_right_interface, transit_namespace),
            (node_b_interface, node_b_namespace),
        ):
            _run(
                ["ip", "link", "set", interface, "netns", namespace],
                label=f"move {interface} into namespace",
            )
        for namespace, interface, address in (
            (node_a_namespace, node_a_interface, NODE_A_ADDRESS),
            (transit_namespace, transit_left_interface, TRANSIT_LEFT_ADDRESS),
            (transit_namespace, transit_right_interface, TRANSIT_RIGHT_ADDRESS),
            (node_b_namespace, node_b_interface, NODE_B_ADDRESS),
        ):
            _run(
                ["ip", "-n", namespace, "addr", "add", f"{address}/30", "dev", interface],
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
                "10.207.0.0/30",
                "via",
                TRANSIT_LEFT_ADDRESS,
            ],
            label="install node A route toward node B segment",
        )
        _run(
            [
                "ip",
                "-n",
                node_b_namespace,
                "route",
                "add",
                "10.206.0.0/30",
                "via",
                TRANSIT_RIGHT_ADDRESS,
            ],
            label="install node B route toward node A segment",
        )
        _run(
            [
                "ip",
                "netns",
                "exec",
                transit_namespace,
                "sysctl",
                "-q",
                "-w",
                "net.ipv4.ip_forward=0",
            ],
            label="disable underlay forwarding on transit node",
        )

        phase = "direct-underlay-exclusion"
        direct_probe = _run(
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
            label="endpoint direct-underlay exclusion probe",
            timeout=5,
            check=False,
        )
        if direct_probe.returncode == 0:
            raise QualificationError("node A unexpectedly reached node B over the IPv4 underlay")

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

        def control(index: int, *arguments: str) -> dict:
            return _json_command(
                [str(fipsctl_binary), "-s", str(sockets[index]), *arguments],
                label=f"node {index} {' '.join(arguments)}",
            )

        def status(index: int) -> dict:
            return control(index, "show", "status")

        statuses = [status(index) for index in range(3)]
        identities = [item.get("npub") for item in statuses]
        if any(not isinstance(item, str) or not item.startswith("npub1") for item in identities):
            raise QualificationError("a node did not expose a valid public identity")

        node_observations = []
        for index, (namespace, node_status) in enumerate(zip(namespaces, statuses)):
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
                    "node": ("a", "r", "b")[index],
                    "role": "managed-transit" if index == 1 else "endpoint",
                    "tun_state": "active",
                    "tun_name": "fips0",
                    "kernel_tun_mtu": kernel_mtu,
                    "effective_ipv6_mtu": node_status["effective_ipv6_mtu"],
                }
            )

        phase = "line-link-connect"
        connect_a = control(
            0,
            "connect",
            identities[1],
            f"{TRANSIT_LEFT_ADDRESS}:2121",
            "udp",
        )
        if not valid_connect_acknowledgement(
            connect_a, identities[1], f"{TRANSIT_LEFT_ADDRESS}:2121"
        ):
            raise QualificationError("node A connect acknowledgement was invalid")
        connect_b = control(
            2,
            "connect",
            identities[1],
            f"{TRANSIT_RIGHT_ADDRESS}:2121",
            "udp",
        )
        if not valid_connect_acknowledgement(
            connect_b, identities[1], f"{TRANSIT_RIGHT_ADDRESS}:2121"
        ):
            raise QualificationError("node B connect acknowledgement was invalid")

        phase = "line-topology-convergence"

        def converged_line():
            current_statuses = [status(index) for index in range(3)]
            expected_counts = (1, 2, 1)
            if not all(
                item.get("peer_count") == count and item.get("link_count") == count
                for item, count in zip(current_statuses, expected_counts)
            ):
                return None
            if not all(item.get("estimated_mesh_size") == 3 for item in current_statuses):
                return None
            peer_views = [control(index, "show", "peers") for index in range(3)]
            if not line_peer_relationships(peer_views, identities):
                return None
            return current_statuses, peer_views

        statuses, peer_views = _wait_for(
            converged_line, label="three-node authenticated line topology", timeout=45
        )

        phase = "mmp-observation"

        def full_mmp_views():
            current = [control(index, "show", "peers") for index in range(3)]
            if not line_peer_relationships(current, identities):
                return None
            peers = [peer for view in current for peer in view.get("peers", [])]
            if len(peers) != 4:
                return None
            if not all(
                peer.get("transport_type") == "udp"
                and isinstance(peer.get("mmp"), dict)
                and peer["mmp"].get("mode") == "full"
                and isinstance(peer["mmp"].get("srtt_ms"), (int, float))
                for peer in peers
            ):
                return None
            return current

        peer_views = _wait_for(full_mmp_views, label="full MMP on all four link views", timeout=30)
        mmp_observations = []
        for index, view in enumerate(peer_views):
            for peer_index, peer in enumerate(view["peers"]):
                mmp = peer["mmp"]
                mmp_observations.append(
                    {
                        "node": ("a", "r", "b")[index],
                        "link_ordinal": peer_index + 1,
                        "mode": "full",
                        "loss_rate": mmp.get("loss_rate"),
                        "etx": mmp.get("etx"),
                        "srtt_ms_observed": True,
                    }
                )

        phase = "multihop-icmpv6"
        destination = statuses[2]["ipv6_addr"]

        def multihop_route_ready():
            result = _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    node_a_namespace,
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
                label="multihop route-discovery probe",
                timeout=5,
                check=False,
            )
            return result.returncode == 0

        _wait_for(
            multihop_route_ready,
            label="FIPS multihop route discovery and first ICMPv6 reply",
            timeout=45,
            interval=1,
        )
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
                "10",
                "-s",
                "1155",
                destination,
            ],
            label="effective-MTU-boundary multihop ICMPv6 probe",
            timeout=30,
        )

        phase = "multihop-payload-identity"
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
            label="deterministic multihop UDP identity probe",
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

        phase = "transit-forwarding-observation"

        def forwarding_observed():
            current_statuses = [status(index) for index in range(3)]
            if (
                current_statuses[0].get("session_count", 0) < 1
                or current_statuses[2].get("session_count", 0) < 1
                or current_statuses[1].get("session_count") != 0
            ):
                return None
            routing = control(1, "show", "routing")
            packets, byte_count = forwarding_counters(routing)
            if packets < 1 or byte_count < 1:
                return None
            return current_statuses, packets, byte_count

        statuses, relay_forwarded_packets, relay_forwarded_bytes = _wait_for(
            forwarding_observed, label="managed transit forwarding counters", timeout=30
        )

        phase = "controlled-disconnect"
        disconnect_a = control(0, "disconnect", identities[1])
        disconnect_b = control(2, "disconnect", identities[1])
        if (
            disconnect_a.get("disconnected") is not True
            or disconnect_b.get("disconnected") is not True
        ):
            raise QualificationError("FIPS control did not acknowledge both disconnects")

        def disconnected_statuses():
            current = [status(index) for index in range(3)]
            if all(
                item.get("peer_count") == 0 and item.get("link_count") == 0
                for item in current
            ):
                return current
            return None

        _wait_for(disconnected_statuses, label="clean three-node peer/link removal", timeout=30)
        observations = {
            "underlay_exclusion": {
                "endpoint_direct_ipv4_forwarding_disabled": True,
                "endpoint_direct_ipv4_probe_blocked": True,
            },
            "line_topology": {
                "control_connects_acknowledged": 2,
                "authenticated_peer_counts": [1, 2, 1],
                "authenticated_link_counts": [1, 2, 1],
                "estimated_mesh_size": 3,
                "endpoint_direct_peer_absent": True,
                "transport": "udp",
            },
            "nodes": node_observations,
            "mmp": mmp_observations,
            "icmpv6": {
                "path": "endpoint-a-via-managed-transit-r-to-endpoint-b",
                "small_payload_bytes": 32,
                "effective_mtu_boundary_payload_bytes": 1155,
                "passed": True,
            },
            "payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0-multihop",
                "records": payload_records,
                "all_exact_echo": True,
            },
            "transit_forwarding": {
                "forwarded_packets": relay_forwarded_packets,
                "forwarded_bytes": relay_forwarded_bytes,
                "endpoint_fsp_session_counts": [statuses[0]["session_count"], statuses[2]["session_count"]],
                "transit_fsp_session_count": statuses[1]["session_count"],
                "payload_opaque_to_transit_by_protocol_contract": True,
            },
            "disconnect": {
                "control_acknowledgements": 2,
                "peers_per_node_after": [0, 0, 0],
                "links_per_node_after": [0, 0, 0],
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
        raise QualificationError(
            f"G2 managed-transit qualification failed during {phase_at_failure}"
        ) from error

    result = {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-managed-transit",
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
            "node_count": 3,
            "namespace_count": 3,
            "authenticated_link_count": 2,
            "isolation": "linux-network-namespaces",
            "underlay": "two-segment-line-ipv4-udp",
            "path_role": "managed-fips-transit",
            "public_discovery": False,
            "nostr_relay": False,
            "tun_name": "fips0",
            "configured_tun_mtu": TUN_MTU,
            "configured_udp_mtu": TUN_MTU,
        },
        "observations": observations,
        "cleanup": cleanup,
        "limitations": [
            "A static, explicitly connected three-node FIPS line was exercised; Nostr discovery, a Nostr signaling relay, and NAT traversal were not part of this run.",
            "The managed transit node was not impaired, restarted, removed, or compared with an alternate route.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
            "Payload opacity at the transit node follows the pinned FIPS protocol contract; this runner did not capture or cryptographically inspect transit packets.",
            "This run qualifies Linux TUN transit connectivity for the pinned host architecture only.",
        ],
    }
    _write_result(output, result)
    return result
