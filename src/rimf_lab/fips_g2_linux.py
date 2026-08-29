from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


FIPS_REPOSITORY = "https://github.com/jmcorgan/fips.git"
EXPECTED_FIPS_COMMIT = "487fa86f65794071e3b91313c298d4f09b98b7fe"
EXPECTED_CARGO_LOCK_SHA256 = "6a3016555299ec8895cd52d10e34b051f6d7ed2e32813f4585786bb61d4dbc83"
EXPECTED_RUST_TOOLCHAIN_SHA256 = "6a95738ee0eea5867a071922541a1ccaac80c63ccba5c947eb78b6130e1b22d3"
TUN_MTU = 1280
EFFECTIVE_IPV6_MTU = 1203
UDP_PAYLOAD_SIZES = (1, 1024, 1155)
UDP_PROBE_PORT = 42042
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IDENTITY_RE = re.compile(r"\b(?:npub|nsec)1[0-9a-z]+\b")


class QualificationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_config(control_socket: Path, bind_address: str) -> str:
    return f"""node:
  identity:
    persistent: false
  control:
    enabled: true
    socket_path: "{control_socket}"
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

peers: []
"""


def valid_connect_acknowledgement(result: dict, peer: str, address: str) -> bool:
    return (
        result.get("npub") == peer
        and result.get("address") == address
        and result.get("transport") == "udp"
    )


def _run(
    command: list[str],
    *,
    label: str,
    timeout: float = 30,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(f"{label} could not complete") from exc
    if check and result.returncode != 0:
        raise QualificationError(f"{label} failed with exit code {result.returncode}")
    return result


def _json_command(command: list[str], *, label: str, timeout: float = 30) -> dict:
    result = _run(command, label=label, timeout=timeout)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label} did not return a JSON object")
    return value


def _json_value_command(command: list[str], *, label: str, timeout: float = 30):
    result = _run(command, label=label, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"{label} returned invalid JSON") from exc


def _wait_for(
    predicate: Callable[[], object | None],
    *,
    label: str,
    timeout: float = 30,
    interval: float = 0.25,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise QualificationError(f"timed out waiting for {label}")


def _validate_executable(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise QualificationError(f"{label} is not an executable file")
    return resolved


def _source_provenance(source: Path) -> dict:
    source = source.resolve()
    if not source.is_dir():
        raise QualificationError("FIPS source directory does not exist")
    revision = _run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        label="FIPS source revision",
    ).stdout.strip()
    if revision != EXPECTED_FIPS_COMMIT:
        raise QualificationError("FIPS source revision does not match the Phase 1 baseline")
    tree_state = _run(
        ["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=no"],
        label="FIPS source tree state",
    ).stdout.strip()
    if tree_state:
        raise QualificationError("FIPS tracked source tree is dirty")
    cargo_lock = sha256_file(source / "Cargo.lock")
    rust_toolchain = sha256_file(source / "rust-toolchain.toml")
    if cargo_lock != EXPECTED_CARGO_LOCK_SHA256:
        raise QualificationError("FIPS Cargo.lock digest does not match the baseline")
    if rust_toolchain != EXPECTED_RUST_TOOLCHAIN_SHA256:
        raise QualificationError("FIPS rust-toolchain digest does not match the baseline")
    return {
        "fips_repository": FIPS_REPOSITORY,
        "fips_commit": revision,
        "fips_source_tree_state": "clean",
        "cargo_lock_sha256": cargo_lock,
        "rust_toolchain_sha256": rust_toolchain,
    }


def _stop_process(process: subprocess.Popen | None) -> bool:
    if process is None:
        return True
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=8)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    return False
    return process.poll() is not None


def _print_redacted_log_tails(paths: tuple[Path, ...]) -> None:
    for index, path in enumerate(paths):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        except OSError:
            continue
        if not lines:
            continue
        print(f"redacted FIPS node-{index + 1} log tail:", file=sys.stderr)
        for line in lines:
            print(IDENTITY_RE.sub("<redacted-identity>", line), file=sys.stderr)


def _safe_failure_result(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    phase: str,
    project_revision: str,
    cleanup: dict,
) -> dict:
    return {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-direct",
        "run_id": run_id,
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G2"],
        "started_at": started_at,
        "finished_at": finished_at,
        "project_revision": project_revision,
        "failure_phase": phase,
        "cleanup": cleanup,
    }


def _write_result(output: Path, result: dict) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(output)


def run_fips_g2_linux_direct(
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
        raise QualificationError("the G2 direct runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the G2 direct runner requires root")
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

    suffix = str(os.getpid())
    namespaces = (f"rimfg2a{suffix}", f"rimfg2b{suffix}")
    veths = (f"g2a{suffix}", f"g2b{suffix}")
    if any(len(name) > 15 for name in (*namespaces, *veths)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")

    work = Path(tempfile.mkdtemp(prefix="rimf-g2-", dir="/tmp"))
    node_dirs = (work / "node-a", work / "node-b")
    sockets = (node_dirs[0] / "control.sock", node_dirs[1] / "control.sock")
    underlay_addresses = ("10.203.0.1", "10.203.0.2")
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
        for config, socket_path, address in zip(configs, sockets, underlay_addresses):
            config.write_text(render_config(socket_path, address), encoding="utf-8")
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

        def status(index: int) -> dict:
            return _json_command(
                [str(fipsctl_binary), "-s", str(sockets[index]), "show", "status"],
                label=f"node {index} status",
            )

        statuses = [status(0), status(1)]
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
                    "node": "a" if index == 0 else "b",
                    "tun_state": "active",
                    "tun_name": "fips0",
                    "kernel_tun_mtu": kernel_mtu,
                    "effective_ipv6_mtu": node_status["effective_ipv6_mtu"],
                }
            )

        peer_b = statuses[1].get("npub")
        if not isinstance(peer_b, str) or not peer_b.startswith("npub1"):
            raise QualificationError("node B did not expose a valid public identity")

        phase = "connect-acknowledgement"
        connect_result = _json_command(
            [
                str(fipsctl_binary),
                "-s",
                str(sockets[0]),
                "connect",
                peer_b,
                f"{underlay_addresses[1]}:2121",
                "udp",
            ],
            label="connect node A to node B",
        )
        if not valid_connect_acknowledgement(
            connect_result, peer_b, f"{underlay_addresses[1]}:2121"
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
            connected_statuses, label="authenticated two-node link", timeout=30
        )

        phase = "mesh-size-convergence"

        def converged_mesh_statuses():
            current = [status(0), status(1)]
            if all(item.get("estimated_mesh_size", 0) >= 2 for item in current):
                return current
            return None

        statuses = _wait_for(
            converged_mesh_statuses, label="estimated mesh size of two", timeout=30
        )

        phase = "mmp-observation"

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
            if all(
                isinstance(item, dict)
                and item.get("mode") == "full"
                and isinstance(item.get("srtt_ms"), (int, float))
                for item in measurements
            ):
                return current
            return None

        peer_views = _wait_for(
            measured_peer_views, label="full MMP observations", timeout=30
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
                "32",
                destination,
            ],
            label="small ICMPv6 probe through fips0",
            timeout=20,
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
            label="effective-MTU-boundary ICMPv6 probe through fips0",
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
            [str(fipsctl_binary), "-s", str(sockets[0]), "disconnect", peer_b],
            label="disconnect node A from node B",
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
        cleanup["namespaces_removed"] = all(namespace not in namespace_list for namespace in namespaces)
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
        )
        _write_result(output, result)
        raise QualificationError(f"G2 direct qualification failed during {phase_at_failure}") from error

    result = {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-direct",
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
        },
        "observations": observations,
        "cleanup": cleanup,
        "limitations": [
            "Direct veth underlay only; NAT and relay-assisted connectivity were not exercised.",
            "No loss, delay, reordering, link failure, daemon restart, or route reconvergence was injected.",
            "The payload probe used deterministic UDP datagrams, not an SRT media stream.",
            "This run qualifies Linux TUN connectivity for the pinned host architecture only.",
        ],
    }
    _write_result(output, result)
    return result
