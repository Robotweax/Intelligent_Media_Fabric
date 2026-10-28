"""Paced MPEG-TS source and independent downstream collector for faulted experiments.

The source sends a constant-bitrate fixture as fixed 1316-byte UDP datagrams on an
absolute schedule, so datagram i leaves at start + i * interval. The collector is a
separate process from both SRT peers: it binds a UDP port, appends every datagram it
receives to one file, and records arrival times as a bounded summary (counts, first
and last arrival, and the inter-arrival gaps above a threshold). Neither component
inspects or repairs the media; decoding happens afterwards in another process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any

DATAGRAM_BYTES = 1316
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_GAPS = 64
GAP_THRESHOLD_NS = 250_000_000
RECEIVE_BUFFER_BYTES = 4 * 1024 * 1024


def _endpoint(text: str) -> tuple[str, int]:
    host, separator, port = text.rpartition(":")
    if not separator or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"invalid endpoint {text!r}")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host, int(port)


def _family(host: str) -> int:
    return socket.AF_INET6 if ":" in host else socket.AF_INET


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, allow_nan=False, indent=2, sort_keys=True)
        stream.write("\n")


def _datagrams(data: bytes) -> list[bytes]:
    return [data[offset : offset + DATAGRAM_BYTES] for offset in range(0, len(data), DATAGRAM_BYTES)]


def datagram_interval_ns(rate_bps: int) -> int:
    if not isinstance(rate_bps, int) or not 100_000 <= rate_bps <= 50_000_000:
        raise ValueError("source rate must be between 100 kbit/s and 50 Mbit/s")
    return round(DATAGRAM_BYTES * 8 * 1_000_000_000 / rate_bps)


def run_source(fixture: Path, destination: str, rate_bps: int, output: Path) -> dict[str, Any]:
    """Send the fixture once, datagram i at start + i * interval, and summarize."""
    data = fixture.read_bytes()
    if not data or len(data) > MAX_STREAM_BYTES:
        raise ValueError("fixture is empty or exceeds the stream byte limit")
    datagrams = _datagrams(data)
    interval = datagram_interval_ns(rate_bps)
    host, port = _endpoint(destination)
    sender = socket.socket(_family(host), socket.SOCK_DGRAM)
    max_lateness = 0
    try:
        start = time.monotonic_ns()
        for index, datagram in enumerate(datagrams):
            target = start + index * interval
            remaining = target - time.monotonic_ns()
            if remaining > 0:
                time.sleep(remaining / 1_000_000_000)
            max_lateness = max(max_lateness, time.monotonic_ns() - target)
            sender.sendto(datagram, (host, port))
        finished = time.monotonic_ns()
    finally:
        sender.close()
    summary = {
        "schema_version": 1,
        "component": "media-source",
        "fixture_sha256": hashlib.sha256(data).hexdigest(),
        "fixture_bytes": len(data),
        "datagram_bytes": DATAGRAM_BYTES,
        "datagrams": len(datagrams),
        "rate_bps": rate_bps,
        "interval_ns": interval,
        "start_monotonic_ns": start,
        "finish_monotonic_ns": finished,
        "max_lateness_ns": max_lateness,
    }
    _write_exclusive(output, summary)
    return summary


class _Stop:
    requested = False


def run_collector(bind: str, stream_path: Path, output: Path, ready: Path) -> dict[str, Any]:
    """Append every received datagram to one file until SIGTERM or SIGINT."""
    host, port = _endpoint(bind)
    receiver = socket.socket(_family(host), socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECEIVE_BUFFER_BYTES)
    receiver.bind((host, port))
    receiver.settimeout(0.2)

    def stop(_signal: int, _frame: object) -> None:
        _Stop.requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    digest = hashlib.sha256()
    datagrams = 0
    total = 0
    oversize = 0
    first = last = 0
    gaps: list[dict[str, int]] = []
    gaps_truncated = 0
    longest_gap = 0
    with stream_path.open("xb") as stream:
        ready.write_text("ready\n", encoding="utf-8")
        while not _Stop.requested:
            try:
                datagram = receiver.recv(65_535)
            except socket.timeout:
                continue
            except InterruptedError:
                continue
            now = time.monotonic_ns()
            if len(datagram) > DATAGRAM_BYTES:
                oversize += 1
                continue
            if total + len(datagram) > MAX_STREAM_BYTES:
                raise ValueError("collected stream exceeds the byte limit")
            if datagrams:
                gap = now - last
                longest_gap = max(longest_gap, gap)
                if gap >= GAP_THRESHOLD_NS:
                    if len(gaps) < MAX_GAPS:
                        gaps.append({"after_datagram": datagrams, "start_ns": last, "end_ns": now})
                    else:
                        gaps_truncated += 1
            else:
                first = now
            last = now
            datagrams += 1
            total += len(datagram)
            digest.update(datagram)
            stream.write(datagram)
    receiver.close()
    summary = {
        "schema_version": 1,
        "component": "media-collector",
        "datagrams": datagrams,
        "bytes": total,
        "oversize_datagrams": oversize,
        "stream_sha256": digest.hexdigest(),
        "first_arrival_monotonic_ns": first if datagrams else None,
        "last_arrival_monotonic_ns": last if datagrams else None,
        "gap_threshold_ns": GAP_THRESHOLD_NS,
        "longest_gap_ns": longest_gap,
        "gaps": gaps,
        "gaps_truncated": gaps_truncated,
    }
    _write_exclusive(output, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rimf_lab.media_stream")
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source")
    source.add_argument("--fixture", type=Path, required=True)
    source.add_argument("--destination", required=True)
    source.add_argument("--rate-bps", type=int, required=True)
    source.add_argument("--output", type=Path, required=True)
    collector = commands.add_parser("collect")
    collector.add_argument("--bind", required=True)
    collector.add_argument("--stream", type=Path, required=True)
    collector.add_argument("--output", type=Path, required=True)
    collector.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "source":
            run_source(args.fixture, args.destination, args.rate_bps, args.output)
        else:
            run_collector(args.bind, args.stream, args.output, args.ready)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
