from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
from pathlib import Path


def deterministic_payload(size: int) -> bytes:
    if size < 1 or size > 65507:
        raise ValueError("payload size must be between 1 and 65507")
    seed = hashlib.sha256(f"rimf-g2-payload:{size}".encode("ascii")).digest()
    return (seed * ((size + len(seed) - 1) // len(seed)))[:size]


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _ipv6(value: str) -> str:
    return str(ipaddress.IPv6Address(value))


def run_server(bind: str, port: int, count: int, ready: Path, output: Path) -> int:
    address = _ipv6(bind)
    records: list[dict] = []
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
        sock.settimeout(30)
        sock.bind((address, port))
        ready.write_text("ready\n", encoding="ascii")
        for _ in range(count):
            payload, peer = sock.recvfrom(65535)
            sock.sendto(payload, peer)
            records.append(
                {
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    _atomic_json(output, {"status": "passed", "records": records})
    return 0


def run_client(destination: str, port: int, sizes: list[int], output: Path) -> int:
    address = _ipv6(destination)
    records: list[dict] = []
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
        sock.settimeout(30)
        for size in sizes:
            sent = deterministic_payload(size)
            sock.sendto(sent, (address, port))
            received, _ = sock.recvfrom(size + 1)
            if received != sent:
                raise RuntimeError(f"payload mismatch for {size} bytes")
            records.append(
                {
                    "bytes": size,
                    "sha256": hashlib.sha256(sent).hexdigest(),
                    "exact_echo": True,
                }
            )
    _atomic_json(output, {"status": "passed", "records": records})
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded IPv6 UDP payload identity probe")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    server = subparsers.add_parser("server")
    server.add_argument("--bind", required=True)
    server.add_argument("--port", required=True, type=int)
    server.add_argument("--count", required=True, type=int)
    server.add_argument("--ready", required=True, type=Path)
    server.add_argument("--output", required=True, type=Path)

    client = subparsers.add_parser("client")
    client.add_argument("--destination", required=True)
    client.add_argument("--port", required=True, type=int)
    client.add_argument("--sizes", required=True, nargs="+", type=int)
    client.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    if args.mode == "server":
        if args.count < 1 or args.count > 100:
            raise SystemExit("count must be between 1 and 100")
        return run_server(args.bind, args.port, args.count, args.ready, args.output)
    return run_client(args.destination, args.port, args.sizes, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
