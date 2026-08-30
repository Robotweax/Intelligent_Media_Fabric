from __future__ import annotations

import argparse
import json
import os
import re
import socket
import time
from pathlib import Path


INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def parse_packet_too_big(packet: bytes) -> dict | None:
    offset = 0
    if len(packet) >= 48 and packet[0] >> 4 == 6:
        if packet[6] != socket.IPPROTO_ICMPV6:
            return None
        offset = 40
    if len(packet) < offset + 8:
        return None
    if packet[offset] != 2 or packet[offset + 1] != 0:
        return None
    return {
        "icmpv6_type": 2,
        "icmpv6_code": 0,
        "reported_mtu": int.from_bytes(packet[offset + 4 : offset + 8], "big"),
    }


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def observe(interface: str, ready: Path, output: Path, timeout: float) -> int:
    if not INTERFACE_RE.fullmatch(interface):
        raise ValueError("interface name is invalid")
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET6, socket.SOCK_RAW, socket.IPPROTO_ICMPV6) as sock:
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_BINDTODEVICE,
            interface.encode("ascii") + b"\0",
        )
        sock.settimeout(min(timeout, 1.0))
        ready.write_text("ready\n", encoding="ascii")
        while time.monotonic() < deadline:
            try:
                packet, _ = sock.recvfrom(65535)
            except TimeoutError:
                continue
            observation = parse_packet_too_big(packet)
            if observation is not None:
                _atomic_json(output, {"status": "passed", **observation})
                return 0
    raise TimeoutError("timed out waiting for ICMPv6 Packet Too Big")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded ICMPv6 Packet Too Big observer")
    parser.add_argument("--interface", required=True)
    parser.add_argument("--ready", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 0 < args.timeout <= 30:
        raise SystemExit("timeout must be greater than zero and no more than 30 seconds")
    return observe(args.interface, args.ready, args.output, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
