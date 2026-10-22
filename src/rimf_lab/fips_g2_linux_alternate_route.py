from __future__ import annotations

import hashlib
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
from collections import deque
from collections.abc import Sequence
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
    sha256_file,
    utc_now,
)
from .fips_g2_linux_managed_transit import forwarding_counters


LINK_DEAD_TIMEOUT_SECS = 30
HEARTBEAT_INTERVAL_SECS = 10
TICK_INTERVAL_SECS = 1
RETRY_BASE_INTERVAL_SECS = 5
RETRY_MAX_BACKOFF_SECS = 300
REPARENT_BUDGET_SECS = 60
PAYLOAD_RECOVERY_BUDGET_SECS = 180
SESSION_IDLE_TIMEOUT_SECS = 90
SESSION_POLL_INTERVAL_SECS = 0.25
ALTERNATE_PATH_ONE_WAY_DELAY_MS = 20
UDP_PROBE_PORT = 42045
NPUB_RE = re.compile(r"^npub1[023456789acdefghjklmnpqrstuvwxyz]+$")
NODE_ADDR_RE = re.compile(r"^[0-9a-f]{32}$")
DIAGNOSTIC_INTERVAL_NS = 5_000_000_000
MAX_DIAGNOSTIC_SAMPLES = 32
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

ROLE_NAMES = ("a", "r1", "r2", "b")
ROLE_KINDS = ("endpoint-root", "managed-transit", "managed-transit", "endpoint-leaf")
NODE_ADDRESSES = (
    ("10.208.1.1", "10.208.3.1"),
    ("10.208.1.2", "10.208.2.1"),
    ("10.208.3.2", "10.208.4.1"),
    ("10.208.2.2", "10.208.4.2"),
)


def _bech32_polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(character) >> 5 for character in hrp] + [0] + [
        ord(character) & 31 for character in hrp
    ]


def _convert_five_to_eight_bits(values: list[int]) -> bytes:
    accumulator = 0
    bit_count = 0
    result = bytearray()
    for value in values:
        if value < 0 or value > 31:
            raise ValueError("npub contains an invalid Bech32 value")
        accumulator = (accumulator << 5) | value
        bit_count += 5
        while bit_count >= 8:
            bit_count -= 8
            result.append((accumulator >> bit_count) & 0xFF)
    if bit_count >= 5 or ((accumulator << (8 - bit_count)) & 0xFF):
        raise ValueError("npub contains invalid Bech32 padding")
    return bytes(result)


def node_addr_from_npub(npub: str) -> str:
    """Derive the exact FIPS NodeAddr without retaining the public identity."""
    if not isinstance(npub, str) or npub.lower() != npub or not NPUB_RE.fullmatch(npub):
        raise ValueError("npub is invalid")
    separator = npub.rfind("1")
    hrp = npub[:separator]
    encoded = npub[separator + 1 :]
    if hrp != "npub" or len(encoded) < 7:
        raise ValueError("npub has an invalid Bech32 envelope")
    try:
        values = [BECH32_CHARSET.index(character) for character in encoded]
    except ValueError as exc:
        raise ValueError("npub contains an invalid Bech32 character") from exc
    if _bech32_polymod(_bech32_hrp_expand(hrp) + values) != 1:
        raise ValueError("npub checksum is invalid")
    public_key = _convert_five_to_eight_bits(values[:-6])
    if len(public_key) != 32:
        raise ValueError("npub payload is not a 32-byte x-only public key")
    return hashlib.sha256(public_key).hexdigest()[:32]


def diamond_peer_relationships(peer_views: list[dict], identities: list[str]) -> bool:
    if len(peer_views) != 4 or len(identities) != 4:
        return False
    observed: list[set[str]] = []
    for view in peer_views:
        peers = view.get("peers")
        if not isinstance(peers, list):
            return False
        npubs = {item.get("npub") for item in peers if isinstance(item, dict)}
        if len(npubs) != len(peers) or any(not isinstance(item, str) for item in npubs):
            return False
        observed.append(npubs)
    node_a, transit_r1, transit_r2, node_b = identities
    return observed == [
        {transit_r1, transit_r2},
        {node_a, node_b},
        {node_a, node_b},
        {transit_r1, transit_r2},
    ]


def diamond_tree_relationships(tree_views: list[dict], node_addrs: Sequence[str]) -> bool:
    """Accept either authenticated transit as B's active tree parent."""
    if len(tree_views) != 4 or len(node_addrs) != 4:
        return False
    return (
        all(item.get("root") == node_addrs[0] for item in tree_views)
        and [item.get("depth") for item in tree_views] == [0, 1, 1, 2]
        and tree_views[1].get("parent") == node_addrs[0]
        and tree_views[2].get("parent") == node_addrs[0]
        and tree_views[3].get("parent") in node_addrs[1:3]
    )


def render_alternate_route_config(
    control_socket: Path,
    *,
    dns_enabled: bool,
    peers: list[tuple[str, str, str]],
) -> str:
    peer_lines: list[str] = []
    for alias, npub, address in peers:
        if not alias or not NPUB_RE.fullmatch(npub):
            raise ValueError("static peer specification is invalid")
        peer_lines.append(
            f'''  - npub: "{npub}"
    alias: "{alias}"
    addresses:
      - transport: "udp"
        addr: "{address}:2121"
        priority: 100
    connect_policy: "auto_connect"
    auto_reconnect: true
    via_nostr: false'''
        )
    peers_yaml = "peers: []" if not peer_lines else "peers:\n" + "\n".join(peer_lines)
    dns_yaml = (
        '  enabled: true\n  bind_addr: "::1"\n  port: 5354'
        if dns_enabled
        else "  enabled: false"
    )
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
  name: "fips0"
  mtu: {TUN_MTU}

dns:
{dns_yaml}

transports:
  udp:
    bind_addr: "0.0.0.0:2121"
    mtu: {TUN_MTU}

{peers_yaml}
'''


def alternate_route_timings_within_contract(
    reparent_elapsed_ms: int, payload_recovery_elapsed_ms: int
) -> bool:
    return (
        0 < reparent_elapsed_ms <= REPARENT_BUDGET_SECS * 1000
        and reparent_elapsed_ms <= payload_recovery_elapsed_ms
        and payload_recovery_elapsed_ms <= PAYLOAD_RECOVERY_BUDGET_SECS * 1000
    )


def project_diamond_node(
    role: str,
    status_view: dict | None,
    peers_view: dict | None,
    tree_view: dict | None,
    routing_view: dict | None,
    role_by_npub: dict[str, str],
    role_by_addr: dict[str, str],
) -> dict:
    """Keep bounded counters and local role names from FIPS control views."""
    status_view = status_view if isinstance(status_view, dict) else {}
    peers_view = peers_view if isinstance(peers_view, dict) else {}
    tree_view = tree_view if isinstance(tree_view, dict) else {}
    routing_view = routing_view if isinstance(routing_view, dict) else {}

    def count(value: object) -> int | None:
        return value if type(value) is int and 0 <= value <= 1_000_000_000 else None

    def role_of(value: object, mapping: dict[str, str]) -> str:
        return mapping.get(value, "unknown") if isinstance(value, str) else "unknown"

    def counters(view: object, names: tuple[str, ...]) -> dict:
        view = view if isinstance(view, dict) else {}
        return {name: count(view.get(name)) for name in names}

    peers = peers_view.get("peers")
    peer_roles = sorted(
        {
            role_of(peer.get("npub"), role_by_npub)
            for peer in peers if isinstance(peer, dict)
        }
    ) if isinstance(peers, list) else []
    lookup = routing_view.get("lookup")
    if not isinstance(lookup, dict):
        lookup = routing_view.get("discovery")
    pending = routing_view.get("pending_lookups")
    return {
        "role": role,
        "control_available": bool(status_view),
        "peer_count": count(status_view.get("peer_count")),
        "link_count": count(status_view.get("link_count")),
        "session_count": count(status_view.get("session_count")),
        "estimated_mesh_size": count(status_view.get("estimated_mesh_size")),
        "peer_roles": peer_roles,
        "tree": {
            "root_role": role_of(tree_view.get("root"), role_by_addr),
            "parent_role": role_of(tree_view.get("parent"), role_by_addr),
            "depth": count(tree_view.get("depth")),
            "peer_tree_count": count(tree_view.get("peer_tree_count")),
            "stats": counters(
                tree_view.get("stats"),
                ("received", "accepted", "parent_switches", "parent_losses",
                 "flap_dampened", "loop_detected", "stale"),
            ),
        },
        "routing": {
            "coord_cache_entries": count(routing_view.get("coord_cache_entries")),
            "pending_tun_packets": count(routing_view.get("pending_tun_packets")),
            "pending_lookups": len(pending) if isinstance(pending, list) else None,
            "lookup": counters(
                lookup,
                ("req_initiated", "req_received", "req_forwarded", "req_no_tree_peer",
                 "resp_received", "resp_accepted", "resp_timed_out", "resp_no_route"),
            ),
            "forwarding": counters(
                routing_view.get("forwarding"),
                ("originated_packets", "forwarded_packets", "delivered_packets",
                 "drop_no_route_packets"),
            ),
        },
    }


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
        "evidence_type": "fips-g2-linux-alternate-route",
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


def run_fips_g2_linux_alternate_route(
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
        raise QualificationError("the G2 alternate-route runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G2 alternate-route runner requires root")
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
    if provenance["fips_repository"] != FIPS_REPOSITORY:
        raise QualificationError("unexpected FIPS repository provenance")

    suffix = str(os.getpid())
    namespaces = tuple(f"rg2{name}{suffix}" for name in ROLE_NAMES)
    interfaces = (
        f"g2a1{suffix}",
        f"g2r1a{suffix}",
        f"g2r1b{suffix}",
        f"g2b1{suffix}",
        f"g2a2{suffix}",
        f"g2r2a{suffix}",
        f"g2r2b{suffix}",
        f"g2b2{suffix}",
    )
    if any(len(name) > 15 for name in (*namespaces, *interfaces)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")

    work = Path(tempfile.mkdtemp(prefix="rimf-g2-alternate-route-", dir="/tmp"))
    candidate_dirs = tuple(work / f"identity-{index}" for index in range(4))
    role_dirs: tuple[Path, ...] = candidate_dirs
    sockets: tuple[Path, ...] = tuple()
    configs: tuple[Path, ...] = tuple()
    daemon_logs: tuple[Path, ...] = tuple()
    daemon_processes: list[subprocess.Popen | None] = [None, None, None, None]
    daemon_streams: list[object | None] = [None, None, None, None]
    payload_processes: list[subprocess.Popen] = []
    cleanup = {
        "daemons_stopped": False,
        "faulted_daemon_reaped": False,
        "namespaces_removed": False,
        "persistent_identity_directory_removed": False,
    }
    observations: dict = {}
    error: Exception | None = None
    diagnostic_started_ns = time.monotonic_ns()
    diagnostic_last_ns = 0
    diagnostic_samples: deque[dict] = deque(maxlen=MAX_DIAGNOSTIC_SAMPLES)
    role_by_npub: dict[str, str] = {}
    role_by_addr: dict[str, str] = {}

    def control(index: int, *arguments: str) -> dict:
        return _json_command(
            [str(fipsctl_binary), "-s", str(sockets[index]), *arguments],
            label=f"node {ROLE_NAMES[index]} {' '.join(arguments)}",
        )

    def capture_diamond_snapshot(
        capture_phase: str, *, force: bool = False, probe_exit_code: int | None = None
    ) -> None:
        nonlocal diagnostic_last_ns
        now_ns = time.monotonic_ns()
        if not force and now_ns - diagnostic_last_ns < DIAGNOSTIC_INTERVAL_NS:
            return
        diagnostic_last_ns = now_ns
        nodes = []
        for index, role in enumerate(ROLE_NAMES):
            views: list[dict | None] = []
            for command in ("status", "peers", "tree", "routing"):
                try:
                    views.append(
                        _json_command(
                            [str(fipsctl_binary), "-s", str(sockets[index]), "show", command],
                            label=f"diamond diagnostic {role} {command}",
                            timeout=1,
                        )
                    )
                except (QualificationError, IndexError):
                    views.append(None)
            nodes.append(
                project_diamond_node(role, *views, role_by_npub, role_by_addr)
            )
        diagnostic_samples.append({
            "phase": capture_phase,
            "elapsed_ms": (now_ns - diagnostic_started_ns) // 1_000_000,
            "probe_exit_code": probe_exit_code if type(probe_exit_code) is int else None,
            "nodes": nodes,
        })

    def status(index: int) -> dict:
        return control(index, "show", "status")

    def session_views() -> list[dict]:
        return [control(index, "show", "sessions") for index in (0, 3)]

    def endpoint_session_records(
        views: list[dict], identities: tuple[str, ...], starts: tuple[int, int] | None = None
    ) -> tuple[dict, dict]:
        records: list[dict] = []
        for ordinal, (view, remote_npub) in enumerate(
            zip(views, (identities[3], identities[0]))
        ):
            sessions = view.get("sessions")
            if not isinstance(sessions, list) or len(sessions) != 1:
                raise QualificationError(
                    f"endpoint {('a', 'b')[ordinal]} did not expose one FSP session"
                )
            session = sessions[0]
            if (
                not isinstance(session, dict)
                or session.get("npub") != remote_npub
                or session.get("state") != "established"
                or not isinstance(session.get("session_start_ms"), int)
            ):
                raise QualificationError("endpoint FSP session was not established")
            if starts is not None and session["session_start_ms"] != starts[ordinal]:
                raise QualificationError("endpoint FSP session start changed during reconvergence")
            records.append(session)
        return records[0], records[1]

    def validate_node(index: int, node_status: dict) -> dict:
        if (
            node_status.get("tun_state") != "active"
            or node_status.get("tun_name") != "fips0"
            or node_status.get("effective_ipv6_mtu") != EFFECTIVE_IPV6_MTU
            or node_status.get("persistent") is not True
        ):
            raise QualificationError(f"node {ROLE_NAMES[index]} runtime state is invalid")
        link_data = _json_value_command(
            ["ip", "-n", namespaces[index], "-j", "link", "show", "dev", "fips0"],
            label=f"node {ROLE_NAMES[index]} kernel TUN state",
        )
        if (
            not isinstance(link_data, list)
            or len(link_data) != 1
            or link_data[0].get("mtu") != TUN_MTU
        ):
            raise QualificationError(f"node {ROLE_NAMES[index]} kernel TUN state is invalid")
        try:
            ipv6_address = str(ipaddress.IPv6Address(node_status.get("ipv6_addr", "")))
        except ipaddress.AddressValueError as exc:
            raise QualificationError(
                f"node {ROLE_NAMES[index]} mesh address is invalid"
            ) from exc
        if not ipv6_address.startswith("fd"):
            raise QualificationError(f"node {ROLE_NAMES[index]} did not receive a FIPS ULA")
        return {
            "node": ROLE_NAMES[index],
            "role": ROLE_KINDS[index],
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": TUN_MTU,
            "effective_ipv6_mtu": EFFECTIVE_IPV6_MTU,
            "persistent_identity": True,
        }

    def run_payload_probe(label: str, destination: str) -> list[dict]:
        ready_path = work / f"payload-{label}.ready"
        server_result_path = work / f"payload-{label}-server.json"
        client_result_path = work / f"payload-{label}-client.json"
        server = subprocess.Popen(
            [
                "ip",
                "netns",
                "exec",
                namespaces[3],
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
            {"bytes": item["bytes"], "sha256": item["sha256"]} for item in records or []
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
        phase = "identity-and-config-setup"
        identity_records: list[tuple[str, str, Path]] = []
        for candidate_dir in candidate_dirs:
            candidate_dir.mkdir(mode=0o700)
            _run(
                [str(fipsctl_binary), "keygen", "--dir", str(candidate_dir)],
                label="generate temporary persistent identity",
            )
            identity = (candidate_dir / "fips.pub").read_text(encoding="utf-8").strip()
            identity_records.append((node_addr_from_npub(identity), identity, candidate_dir))
        identity_records.sort(key=lambda item: item[0])
        node_addrs = tuple(item[0] for item in identity_records)
        identities = tuple(item[1] for item in identity_records)
        role_by_npub = dict(zip(identities, ROLE_NAMES))
        role_by_addr = dict(zip(node_addrs, ROLE_NAMES))
        role_dirs = tuple(item[2] for item in identity_records)
        if len(set(node_addrs)) != 4 or not all(NODE_ADDR_RE.fullmatch(item) for item in node_addrs):
            raise QualificationError("temporary identities did not produce unique node addresses")
        if not all(
            stat.S_IMODE((node_dir / "fips.key").stat().st_mode) == 0o600
            and stat.S_IMODE((node_dir / "fips.pub").stat().st_mode) == 0o644
            for node_dir in role_dirs
        ):
            raise QualificationError("temporary identity file modes are invalid")

        sockets = tuple(node_dir / "control.sock" for node_dir in role_dirs)
        configs = tuple(node_dir / "fips.yaml" for node_dir in role_dirs)
        daemon_logs = tuple(node_dir / "daemon.log" for node_dir in role_dirs)
        peer_specs = (
            [],
            [("endpoint-a", identities[0], NODE_ADDRESSES[0][0])],
            [("endpoint-a", identities[0], NODE_ADDRESSES[0][1])],
            [
                ("transit-r1", identities[1], NODE_ADDRESSES[1][1]),
                ("transit-r2", identities[2], NODE_ADDRESSES[2][1]),
            ],
        )
        for index, config in enumerate(configs):
            config.write_text(
                render_alternate_route_config(
                    sockets[index], dns_enabled=index in (0, 3), peers=peer_specs[index]
                ),
                encoding="utf-8",
            )
            config.chmod(0o600)

        phase = "namespace-setup"
        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
            _run(
                ["ip", "-n", namespace, "link", "set", "lo", "up"],
                label=f"bring loopback up in {namespace}",
            )

        links = (
            (interfaces[0], interfaces[1], 0, 1, NODE_ADDRESSES[0][0], NODE_ADDRESSES[1][0]),
            (interfaces[2], interfaces[3], 1, 3, NODE_ADDRESSES[1][1], NODE_ADDRESSES[3][0]),
            (interfaces[4], interfaces[5], 0, 2, NODE_ADDRESSES[0][1], NODE_ADDRESSES[2][0]),
            (interfaces[6], interfaces[7], 2, 3, NODE_ADDRESSES[2][1], NODE_ADDRESSES[3][1]),
        )
        for left, right, left_node, right_node, left_address, right_address in links:
            _run(
                ["ip", "link", "add", left, "type", "veth", "peer", "name", right],
                label="create diamond veth pair",
            )
            for interface, node_index, address in (
                (left, left_node, left_address),
                (right, right_node, right_address),
            ):
                _run(
                    ["ip", "link", "set", interface, "netns", namespaces[node_index]],
                    label="move diamond interface",
                )
                _run(
                    [
                        "ip",
                        "-n",
                        namespaces[node_index],
                        "addr",
                        "add",
                        f"{address}/30",
                        "dev",
                        interface,
                    ],
                    label="assign diamond underlay address",
                )
                _run(
                    ["ip", "-n", namespaces[node_index], "link", "set", interface, "up"],
                    label="bring diamond interface up",
                )
        for index in (1, 2):
            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    namespaces[index],
                    "sysctl",
                    "-q",
                    "-w",
                    "net.ipv4.ip_forward=0",
                ],
                label=f"disable IPv4 forwarding on {ROLE_NAMES[index]}",
            )
        for index, interface in ((2, interfaces[6]), (3, interfaces[7])):
            _run(
                [
                    "ip",
                    "netns",
                    "exec",
                    namespaces[index],
                    "tc",
                    "qdisc",
                    "add",
                    "dev",
                    interface,
                    "root",
                    "netem",
                    "delay",
                    f"{ALTERNATE_PATH_ONE_WAY_DELAY_MS}ms",
                ],
                label="apply alternate-path latency stimulus",
            )

        phase = "direct-underlay-exclusion"
        direct_probe = _run(
            [
                "ip",
                "netns",
                "exec",
                namespaces[0],
                "ping",
                "-c",
                "1",
                "-W",
                "1",
                NODE_ADDRESSES[3][0],
            ],
            label="endpoint direct-underlay exclusion probe",
            timeout=5,
            check=False,
        )
        if direct_probe.returncode == 0:
            raise QualificationError("endpoint A unexpectedly reached B over the IPv4 underlay")

        phase = "daemon-start"
        for index, (namespace, config, daemon_log) in enumerate(
            zip(namespaces, configs, daemon_logs)
        ):
            stream = daemon_log.open("w", encoding="utf-8")
            daemon_streams[index] = stream
            daemon_processes[index] = subprocess.Popen(
                ["ip", "netns", "exec", namespace, str(fips_binary), "-c", str(config)],
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

        def controls_ready():
            if any(
                process is None or process.poll() is not None for process in daemon_processes
            ):
                raise QualificationError("a FIPS daemon exited before control became ready")
            if not all(socket_path.is_socket() for socket_path in sockets):
                return None
            try:
                return [status(index) for index in range(4)]
            except QualificationError:
                return None

        statuses = _wait_for(controls_ready, label="four FIPS control sockets", timeout=30)
        if [item.get("npub") for item in statuses] != list(identities):
            raise QualificationError("daemon identities did not match role-assigned key files")
        nodes = [validate_node(index, node_status) for index, node_status in enumerate(statuses)]

        phase = "diamond-convergence"

        def converged_diamond():
            current_statuses = [status(index) for index in range(4)]
            capture_diamond_snapshot(phase)
            if not all(
                item.get("peer_count") == 2 and item.get("link_count") == 2
                for item in current_statuses
            ):
                return None
            peer_views = [control(index, "show", "peers") for index in range(4)]
            if not diamond_peer_relationships(peer_views, list(identities)):
                return None
            tree_views = [control(index, "show", "tree") for index in range(4)]
            if not diamond_tree_relationships(tree_views, node_addrs):
                return None
            return current_statuses, peer_views, tree_views

        statuses, peer_views, tree_views = _wait_for(
            converged_diamond,
            label="four-node authenticated diamond and spanning tree",
            timeout=60,
        )

        phase = "mmp-observation"

        def full_mmp_views():
            current = [control(index, "show", "peers") for index in range(4)]
            if not diamond_peer_relationships(current, list(identities)):
                return None
            peers = [peer for view in current for peer in view.get("peers", [])]
            if len(peers) != 8:
                return None
            if not all(
                isinstance(peer.get("mmp"), dict)
                and peer["mmp"].get("mode") == "full"
                and isinstance(peer["mmp"].get("srtt_ms"), (int, float))
                for peer in peers
            ):
                return None
            return current

        peer_views = _wait_for(
            full_mmp_views, label="full MMP on all eight direct-link views", timeout=30
        )

        phase = "endpoint-identity-resolution"
        for namespace, remote_identity, expected_address in (
            (namespaces[0], identities[3], statuses[3]["ipv6_addr"]),
            (namespaces[3], identities[0], statuses[0]["ipv6_addr"]),
        ):
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
                raise QualificationError("FIPS DNS did not return the remote overlay address")

        def endpoint_identity_caches_ready():
            endpoint_a_cache = control(0, "show", "identity-cache")
            endpoint_b_cache = control(3, "show", "identity-cache")
            endpoint_a_entries = endpoint_a_cache.get("entries")
            endpoint_b_entries = endpoint_b_cache.get("entries")
            if not isinstance(endpoint_a_entries, list) or not isinstance(
                endpoint_b_entries, list
            ):
                return None
            if not any(
                isinstance(item, dict) and item.get("npub") == identities[3]
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
            timeout=10,
        )

        phase = "initial-data-plane"
        destination = statuses[3]["ipv6_addr"]

        def initial_route_ready():
            result = _run(
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
                label="initial alternate-route discovery probe",
                timeout=5,
                check=False,
            )
            capture_diamond_snapshot(phase, probe_exit_code=result.returncode)
            return result.returncode == 0

        _wait_for(initial_route_ready, label="initial overlay route", timeout=45, interval=1)
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

        initial_sessions = endpoint_session_records(session_views(), identities)
        initial_session_starts = (
            initial_sessions[0]["session_start_ms"],
            initial_sessions[1]["session_start_ms"],
        )
        transit_before = [forwarding_counters(control(index, "show", "routing")) for index in (1, 2)]
        initial_payload = run_payload_probe("before-failure", destination)
        transit_after = [forwarding_counters(control(index, "show", "routing")) for index in (1, 2)]
        packet_deltas = [after[0] - before[0] for before, after in zip(transit_before, transit_after)]
        byte_deltas = [after[1] - before[1] for before, after in zip(transit_before, transit_after)]

        initial_b_tree = control(3, "show", "tree")
        active_addr = initial_b_tree.get("parent")
        if active_addr not in node_addrs[1:3]:
            raise QualificationError("endpoint B parent was not a managed transit")
        active_index = node_addrs.index(active_addr)
        alternate_index = 1 if active_index == 2 else 2
        if packet_deltas[active_index - 1] < 1 or byte_deltas[active_index - 1] < 1:
            raise QualificationError("B's parent did not forward the initial exact payload")
        if (
            packet_deltas[alternate_index - 1] < 0
            or byte_deltas[alternate_index - 1] < 0
        ):
            raise QualificationError("alternate transit forwarding counters regressed")
        if status(1).get("session_count") != 0 or status(2).get("session_count") != 0:
            raise QualificationError("a managed transit terminated an end-to-end FSP session")

        phase = "active-transit-failure"
        failure_started = time.monotonic()
        if not _hard_kill_process(daemon_processes[active_index]):
            raise QualificationError("active transit did not terminate from SIGKILL")
        cleanup["faulted_daemon_reaped"] = True
        daemon_processes[active_index] = None
        if daemon_streams[active_index] is not None:
            daemon_streams[active_index].close()
            daemon_streams[active_index] = None

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
            label="active-path outage probe",
            timeout=5,
            check=False,
        )
        if outage_probe.returncode == 0:
            raise QualificationError("overlay probe unexpectedly succeeded before link-dead detection")

        phase = "automatic-reparenting"
        session_poll_count = 0
        deadline = time.monotonic() + REPARENT_BUDGET_SECS
        post_tree_views: tuple[dict, dict, dict] | None = None
        while time.monotonic() < deadline:
            endpoint_session_records(session_views(), identities, initial_session_starts)
            session_poll_count += 1
            a_status = status(0)
            alternate_status = status(alternate_index)
            b_status = status(3)
            a_tree = control(0, "show", "tree")
            alternate_tree = control(alternate_index, "show", "tree")
            b_tree = control(3, "show", "tree")
            if (
                a_status.get("peer_count") == 1
                and a_status.get("link_count") == 1
                and alternate_status.get("peer_count") == 2
                and alternate_status.get("link_count") == 2
                and b_status.get("peer_count") == 1
                and b_status.get("link_count") == 1
                and a_tree.get("root") == node_addrs[0]
                and alternate_tree.get("root") == node_addrs[0]
                and b_tree.get("root") == node_addrs[0]
                and b_tree.get("parent") == node_addrs[alternate_index]
                and b_tree.get("depth") == 2
            ):
                post_tree_views = (a_tree, alternate_tree, b_tree)
                break
            time.sleep(SESSION_POLL_INTERVAL_SECS)
        if post_tree_views is None:
            raise QualificationError("timed out waiting for automatic alternate-route reparenting")
        reparent_elapsed_ms = round((time.monotonic() - failure_started) * 1000)
        post_b_tree = post_tree_views[2]
        initial_tree_stats = initial_b_tree.get("stats")
        post_tree_stats = post_b_tree.get("stats")
        if (
            not isinstance(initial_tree_stats, dict)
            or not isinstance(post_tree_stats, dict)
            or post_b_tree.get("declaration_sequence", 0)
            <= initial_b_tree.get("declaration_sequence", 0)
            or post_tree_stats.get("parent_losses", 0)
            <= initial_tree_stats.get("parent_losses", 0)
        ):
            raise QualificationError("B tree telemetry did not record the parent loss")

        phase = "post-failure-data-plane"

        def recovered_route():
            result = _run(
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
                label="post-failure route recovery probe",
                timeout=5,
                check=False,
            )
            return result.returncode == 0

        recovery_timeout = max(
            1.0,
            PAYLOAD_RECOVERY_BUDGET_SECS - (time.monotonic() - failure_started),
        )
        _wait_for(
            recovered_route,
            label="post-failure overlay route and automatic FSP session recovery",
            timeout=recovery_timeout,
            interval=1,
        )
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
            label="post-failure effective-MTU-boundary ICMPv6 probe",
            timeout=20,
        )
        recovered_sessions = endpoint_session_records(session_views(), identities)
        recovered_session_starts = (
            recovered_sessions[0]["session_start_ms"],
            recovered_sessions[1]["session_start_ms"],
        )
        # FIPS v0.5.1 let the established FSP session go dark after route loss
        # and rebuilt it; v0.5.3 re-looks-up the destination and keeps the
        # session. Both are automatic (no manual reset is ever issued). Record
        # which one was observed instead of demanding either; a mixed outcome
        # (one endpoint kept its session, the other did not) is not a known
        # daemon behaviour and fails closed.
        session_start_changed = [
            recovered != initial
            for recovered, initial in zip(
                recovered_session_starts, initial_session_starts
            )
        ]
        if all(session_start_changed):
            session_continuity = "re-established"
        elif not any(session_start_changed):
            session_continuity = "preserved"
        else:
            raise QualificationError(
                "FSP session continuity differed between endpoints after route loss"
            )
        alternate_before = forwarding_counters(
            control(alternate_index, "show", "routing")
        )
        post_payload = run_payload_probe("after-failure", destination)
        alternate_after = forwarding_counters(
            control(alternate_index, "show", "routing")
        )
        alternate_packet_delta = alternate_after[0] - alternate_before[0]
        alternate_byte_delta = alternate_after[1] - alternate_before[1]
        if alternate_packet_delta < 1 or alternate_byte_delta < 1:
            raise QualificationError(
                "alternate transit did not forward the recovered exact payload"
            )
        endpoint_session_records(
            session_views(), identities, recovered_session_starts
        )
        if status(alternate_index).get("session_count") != 0:
            raise QualificationError("surviving transit terminated an end-to-end FSP session")
        payload_recovery_elapsed_ms = round((time.monotonic() - failure_started) * 1000)
        if not alternate_route_timings_within_contract(
            reparent_elapsed_ms, payload_recovery_elapsed_ms
        ):
            raise QualificationError("alternate-route reconvergence exceeded its timing budget")

        observations = {
            "underlay_exclusion": {
                "transit_ipv4_forwarding_disabled": [True, True],
                "endpoint_direct_ipv4_probe_blocked": True,
                "direct_endpoint_underlay_link_absent": True,
            },
            "nodes": nodes,
            "initial_topology": {
                "configured_auto_connect_peers": 4,
                "manual_connect_commands": 0,
                "authenticated_peer_counts": [2, 2, 2, 2],
                "authenticated_link_counts": [2, 2, 2, 2],
                "root_role": "a",
                "tree_depths": [0, 1, 1, 2],
                "endpoint_b_parent_role": ROLE_NAMES[active_index],
                "alternate_transit_authenticated": True,
                "alternate_path_one_way_delay_ms": ALTERNATE_PATH_ONE_WAY_DELAY_MS,
                "full_mmp_link_views": 8,
                "transport": "udp",
            },
            "identity_resolution": {
                "mechanism": "local-fips-dns-npub",
                "endpoint_remote_identities_registered": True,
                "public_discovery_used": False,
            },
            "initial_payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0-multihop",
                "records": initial_payload,
                "all_exact_echo": True,
            },
            "initial_path_selection": {
                "active_transit": ROLE_NAMES[active_index],
                "alternate_transit": ROLE_NAMES[alternate_index],
                "endpoint_b_parent_was_active_transit": True,
                "active_forwarded_packets_delta": packet_deltas[active_index - 1],
                "active_forwarded_bytes_delta": byte_deltas[active_index - 1],
                "alternate_forwarded_packets_delta": packet_deltas[alternate_index - 1],
                "alternate_forwarded_bytes_delta": byte_deltas[alternate_index - 1],
                "transit_fsp_session_counts": [0, 0],
            },
            "failure_injection": {
                "failed_role": ROLE_NAMES[active_index],
                "signal": "SIGKILL",
                "graceful_disconnect_sent": False,
                "process_exit_observed": True,
                "underlay_interfaces_left_up": True,
                "outage_probe_blocked": True,
            },
            "automatic_reparenting": {
                "tick_interval_secs": TICK_INTERVAL_SECS,
                "heartbeat_interval_secs": HEARTBEAT_INTERVAL_SECS,
                "link_dead_timeout_secs": LINK_DEAD_TIMEOUT_SECS,
                "reparent_budget_secs": REPARENT_BUDGET_SECS,
                "reparent_elapsed_ms": reparent_elapsed_ms,
                "old_parent_role": ROLE_NAMES[active_index],
                "new_parent_role": ROLE_NAMES[alternate_index],
                "root_unchanged": True,
                "tree_depth_unchanged": True,
                "declaration_sequence_increased": True,
                "parent_loss_counter_increased": True,
                "manual_route_or_connect_commands": 0,
                "remaining_peer_counts": {"a": 1, "alternate": 2, "b": 1},
                "remaining_link_counts": {"a": 1, "alternate": 2, "b": 1},
            },
            "fsp_session_recovery": {
                "target_control_poll_interval_ms": round(
                    SESSION_POLL_INTERVAL_SECS * 1000
                ),
                "control_poll_count": session_poll_count,
                "established_through_reparent_control_polls": True,
                "original_session_start_unchanged_through_reparent": [True, True],
                "idle_timeout_secs": SESSION_IDLE_TIMEOUT_SECS,
                "manual_session_reset_commands": 0,
                "session_continuity": session_continuity,
                "automatic_session_reestablishment_observed": (
                    session_continuity == "re-established"
                ),
                "session_start_changed_per_endpoint": session_start_changed,
                "endpoint_session_counts_after_recovery": [
                    len(control(0, "show", "sessions")["sessions"]),
                    len(control(3, "show", "sessions")["sessions"]),
                ],
                "alternate_transit_fsp_session_count": 0,
                "identity_values_retained": False,
            },
            "post_failure_icmpv6": {
                "effective_mtu_boundary_payload_bytes": 1155,
                "echo_requests": 2,
                "passed": True,
            },
            "post_failure_payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0-multihop",
                "records": post_payload,
                "all_exact_echo": True,
            },
            "post_failure_path": {
                "forwarding_transit": ROLE_NAMES[alternate_index],
                "forwarded_packets_delta": alternate_packet_delta,
                "forwarded_bytes_delta": alternate_byte_delta,
                "failed_transit_unavailable": True,
                "payload_recovery_budget_secs": PAYLOAD_RECOVERY_BUDGET_SECS,
                "payload_recovery_elapsed_ms": payload_recovery_elapsed_ms,
            },
        }
    except Exception as exc:
        error = exc
        if phase in {"diamond-convergence", "initial-data-plane"}:
            capture_diamond_snapshot(phase, force=True)
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
    diagnostic_path = output.with_name(output.stem + "-diagnostics.json")
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    with diagnostic_path.open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "schema_version": 1,
                "evidence_type": "fips-g2-diamond-diagnostics",
                "run_id": run_id,
                "project_revision": project_revision,
                "fips_commit": provenance["fips_commit"],
                "status": "failed" if error is not None else "passed",
                "last_phase": phase_at_failure if error is not None else phase,
                "sample_interval_ms": DIAGNOSTIC_INTERVAL_NS // 1_000_000,
                "sample_limit": MAX_DIAGNOSTIC_SAMPLES,
                "samples": list(diagnostic_samples),
            },
            stream, indent=2, sort_keys=True,
        )
        stream.write("\n")
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
            f"G2 alternate-route qualification failed during {phase_at_failure}"
        ) from error

    result = {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-alternate-route",
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
            "node_count": 4,
            "namespace_count": 4,
            "authenticated_link_count": 4,
            "isolation": "linux-network-namespaces",
            "underlay": "four-segment-diamond-ipv4-udp",
            "path_role": "redundant-managed-fips-transit",
            "public_discovery": False,
            "nostr_relay": False,
            "tun_name": "fips0",
            "configured_tun_mtu": TUN_MTU,
            "configured_udp_mtu": TUN_MTU,
            "identity_storage": "temporary-config-adjacent-key-files",
            "root_assignment": "lowest-derived-node-address-to-endpoint-a",
            "path_cost_bias": "r2-b-20ms-one-way-netem-delay",
        },
        "observations": observations,
        "cleanup": cleanup,
        "limitations": [
            "This run qualifies one four-node Linux UDP diamond on the pinned host architecture only.",
            "Tree reparenting is automatic but not hitless: the stale FSP session recovers through the configured 90-second idle timeout and automatic re-discovery.",
            "It does not qualify NAT rebinding, public discovery, Nostr relays, heterogeneous PMTUD, or impaired links.",
            "It is FIPS G2 evidence, not SRT media-continuity or G6 evidence.",
        ],
    }
    _write_result(output, result)
    return result
