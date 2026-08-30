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
TRANSIT_UDP_MTU = 1000
PATH_EFFECTIVE_IPV6_MTU = 923
PATH_BOUNDARY_ICMP_PAYLOAD = 875
PATH_ABOVE_BOUNDARY_ICMP_PAYLOAD = 876
PATH_ABOVE_BOUNDARY_IPV6_BYTES = 924
PATH_UDP_PAYLOAD_SIZES = (1, 512, 875)
REACTIVE_TICK_INTERVAL_SECS = 10
REACTIVE_CONVERGENCE_BUDGET_SECS = 20
TRANSPORT_TRANSITION_BUDGET_SECS = 45
TCP_PORT = 3121
CROSS_CONNECTION_WON_LOG_MARKER = "Cross-connection resolved: this connection won"


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


def mtu_drop_counters(value: dict) -> tuple[int, int]:
    forwarding = value.get("forwarding")
    if not isinstance(forwarding, dict):
        raise QualificationError("routing view did not contain forwarding counters")
    packets = forwarding.get("drop_mtu_exceeded_packets")
    byte_count = forwarding.get("drop_mtu_exceeded_bytes")
    if (
        not isinstance(packets, int)
        or isinstance(packets, bool)
        or packets < 0
        or not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 0
    ):
        raise QualificationError("routing view contained invalid MTU-drop counters")
    return packets, byte_count


def mtu_error_counters(value: dict) -> tuple[int, int, int]:
    errors = value.get("error_signals")
    if not isinstance(errors, dict):
        raise QualificationError("routing view did not contain error-signal counters")
    values = tuple(
        errors.get(field)
        for field in (
            "mtu_exceeded",
            "mtu_exceeded_below_floor",
            "mtu_exceeded_uncorroborated",
        )
    )
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item < 0
        for item in values
    ):
        raise QualificationError("routing view contained invalid MTU-error counters")
    return values


def endpoint_session_record(value: dict, remote_identity: str) -> dict | None:
    sessions = value.get("sessions")
    if not isinstance(sessions, list):
        return None
    matches = [
        session
        for session in sessions
        if isinstance(session, dict)
        and session.get("npub") == remote_identity
        and session.get("state") == "established"
        and isinstance(session.get("session_start_ms"), int)
    ]
    return matches[0] if len(matches) == 1 else None


def active_peer_record(value: dict, remote_identity: str) -> dict | None:
    peers = value.get("peers")
    if not isinstance(peers, list):
        return None
    matches = [
        peer
        for peer in peers
        if isinstance(peer, dict) and peer.get("npub") == remote_identity
    ]
    return matches[0] if len(matches) == 1 else None


def session_path_mtu(value: dict, remote_identity: str) -> int | None:
    sessions = value.get("sessions")
    if not isinstance(sessions, list):
        return None
    for session in sessions:
        if not isinstance(session, dict) or session.get("npub") != remote_identity:
            continue
        mmp = session.get("mmp")
        if session.get("state") != "established" or not isinstance(mmp, dict):
            return None
        path_mtu = mmp.get("path_mtu")
        if isinstance(path_mtu, int) and not isinstance(path_mtu, bool):
            return path_mtu
    return None


def coordinate_cache_path_mtu(value: dict, remote_ipv6: str) -> int | None:
    entries = value.get("entries")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("ipv6_addr") != remote_ipv6:
            continue
        path_mtu = entry.get("path_mtu")
        if isinstance(path_mtu, int) and not isinstance(path_mtu, bool):
            return path_mtu
    return None


def _safe_failure_result(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    phase: str,
    project_revision: str,
    cleanup: dict,
    error: Exception,
    evidence_type: str = "fips-g2-linux-managed-transit",
) -> dict:
    return {
        "schema_version": 1,
        "evidence_type": evidence_type,
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
    _heterogeneous_mtu: bool = False,
    _reactive_mtu: bool = False,
) -> dict:
    if _heterogeneous_mtu and _reactive_mtu:
        raise ValueError("heterogeneous and reactive MTU modes are mutually exclusive")
    evidence_type = (
        "fips-g2-linux-reactive-mtu"
        if _reactive_mtu
        else (
            "fips-g2-linux-multihop-mtu"
            if _heterogeneous_mtu
            else "fips-g2-linux-managed-transit"
        )
    )
    path_mtu_mode = _heterogeneous_mtu or _reactive_mtu
    udp_mtus = (
        (TUN_MTU, TRANSIT_UDP_MTU, TUN_MTU)
        if _heterogeneous_mtu
        else (TUN_MTU,) * 3
    )
    effective_ipv6_mtus = (
        (EFFECTIVE_IPV6_MTU, PATH_EFFECTIVE_IPV6_MTU, PATH_EFFECTIVE_IPV6_MTU)
        if _reactive_mtu
        else (
            (EFFECTIVE_IPV6_MTU, PATH_EFFECTIVE_IPV6_MTU, EFFECTIVE_IPV6_MTU)
            if _heterogeneous_mtu
            else (EFFECTIVE_IPV6_MTU,) * 3
        )
    )
    boundary_icmp_payload = PATH_BOUNDARY_ICMP_PAYLOAD if path_mtu_mode else 1155
    payload_sizes = PATH_UDP_PAYLOAD_SIZES if path_mtu_mode else UDP_PAYLOAD_SIZES
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    phase = "preflight"
    if platform.system() != "Linux":
        raise QualificationError("the G2 managed-transit runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G2 managed-transit runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("dig", "git", "ip", "ping", "sysctl", "tc"):
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
    ptb_probe: subprocess.Popen | None = None
    path_mtu_observation: dict | None = None
    initial_path_mtu_observation: dict | None = None
    transport_transition_observation: dict | None = None
    reactive_mtu_observation: dict | None = None
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
        for index, (config, socket_path, address, udp_mtu) in enumerate(
            zip(configs, sockets, bind_addresses, udp_mtus)
        ):
            config.write_text(
                render_config(
                    socket_path,
                    address,
                    dns_enabled=True,
                    udp_mtu=udp_mtu,
                    persistent_identity=_reactive_mtu,
                    tick_interval_secs=(
                        REACTIVE_TICK_INTERVAL_SECS if _reactive_mtu else None
                    ),
                    log_level="debug" if _reactive_mtu else "warn",
                    tcp_mtu=(
                        TRANSIT_UDP_MTU if _reactive_mtu and index in (1, 2) else None
                    ),
                    tcp_bind_port=TCP_PORT,
                ),
                encoding="utf-8",
            )
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
        for index, (namespace, node_status, expected_effective_mtu) in enumerate(
            zip(namespaces, statuses, effective_ipv6_mtus)
        ):
            if node_status.get("tun_state") != "active" or node_status.get("tun_name") != "fips0":
                raise QualificationError(f"node {index} TUN did not become active")
            if node_status.get("effective_ipv6_mtu") != expected_effective_mtu:
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
        transition_initiator_index: int | None = None
        transition_target_identity: str | None = None
        transition_target_address: str | None = None
        transition_namespace: str | None = None
        transition_interface: str | None = None
        if _reactive_mtu:
            transit_node_addr = statuses[1].get("node_addr")
            endpoint_b_node_addr = statuses[2].get("node_addr")
            if not isinstance(transit_node_addr, str) or not isinstance(
                endpoint_b_node_addr, str
            ):
                raise QualificationError("node addresses were unavailable for link arbitration")
            if transit_node_addr < endpoint_b_node_addr:
                transition_initiator_index = 1
                transition_target_identity = identities[2]
                transition_target_address = f"{NODE_B_ADDRESS}:{TCP_PORT}"
                transition_namespace = transit_namespace
                transition_interface = transit_right_interface
            else:
                transition_initiator_index = 2
                transition_target_identity = identities[1]
                transition_target_address = f"{TRANSIT_RIGHT_ADDRESS}:{TCP_PORT}"
                transition_namespace = node_b_namespace
                transition_interface = node_b_interface

            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    transition_namespace,
                    "tc",
                    "qdisc",
                    "add",
                    "dev",
                    transition_interface,
                    "root",
                    "handle",
                    "1:",
                    "prio",
                ],
                label="install transition-path priority qdisc",
            )
            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    transition_namespace,
                    "tc",
                    "qdisc",
                    "add",
                    "dev",
                    transition_interface,
                    "parent",
                    "1:3",
                    "handle",
                    "30:",
                    "netem",
                    "loss",
                    "100%",
                ],
                label="hold transition TCP candidate",
            )
            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    transition_namespace,
                    "tc",
                    "filter",
                    "add",
                    "dev",
                    transition_interface,
                    "protocol",
                    "ip",
                    "parent",
                    "1:0",
                    "prio",
                    "3",
                    "u32",
                    "match",
                    "ip",
                    "protocol",
                    "6",
                    "0xff",
                    "match",
                    "ip",
                    "dport",
                    str(TCP_PORT),
                    "0xffff",
                    "flowid",
                    "1:3",
                ],
                label="select only transition TCP candidate",
            )
            transition_ack = control(
                transition_initiator_index,
                "connect",
                transition_target_identity,
                transition_target_address,
                "tcp",
            )
            if not valid_connect_acknowledgement(
                transition_ack,
                transition_target_identity,
                transition_target_address,
                "tcp",
            ):
                raise QualificationError("pending TCP transition acknowledgement was invalid")

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
            expected_link_counts = expected_counts
            if _reactive_mtu:
                expected_link_counts = (
                    (1, 3, 1)
                    if transition_initiator_index == 1
                    else (1, 2, 2)
                )
            if not all(
                item.get("peer_count") == peer_count
                and item.get("link_count") == link_count
                for item, peer_count, link_count in zip(
                    current_statuses, expected_counts, expected_link_counts
                )
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

        phase = "endpoint-identity-resolution"

        def resolve_remote_identity(
            namespace: str, remote_identity: str, expected_address: str
        ) -> None:
            query = _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    namespace,
                    "dig",
                    "@::1",
                    "-p",
                    "5354",
                    f"{remote_identity}.fips",
                    "AAAA",
                    "+short",
                ],
                label="local FIPS DNS identity resolution",
                timeout=10,
            )
            answers: set[str] = set()
            for line in query.stdout.splitlines():
                try:
                    answers.add(str(ipaddress.IPv6Address(line.strip())))
                except ipaddress.AddressValueError:
                    continue
            if str(ipaddress.IPv6Address(expected_address)) not in answers:
                raise QualificationError(
                    "local FIPS DNS did not return the expected remote overlay address"
                )

        resolve_remote_identity(
            node_a_namespace, identities[2], statuses[2]["ipv6_addr"]
        )
        resolve_remote_identity(
            node_b_namespace, identities[0], statuses[0]["ipv6_addr"]
        )

        def endpoint_identity_caches_ready():
            endpoint_a_cache = control(0, "show", "identity-cache")
            endpoint_b_cache = control(2, "show", "identity-cache")
            endpoint_a_entries = endpoint_a_cache.get("entries")
            endpoint_b_entries = endpoint_b_cache.get("entries")
            if not isinstance(endpoint_a_entries, list) or not isinstance(
                endpoint_b_entries, list
            ):
                return None
            if not any(
                isinstance(item, dict) and item.get("npub") == identities[2]
                for item in endpoint_a_entries
            ):
                return None
            if not any(
                isinstance(item, dict) and item.get("npub") == identities[0]
                for item in endpoint_b_entries
            ):
                return None
            return True

        _wait_for(
            endpoint_identity_caches_ready,
            label="endpoint remote-identity cache registration",
            timeout=(REACTIVE_TICK_INTERVAL_SECS + 5 if _reactive_mtu else 10),
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
        learned_session_path_mtus: list[int] | None = None
        learned_coordinate_path_mtu: int | None = None
        if _reactive_mtu:
            phase = "initial-path-mtu-learning"

            def initial_path_mtu_learned():
                endpoint_views = [control(index, "show", "sessions") for index in (0, 2)]
                records = [
                    endpoint_session_record(endpoint_views[0], identities[2]),
                    endpoint_session_record(endpoint_views[1], identities[0]),
                ]
                if any(record is None for record in records):
                    return None
                session_mtus = [
                    session_path_mtu(endpoint_views[0], identities[2]),
                    session_path_mtu(endpoint_views[1], identities[0]),
                ]
                cache_mtu = coordinate_cache_path_mtu(
                    control(0, "show", "cache"), statuses[2]["ipv6_addr"]
                )
                if session_mtus != [TUN_MTU, TUN_MTU] or cache_mtu != TUN_MTU:
                    return None
                return records, session_mtus, cache_mtu

            initial_records, initial_session_path_mtus, initial_cache_path_mtu = _wait_for(
                initial_path_mtu_learned,
                label="initial 1280-byte end-to-end path MTU",
                timeout=45,
            )
            initial_session_starts = [
                initial_records[0]["session_start_ms"],
                initial_records[1]["session_start_ms"],
            ]
            initial_path_mtu_observation = {
                "configured_transport_path_mtu": TUN_MTU,
                "endpoint_session_path_mtus": initial_session_path_mtus,
                "coordinate_cache_path_mtu": initial_cache_path_mtu,
            }
            initial_source_peer = active_peer_record(peer_views[0], identities[1])
            initial_bottleneck_peers = [
                active_peer_record(peer_views[1], identities[2]),
                active_peer_record(peer_views[2], identities[1]),
            ]
            if initial_source_peer is None or any(
                peer is None for peer in initial_bottleneck_peers
            ):
                raise QualificationError("initial FMP link records were unavailable")
            initial_source_link_id = initial_source_peer.get("link_id")
            initial_bottleneck_link_ids = [
                peer.get("link_id") for peer in initial_bottleneck_peers
            ]
            if (
                not isinstance(initial_source_link_id, int)
                or isinstance(initial_source_link_id, bool)
                or any(
                    not isinstance(link_id, int) or isinstance(link_id, bool)
                    for link_id in initial_bottleneck_link_ids
                )
                or initial_source_peer.get("transport_type") != "udp"
                or any(
                    peer.get("transport_type") != "udp"
                    for peer in initial_bottleneck_peers
                )
            ):
                raise QualificationError("initial line did not use the expected UDP links")

            before_reactive_records = [
                endpoint_session_record(control(0, "show", "sessions"), identities[2]),
                endpoint_session_record(control(2, "show", "sessions"), identities[0]),
            ]
            if any(record is None for record in before_reactive_records):
                raise QualificationError("endpoint FSP session disappeared before link transition")
            before_reactive_starts = [
                before_reactive_records[0]["session_start_ms"],
                before_reactive_records[1]["session_start_ms"],
            ]
            before_reactive_mtu = session_path_mtu(
                control(0, "show", "sessions"), identities[2]
            )
            before_reactive_cache_mtu = coordinate_cache_path_mtu(
                control(0, "show", "cache"), statuses[2]["ipv6_addr"]
            )
            if (
                before_reactive_starts != initial_session_starts
                or before_reactive_mtu != TUN_MTU
                or before_reactive_cache_mtu != TUN_MTU
            ):
                raise QualificationError(
                    "route loss or proactive PMTU feedback pre-empted the reactive baseline"
                )
            endpoint_error_before = mtu_error_counters(control(0, "show", "routing"))
            transit_drop_before = mtu_drop_counters(control(1, "show", "routing"))
            transition_markers_before = [
                daemon_logs[index]
                .read_text(encoding="utf-8", errors="replace")
                .count(CROSS_CONNECTION_WON_LOG_MARKER)
                for index in (1, 2)
            ]

            phase = "bottleneck-link-transport-transition"
            if (
                transition_initiator_index is None
                or transition_namespace is None
                or transition_interface is None
            ):
                raise QualificationError("pending TCP transition state was unavailable")
            initiator_index = transition_initiator_index
            transition_started = time.monotonic()
            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    transition_namespace,
                    "tc",
                    "qdisc",
                    "del",
                    "dev",
                    transition_interface,
                    "root",
                ],
                label="release pending TCP transition candidate",
            )

            def cross_transport_link_promoted():
                current_counts = [
                    daemon_logs[index]
                    .read_text(encoding="utf-8", errors="replace")
                    .count(CROSS_CONNECTION_WON_LOG_MARKER)
                    for index in (1, 2)
                ]
                if any(
                    after <= before
                    for before, after in zip(
                        transition_markers_before, current_counts
                    )
                ):
                    return None
                return True

            _wait_for(
                cross_transport_link_promoted,
                label="hitless R-B FMP transition from UDP to TCP",
                timeout=TRANSPORT_TRANSITION_BUDGET_SECS,
                interval=0.01,
            )
            transport_transition_elapsed_ms = round(
                (time.monotonic() - transition_started) * 1000
            )
            time.sleep(0.05)

            reactive_started = time.monotonic()
            phase = "reactive-mtu-exceeded"
            reactive_diagnostic: dict = {}

            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    node_a_namespace,
                    sys.executable,
                    "-c",
                    (
                        "import socket,sys;"
                        "sock=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM);"
                        "sock.sendto(bytes(int(sys.argv[3])),"
                        "(sys.argv[1],int(sys.argv[2])))"
                    ),
                    destination,
                    str(UDP_PROBE_PORT),
                    "1155",
                ],
                label="reactive oversized UDP/IPv6 trigger",
                timeout=3,
            )

            def reactive_signal_observed():
                endpoint_routing = control(0, "show", "routing")
                transit_routing = control(1, "show", "routing")
                endpoint_errors = mtu_error_counters(endpoint_routing)
                transit_drops = mtu_drop_counters(transit_routing)
                current_mtu = session_path_mtu(
                    control(0, "show", "sessions"), identities[2]
                )
                current_statuses = [status(index) for index in range(3)]
                transit_forwarding = transit_routing.get("forwarding", {})
                reactive_diagnostic.clear()
                reactive_diagnostic.update(
                    {
                        "peer_counts": [item.get("peer_count") for item in current_statuses],
                        "link_counts": [item.get("link_count") for item in current_statuses],
                        "endpoint_error_counters": list(endpoint_errors),
                        "transit_mtu_drop_counters": list(transit_drops),
                        "transit_forwarded_packets": transit_forwarding.get(
                            "forwarded_packets"
                        ),
                        "transit_no_route_packets": transit_forwarding.get(
                            "drop_no_route_packets"
                        ),
                        "session_path_mtu": current_mtu,
                        "coordinate_cache_path_mtu": coordinate_cache_path_mtu(
                            control(0, "show", "cache"), statuses[2]["ipv6_addr"]
                        ),
                    }
                )
                if (
                    endpoint_errors[0] <= endpoint_error_before[0]
                    or transit_drops[0] <= transit_drop_before[0]
                    or current_mtu != TRANSIT_UDP_MTU
                ):
                    return None
                return endpoint_errors, transit_drops

            try:
                endpoint_error_after, transit_drop_after = _wait_for(
                    reactive_signal_observed,
                    label="reactive MtuExceeded convergence",
                    timeout=REACTIVE_CONVERGENCE_BUDGET_SECS,
                    interval=0.1,
                )
            except QualificationError as exc:
                raise QualificationError(
                    "reactive MtuExceeded convergence diagnostics: "
                    + json.dumps(reactive_diagnostic, sort_keys=True)
                ) from exc
            reactive_elapsed_ms = round((time.monotonic() - reactive_started) * 1000)

            def final_path_mtu_learned():
                endpoint_views = [control(index, "show", "sessions") for index in (0, 2)]
                records = [
                    endpoint_session_record(endpoint_views[0], identities[2]),
                    endpoint_session_record(endpoint_views[1], identities[0]),
                ]
                if any(record is None for record in records):
                    return None
                session_mtus = [
                    session_path_mtu(endpoint_views[0], identities[2]),
                    session_path_mtu(endpoint_views[1], identities[0]),
                ]
                cache_mtu = coordinate_cache_path_mtu(
                    control(0, "show", "cache"), statuses[2]["ipv6_addr"]
                )
                if session_mtus != [TRANSIT_UDP_MTU, TRANSIT_UDP_MTU]:
                    return None
                if cache_mtu != TRANSIT_UDP_MTU:
                    return None
                return records, session_mtus, cache_mtu

            final_records, learned_session_path_mtus, learned_coordinate_path_mtu = _wait_for(
                final_path_mtu_learned,
                label="post-reactive bidirectional path MTU convergence",
                timeout=35,
            )
            final_session_starts = [
                final_records[0]["session_start_ms"],
                final_records[1]["session_start_ms"],
            ]
            if final_session_starts != initial_session_starts:
                raise QualificationError(
                    "endpoint FSP session start changed across the link transition"
                )

            def transitioned_line():
                current_statuses = [status(index) for index in range(3)]
                expected_counts = (1, 2, 1)
                if not all(
                    item.get("peer_count") == count and item.get("link_count") == count
                    for item, count in zip(current_statuses, expected_counts)
                ):
                    return None
                current_peer_views = [
                    control(index, "show", "peers") for index in range(3)
                ]
                if not line_peer_relationships(current_peer_views, identities):
                    return None
                source_peer = active_peer_record(current_peer_views[0], identities[1])
                bottleneck_peers = [
                    active_peer_record(current_peer_views[1], identities[2]),
                    active_peer_record(current_peer_views[2], identities[1]),
                ]
                if source_peer is None or any(peer is None for peer in bottleneck_peers):
                    return None
                source_link_id = source_peer.get("link_id")
                bottleneck_link_ids = [
                    peer.get("link_id") for peer in bottleneck_peers
                ]
                if (
                    not isinstance(source_link_id, int)
                    or isinstance(source_link_id, bool)
                    or any(
                        not isinstance(link_id, int) or isinstance(link_id, bool)
                        for link_id in bottleneck_link_ids
                    )
                ):
                    return None
                if (
                    source_link_id != initial_source_link_id
                    or source_peer.get("transport_type") != "udp"
                    or any(
                        peer.get("transport_type") != "tcp"
                        for peer in bottleneck_peers
                    )
                    or any(
                        after == before
                        for before, after in zip(
                            initial_bottleneck_link_ids, bottleneck_link_ids
                        )
                    )
                ):
                    return None
                return source_link_id, bottleneck_link_ids

            final_source_link_id, final_bottleneck_link_ids = _wait_for(
                transitioned_line,
                label="post-trigger UDP/TCP line snapshot",
                timeout=REACTIVE_TICK_INTERVAL_SECS + 5,
            )
            transport_transition_observation = {
                "mechanism": "prestarted-delayed-cross-transport-link-replacement",
                "daemon_restarts": 0,
                "node_identities_preserved": True,
                "endpoint_links_explicitly_withdrawn": False,
                "transition_initiator": ("r" if initiator_index == 1 else "b"),
                "transition_connect_commands": 1,
                "tcp_candidate_started_before_udp": True,
                "tcp_candidate_release": "port-selective-tc-qdisc-removal",
                "source_link_transport_before": "udp",
                "source_link_transport_after": "udp",
                "bottleneck_link_transport_before": "udp",
                "bottleneck_link_transport_after": "tcp",
                "source_link_id_before": initial_source_link_id,
                "source_link_id_after": final_source_link_id,
                "bottleneck_link_ids_before": initial_bottleneck_link_ids,
                "bottleneck_link_ids_after": final_bottleneck_link_ids,
                "transition_elapsed_ms": transport_transition_elapsed_ms,
                "transition_budget_ms": TRANSPORT_TRANSITION_BUDGET_SECS * 1000,
                "post_change_application_packets_before_trigger": 0,
                "source_coordinate_cache_path_mtu_before_trigger": (
                    before_reactive_cache_mtu
                ),
                "source_pmtu_snapshot_phase": "pre-transition-reactive-baseline",
                "transport_mtu_before": TUN_MTU,
                "transport_mtu_after": TRANSIT_UDP_MTU,
                "endpoint_session_start_ms_before": initial_session_starts,
                "endpoint_session_start_ms_after": final_session_starts,
            }
            reactive_mtu_observation = {
                "trigger_ipv6_packet_bytes": 1203,
                "trigger_transport": "udp",
                "trigger_count": 1,
                "session_path_mtu_before": TUN_MTU,
                "session_path_mtu_after": TRANSIT_UDP_MTU,
                "coordinate_cache_path_mtu_after": learned_coordinate_path_mtu,
                "endpoint_mtu_exceeded_delta": (
                    endpoint_error_after[0] - endpoint_error_before[0]
                ),
                "endpoint_below_floor_delta": (
                    endpoint_error_after[1] - endpoint_error_before[1]
                ),
                "endpoint_uncorroborated_delta": (
                    endpoint_error_after[2] - endpoint_error_before[2]
                ),
                "transit_drop_packets_delta": (
                    transit_drop_after[0] - transit_drop_before[0]
                ),
                "transit_drop_bytes_delta": (
                    transit_drop_after[1] - transit_drop_before[1]
                ),
                "convergence_elapsed_ms": reactive_elapsed_ms,
                "convergence_budget_ms": REACTIVE_CONVERGENCE_BUDGET_SECS * 1000,
            }

        if _heterogeneous_mtu:
            phase = "multihop-path-mtu-learning"

            def path_mtu_learned():
                endpoint_a_sessions = control(0, "show", "sessions")
                endpoint_b_sessions = control(2, "show", "sessions")
                session_mtus = [
                    session_path_mtu(endpoint_a_sessions, identities[2]),
                    session_path_mtu(endpoint_b_sessions, identities[0]),
                ]
                cache_mtu = coordinate_cache_path_mtu(
                    control(0, "show", "cache"), statuses[2]["ipv6_addr"]
                )
                if session_mtus != [TRANSIT_UDP_MTU, TRANSIT_UDP_MTU]:
                    return None
                if cache_mtu != TRANSIT_UDP_MTU:
                    return None
                return session_mtus, cache_mtu

            learned_session_path_mtus, learned_coordinate_path_mtu = _wait_for(
                path_mtu_learned,
                label="heterogeneous multihop path MTU learning",
                timeout=30,
            )

        if path_mtu_mode:
            phase = "multihop-path-mtu-boundary"
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
                str(boundary_icmp_payload),
                destination,
            ],
            label="path-MTU-boundary multihop ICMPv6 probe",
            timeout=30,
        )

        if path_mtu_mode:
            ptb_ready_path = work / "ptb-probe.ready"
            ptb_result_path = work / "ptb-probe.json"
            ptb_probe = subprocess.Popen(
                [
                    "ip",
                    "netns",
                    "exec",
                    node_a_namespace,
                    sys.executable,
                    "-m",
                    "rimf_lab.icmpv6_ptb_probe",
                    "--interface",
                    "fips0",
                    "--ready",
                    str(ptb_ready_path),
                    "--output",
                    str(ptb_result_path),
                    "--timeout",
                    "10",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            def ptb_probe_ready():
                if ptb_probe is None or ptb_probe.poll() is not None:
                    raise QualificationError("ICMPv6 PTB observer exited before becoming ready")
                return ptb_ready_path.is_file()

            _wait_for(ptb_probe_ready, label="ICMPv6 PTB observer", timeout=10)
            above_boundary_probe = _run(
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
                    "5",
                    "-s",
                    str(PATH_ABOVE_BOUNDARY_ICMP_PAYLOAD),
                    destination,
                ],
                label="one-byte-above-multihop-path-MTU ICMPv6 probe",
                timeout=10,
                check=False,
            )
            if above_boundary_probe.returncode == 0:
                raise QualificationError(
                    "above-path-MTU probe unexpectedly received an echo reply"
                )
            try:
                ptb_probe.wait(timeout=12)
            except subprocess.TimeoutExpired as exc:
                raise QualificationError("ICMPv6 PTB observer did not finish") from exc
            if ptb_probe.returncode != 0 or not ptb_result_path.is_file():
                raise QualificationError(
                    "ICMPv6 PTB observer did not capture a Packet Too Big message"
                )
            try:
                ptb_observation = json.loads(ptb_result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise QualificationError("ICMPv6 PTB observer returned invalid JSON") from exc
            expected_ptb = {
                "status": "passed",
                "icmpv6_type": 2,
                "icmpv6_code": 0,
                "reported_mtu": PATH_EFFECTIVE_IPV6_MTU,
            }
            if ptb_observation != expected_ptb:
                raise QualificationError(
                    "ICMPv6 PTB observation did not report the multihop path MTU"
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
                    str(PATH_BOUNDARY_ICMP_PAYLOAD),
                    destination,
                ],
                label="post-PTB multihop boundary ICMPv6 probe",
                timeout=30,
            )
            path_mtu_observation = {
                "endpoint_effective_ipv6_mtu": EFFECTIVE_IPV6_MTU,
                "transit_transport_mtu": TRANSIT_UDP_MTU,
                "learned_transport_path_mtu": learned_coordinate_path_mtu,
                "endpoint_session_path_mtus": learned_session_path_mtus,
                "effective_ipv6_path_mtu": PATH_EFFECTIVE_IPV6_MTU,
                "boundary_icmp_payload_bytes": PATH_BOUNDARY_ICMP_PAYLOAD,
                "above_boundary_icmp_payload_bytes": PATH_ABOVE_BOUNDARY_ICMP_PAYLOAD,
                "above_boundary_ipv6_packet_bytes": PATH_ABOVE_BOUNDARY_IPV6_BYTES,
                "echo_reply_received": False,
                "icmpv6_type": ptb_observation["icmpv6_type"],
                "icmpv6_code": ptb_observation["icmpv6_code"],
                "reported_mtu": ptb_observation["reported_mtu"],
                "post_ptb_boundary_probe_passed": True,
            }

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
                str(len(payload_sizes)),
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
                *[str(size) for size in payload_sizes],
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
            or [item.get("bytes") for item in payload_records] != list(payload_sizes)
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
            "identity_resolution": {
                "mechanism": "local-fips-dns-npub",
                "endpoint_remote_identities_registered": True,
                "public_discovery_used": False,
            },
            "nodes": node_observations,
            "mmp": mmp_observations,
            "icmpv6": {
                "path": "endpoint-a-via-managed-transit-r-to-endpoint-b",
                "small_payload_bytes": 32,
                "effective_mtu_boundary_payload_bytes": boundary_icmp_payload,
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
        if path_mtu_mode:
            if path_mtu_observation is None:
                raise QualificationError("multihop path MTU observation is unavailable")
            observations["path_mtu"] = path_mtu_observation
        if _reactive_mtu:
            if (
                initial_path_mtu_observation is None
                or transport_transition_observation is None
                or reactive_mtu_observation is None
            ):
                raise QualificationError("reactive MTU observations are unavailable")
            observations["initial_path_mtu"] = initial_path_mtu_observation
            observations["transport_transition"] = transport_transition_observation
            observations["reactive_mtu"] = reactive_mtu_observation
    except Exception as exc:
        error = exc
        for stream in daemon_streams:
            stream.flush()
        _print_redacted_log_tails(daemon_logs)
    finally:
        phase_at_failure = phase
        _stop_process(payload_server)
        _stop_process(ptb_probe)
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
            evidence_type=evidence_type,
        )
        _write_result(output, result)
        raise QualificationError(
            f"G2 managed-transit qualification failed during {phase_at_failure}"
        ) from error

    result = {
        "schema_version": 1,
        "evidence_type": evidence_type,
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
            "A static, explicitly connected three-node FIPS line was exercised; endpoint identities were registered through each endpoint's loopback-only FIPS DNS responder, while Nostr discovery, a Nostr signaling relay, and NAT traversal were not part of this run.",
            "The managed transit node was not impaired, restarted, removed, or compared with an alternate route.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
            "Payload opacity at the transit node follows the pinned FIPS protocol contract; this runner did not capture or cryptographically inspect transit packets.",
            "This run qualifies Linux TUN transit connectivity for the pinned host architecture only.",
        ],
    }
    if _heterogeneous_mtu:
        result["topology"] = {
            "node_count": 3,
            "namespace_count": 3,
            "authenticated_link_count": 2,
            "isolation": "linux-network-namespaces",
            "underlay": "two-segment-line-ipv4-udp",
            "path_role": "managed-fips-transit",
            "public_discovery": False,
            "nostr_relay": False,
            "tun_name": "fips0",
            "configured_tun_mtu_per_node": [TUN_MTU, TUN_MTU, TUN_MTU],
            "configured_udp_mtu_per_node": list(udp_mtus),
            "bottleneck_node": "r",
        }
        result["limitations"] = [
            "A static, explicitly connected three-node FIPS line was exercised; public discovery, Nostr relays, and NAT traversal were not part of this run.",
            "The heterogeneous constraint was the transit node's configured FIPS UDP transport MTU, not a changing physical underlay MTU or a black-holed ICMP path.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
            "This run qualifies one proactive discovery/session PMTUD case on Linux for the pinned host architecture only.",
        ]
    if _reactive_mtu:
        result["topology"] = {
            "node_count": 3,
            "namespace_count": 3,
            "authenticated_link_count": 2,
            "isolation": "linux-network-namespaces",
            "underlay": "two-segment-line-ipv4",
            "path_role": "managed-fips-transit",
            "public_discovery": False,
            "nostr_relay": False,
            "tun_name": "fips0",
            "configured_tun_mtu_per_node": [TUN_MTU, TUN_MTU, TUN_MTU],
            "configured_udp_mtu_per_node": [TUN_MTU, TUN_MTU, TUN_MTU],
            "configured_tcp_mtu_per_node": [None, TRANSIT_UDP_MTU, TRANSIT_UDP_MTU],
            "initial_link_transports": ["udp", "udp"],
            "final_link_transports": ["udp", "tcp"],
            "bottleneck_hop": "r-b",
        }
        result["limitations"] = [
            "FIPS v0.4.2 does not hot-reload transport MTU configuration and its public connect API skips an already-active peer; the changing constraint was therefore modeled with a prestarted TCP candidate held by a port-selective Linux tc rule until the UDP baseline was proven.",
            "The deterministic cross-connection winner replaced only the bottleneck link without explicit withdrawal, process restart, node-identity change, or endpoint FSP session replacement.",
            "No post-change application packet preceded the oversized trigger; the last pre-transition source coordinate-cache and endpoint-session snapshot reported path MTU 1280, and unchanged session timestamps were verified after convergence.",
            "The changing constraint was a FIPS transport/link transition, not a physical underlay MTU change or an ICMP black hole.",
            "A ten-second qualification-only node tick isolated the reactive MtuExceeded window; the FIPS production default remains one second.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
        ]
    _write_result(output, result)
    return result


def run_fips_g2_linux_multihop_mtu(
    *,
    fips_source: Path,
    fips_binary: Path,
    fipsctl_binary: Path,
    output: Path,
    project_revision: str,
) -> dict:
    return run_fips_g2_linux_managed_transit(
        fips_source=fips_source,
        fips_binary=fips_binary,
        fipsctl_binary=fipsctl_binary,
        output=output,
        project_revision=project_revision,
        _heterogeneous_mtu=True,
    )


def run_fips_g2_linux_reactive_mtu(
    *,
    fips_source: Path,
    fips_binary: Path,
    fipsctl_binary: Path,
    output: Path,
    project_revision: str,
) -> dict:
    return run_fips_g2_linux_managed_transit(
        fips_source=fips_source,
        fips_binary=fips_binary,
        fipsctl_binary=fipsctl_binary,
        output=output,
        project_revision=project_revision,
        _reactive_mtu=True,
    )
