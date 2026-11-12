"""G4 faulted-diamond experiment: one SRT media stream through an automatic FIPS failover.

Four namespaces form the retained G2 alternate-route diamond (a-r1-b / a-r2-b, no a-b
underlay). A deterministic constant-bitrate MPEG-TS fixture is paced into the SRT
Telemetry incident peer on `a`, carried over `fips0` to the peer on `b`, and handed to
an independent collector process; the collected stream is decoded afterwards by a
separate FFmpeg process and compared frame by frame with the fixture. The coordinator
samples SRT on both endpoints and FIPS control state on one shared monotonic clock,
kills the observed active transit with SIGKILL (or, as a predeclared variant, blackholes
both of its links while its daemon keeps running), and marks route epoch 2 only when a
FIPS observation proves that `b` reparented to the other authenticated transit.

The result is ordering-only. It records when each layer's observed state changed, as
intervals at its own sampling resolution, and never claims a first divergent layer,
a cause, or a gate passage.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import queue
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from .contracts import (
    COMMIT_RE,
    ContractError,
    load_json,
    validate_correlation_envelope,
    validate_srt_telemetry_observation,
)
from .fips_g2_linux import (
    EFFECTIVE_IPV6_MTU,
    EXPECTED_FIPS_COMMIT,
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
    sha256_file,
    utc_now,
)
from .fips_g2_linux_alternate_route import (
    ALTERNATE_PATH_ONE_WAY_DELAY_MS,
    HEARTBEAT_INTERVAL_SECS,
    LINK_DEAD_TIMEOUT_SECS,
    TICK_INTERVAL_SECS,
    NODE_ADDR_RE,
    NODE_ADDRESSES,
    REPARENT_BUDGET_SECS,
    ROLE_NAMES,
    _hard_kill_process,
    diamond_peer_relationships,
    diamond_tree_relationships,
    node_addr_from_npub,
    render_alternate_route_config,
)
from .fips_g2_linux_managed_transit import forwarding_counters
from .g4_srt_over_fips import (
    EXPECTED_SRT_COMMIT,
    EXPECTED_SRT_VERSION,
    EXPECTED_TELEMETRY_COMMIT,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
    _Peer,
    _clock,
    _clock_domain,
    _file_record,
    _parse_prefixed_json,
    _peer_command,
    _read_jsonl,
    _rfc3339_nano,
    _sample_pair,
    _source_revision,
    _write_json,
    _write_jsonl,
)
from .media_frames import assess_media_frames
from .media_stream import GAP_THRESHOLD_NS, TS_PACKET_BYTES, datagram_interval_ns
from .srt_adapter import adapt_srt_telemetry_jsonl

EVIDENCE_TYPE = "g4-faulted-diamond"
DEVICE_ID = "four-node-faulted-diamond"
EVENT_NAMESPACE = uuid.UUID("2d6c1f0e-8a4b-5f3e-9c7d-1b0a2e3f4c5d")
SENDER_EVENT_NAMESPACE = "a1e2d3c4-b5a6-5978-8b9a-0c1d2e3f4a5b"
RECEIVER_EVENT_NAMESPACE = "b2f3e4d5-c6b7-5a89-9cab-1d2e3f4a5b6c"

# Retained faulted-diamond bundles are evidence only for their own recorded revisions.
# A bundle whose result manifest matches a digest recorded here is validated against
# that entry's pins; every other result must carry the active pins, so a new run
# cannot present an old pin as current. See ADR-0010.
_PINS_2026_10_28 = {
    "srt_commit": "57fcf51a31ec2eecf4189d63c2f998ff1e8daaa1",
    "srt_version": "0.3.1",
    "telemetry_commit": "1b12f8d7d75658cb7b7e00a0575fc77d965dbbec",
    "fips_commit": "f4a5b4a8e61e340e6be7551608109a5c399f8353",
}
HISTORICAL_G4_FAULTED_DIAMOND_BUNDLES = {
    # 2026-10-28, run 40743995191: first faulted-diamond run (SRT v0.3.1, Telemetry 1b12f8d7, FIPS v0.5.3).
    "dfc3d7b69bdc3adb6db219ffca7a7a47e8aaead5861e242676b22c1ac36abdf1": _PINS_2026_10_28,
    # 2026-10-28, run 40748574042: repeat (SRT v0.3.1, Telemetry 1b12f8d7, FIPS v0.5.3).
    "0b290b2462f0ef2634304b07a590c9ee0fb3363e80005b292b11186329786019": _PINS_2026_10_28,
    # 2026-10-30, run 41022516133: fast-FIPS-detection variant (SRT v0.3.1, Telemetry 1b12f8d7, FIPS v0.5.3).
    "80474d3cc8456e8a0a8572b2b9227da4c944d7310ec10b30877c18f1b5ab7c13": _PINS_2026_10_28,
    # 2026-10-30, run 41022516133: same-revision baseline of the variant (SRT v0.3.1, Telemetry 1b12f8d7, FIPS v0.5.3).
    "e51fbf6733cb27b618436a319e41f710e6da6b6f62c23f4ea30f0c352d3bcb43": _PINS_2026_10_28,
}

# Predeclared experiment profile (docs/qualification/g4-faulted-diamond-experiment-plan).
EXPECTED_FFMPEG_VERSION = "ffmpeg version 6.1.1-3ubuntu5"
FIXTURE_SECONDS = 160
FIXTURE_FPS = 25
FIXTURE_FRAMES = FIXTURE_SECONDS * FIXTURE_FPS
FIXTURE_FILTER = f"testsrc2=size=320x180:rate={FIXTURE_FPS}:duration={FIXTURE_SECONDS}"
FIXTURE_ENCODE = (
    "-c:v", "mpeg2video", "-g", "25", "-bf", "0",
    "-b:v", "600k", "-maxrate", "600k", "-minrate", "600k", "-bufsize", "600k",
    "-flags", "+bitexact", "-fflags", "+bitexact", "-threads", "1", "-pix_fmt", "yuv420p",
    "-f", "mpegts", "-muxrate", "1000000", "-pcr_period", "20",
)
SOURCE_RATE_BPS = 1_000_000
# Packet budget over fips0 (docs/protocols/srt-over-fips-profile-v0.md): the inner IPv6
# MTU FIPS reports, minus IPv6 (40), UDP (8) and SRT (16) headers, bounds the clear SRT
# payload. Six TS packets fit the documented 1139-byte budget; seven (1316) do not.
SRT_IPV6_UDP_HEADER_BYTES = 64
DATAGRAM_BYTES = 6 * TS_PACKET_BYTES
INJECT_AFTER_SOURCE_START_NS = 20_000_000_000
SRT_SAMPLE_INTERVAL_NS = 500_000_000
FIPS_OBSERVATION_EVERY = 2
# Predeclared SRT peer-idle profiles. "extended" (60 s) is the frozen profile of every run
# retained through 2026-11-12; it lets one session span the measured outage. "default"
# (5 s, SRT's default) was predeclared on 2026-11-12: under it a session that ends during
# the outage is an observed outcome, not a failed run.
SRT_PEER_IDLE_PROFILES: dict[str, int] = {"extended": 60_000, "default": 5_000}
DEFAULT_SRT_PEER_IDLE_PROFILE = "extended"
SRT_PEER_IDLE_TIMEOUT_MS = SRT_PEER_IDLE_PROFILES[DEFAULT_SRT_PEER_IDLE_PROFILE]
# Predeclared SRT reconnect policies (2026-11-12). "none" is every earlier run: an ended
# session ends media. Under "coordinator-restart" the coordinator stands in for a
# reconnecting application: when the sender's sent counter stops after the fault and the
# sender confirms an ended session, it starts a second listener and caller. The incident
# peer itself does not reconnect.
SRT_RECONNECT_POLICIES = ("none", "coordinator-restart")
DEFAULT_SRT_RECONNECT_POLICY = "none"
SRT_RECONNECT_MAX_ATTEMPTS = 12
RECONNECT_POLL_NS = 10_000_000
SENDER_EVENT_NAMESPACE_2 = "c3a4f5e6-d7c8-5b9a-8dbc-2e3f4a5b6c7d"
RECEIVER_EVENT_NAMESPACE_2 = "d4b5a6f7-e8d9-5cab-9ecd-3f4a5b6c7d8e"
SRT_RECEIVE_TIMEOUT_MS = 500
SRT_RECOVERY_BUDGET_NS = 120_000_000_000
POST_RECOVERY_MINIMUM_NS = 10_000_000_000
DRAIN_NS = 2_000_000_000
RECORDER_CAPACITY = 512
MAX_SAMPLES = 480
SOURCE_PORT = 47010
OUTPUT_PORT = 47011

BUNDLE_FILES = (
    "sender-source.jsonl",
    "receiver-source.jsonl",
    "sender-context.json",
    "receiver-context.json",
    "sender-observations.jsonl",
    "receiver-observations.jsonl",
    "fips-observations.jsonl",
    "fault-events.jsonl",
    "route-epochs.jsonl",
    "media-source.json",
    "media-collector.json",
    "media-relay.json",
    "reference.framehash",
    "observed.framehash",
    "frame-assessment.json",
)
# Present only in a bundle whose run reconnected: the second session's recordings,
# adapter contexts and observations, and the coordinator's reconnect record.
RECONNECT_FILES = (
    "sender-source-2.jsonl",
    "receiver-source-2.jsonl",
    "sender-context-2.json",
    "receiver-context-2.json",
    "sender-observations-2.jsonl",
    "receiver-observations-2.jsonl",
    "srt-reconnect.json",
)
TIMELINE_EVENTS = (
    "media_downstream_stop",
    "srt_receiver_stall",
    "srt_sender_loss_or_drop",
    "fips_link_loss",
)


def _envelope(
    *,
    source: str,
    name: str,
    run_id: str,
    domain_id: str,
    route_epoch: int,
    monotonic_ns: int,
    unix_ns: int,
    payload: dict[str, Any],
    availability: str = "available",
    reason: str | None = None,
) -> dict[str, Any]:
    envelope = {
        "schema_version": 1,
        "event_id": str(uuid.uuid5(EVENT_NAMESPACE, f"{run_id}:{name}")),
        "source": source,
        "observed_at": _rfc3339_nano(unix_ns),
        "monotonic_ns": monotonic_ns,
        "route_epoch": route_epoch,
        "clock": _clock(domain_id),
        "tenant_id": "qualification",
        "device_id": DEVICE_ID,
        "stream_id": run_id,
        "quality": {
            "availability": availability,
            "confidence": 1.0 if availability == "available" else 0.0,
            "reason": reason,
        },
        "payload": payload,
    }
    validate_correlation_envelope(envelope)
    return envelope


def validate_route_epoch_event(event: Any) -> None:
    if not isinstance(event, dict):
        raise ContractError("route epoch event must be an object")
    required = {
        "schema_version", "route_epoch", "observed_at", "monotonic_ns", "reason",
        "previous_path_id", "current_path_id", "confidence",
    }
    if not required <= set(event) or set(event) - (required | {"evidence_event_ids"}):
        raise ContractError("route epoch event fields are invalid")
    if event["schema_version"] != 1:
        raise ContractError("route epoch event schema_version must be 1")
    for field in ("route_epoch", "monotonic_ns"):
        value = event[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < (1 if field == "route_epoch" else 0):
            raise ContractError(f"route epoch event {field} is invalid")
    if event["reason"] not in {"initial", "link-change", "relay-change", "policy-change", "unknown"}:
        raise ContractError("route epoch event reason is invalid")
    for field in ("previous_path_id", "current_path_id"):
        if event[field] is not None and not isinstance(event[field], str):
            raise ContractError(f"route epoch event {field} is invalid")
    confidence = event["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ContractError("route epoch event confidence is invalid")
    evidence = event.get("evidence_event_ids", [])
    if not isinstance(evidence, list) or len(set(evidence)) != len(evidence) or any(
        not isinstance(item, str) for item in evidence
    ):
        raise ContractError("route epoch event evidence_event_ids is invalid")


def _sample_values(observation: dict[str, Any]) -> tuple[int, dict, dict]:
    sample = observation["payload"]["sample"]
    return observation["monotonic_ns"], sample.get("raw", {}), sample.get("delta", {})


def _positive(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _bracket(previous_ns: int | None, observed_ns: int, origin_ns: int) -> list[int | None]:
    lower = None if previous_ns is None else round((previous_ns - origin_ns) / 1_000_000)
    return [lower, round((observed_ns - origin_ns) / 1_000_000)]


def compute_timeline(
    *,
    fault_events: list[dict],
    fips_observations: list[dict],
    route_epochs: list[dict],
    sender: list[dict],
    receiver: list[dict],
    collector: dict,
    relay: dict | None = None,
    reconnect: dict | None = None,
    receiver_second: list[dict] | None = None,
) -> dict[str, Any]:
    """Derive the ordering-only timeline from retained files (runner and validator share it).

    Each change is an interval [lower, upper] in milliseconds relative to the fault
    (the SIGKILL, or the start of the blackhole):
    the change happened after `lower` (the last observation without it) and was
    observed at `upper`. Downstream media stop and resume are point arrivals at the
    collector. Nothing here identifies a cause.

    `relay` is the retained media-relay record. When it reports an ended SRT session,
    the timeline gains `srt_session_end`, and a downstream stop that never resumed is
    taken from the collector's last arrival. A timeline of a surviving session is
    unchanged by it.

    `reconnect` is the coordinator's retained reconnect record and `receiver_second` the
    second session's receiver observations. With them the timeline gains `srt_reconnect`.
    `sender` and `receiver` are always the first session's observations.
    """
    by_kind = {event["payload"]["event"]: event for event in fault_events if event["source"] == "fabric"}
    origin, completed, completed_key = next(
        names for names in FAULT_EVENTS.values() if names[0] in by_kind)
    injection = by_kind[origin]["monotonic_ns"]
    exit_observed = by_kind[completed]["monotonic_ns"]
    marker = next(item for item in route_epochs if item["route_epoch"] == 2)
    evidence = {item["event_id"]: item for item in fips_observations}
    proving = [evidence[event_id] for event_id in marker["evidence_event_ids"] if event_id in evidence]
    proving.sort(key=lambda item: item["monotonic_ns"])

    def first_after(series: list[dict], predicate, start_ns: int) -> tuple[int | None, int | None]:
        previous = None
        for item in series:
            moment = item["monotonic_ns"]
            if moment > start_ns and predicate(item):
                return previous, moment
            previous = moment
        return None, None

    timeline: dict[str, Any] = {
        "origin": origin,
        "units": "ms",
        completed_key: round((exit_observed - injection) / 1_000_000),
        "fips_reparent": _bracket(proving[0]["monotonic_ns"] if len(proving) == 2 else None,
                                  marker["monotonic_ns"], injection),
    }

    link_series = [item for item in fips_observations if item["payload"].get("b_link_count") is not None]
    previous, moment = first_after(link_series, lambda item: item["payload"]["b_link_count"] < 2, injection)
    timeline["fips_link_loss"] = None if moment is None else _bracket(previous, moment, injection)

    def receiver_delta(item: dict) -> Any:
        return _sample_values(item)[2].get("unique_received_packet_delta")

    previous, stall = first_after(receiver, lambda item: receiver_delta(item) == 0, injection)
    timeline["srt_receiver_stall"] = None if stall is None else _bracket(previous, stall, injection)
    resume_previous, resume = (None, None)
    if stall is not None:
        resume_previous, resume = first_after(receiver, lambda item: _positive(receiver_delta(item)), stall)
    timeline["srt_receiver_resume"] = None if resume is None else _bracket(resume_previous, resume, injection)

    def sender_changed(item: dict) -> bool:
        delta = _sample_values(item)[2]
        return any(_positive(delta.get(name)) for name in (
            "sender_drop_packet_delta", "sender_loss_packet_delta", "retransmitted_packet_delta"))

    previous, moment = first_after(sender, sender_changed, injection)
    timeline["srt_sender_loss_or_drop"] = None if moment is None else _bracket(previous, moment, injection)

    # Datagrams already in flight keep arriving briefly after the SIGKILL, so the
    # downstream interruption is the first collector gap that ends after it.
    gap = next(
        (item for item in sorted(collector.get("gaps", []), key=lambda gap: gap["start_ns"])
         if item["end_ns"] > injection),
        None,
    )
    stopped = (relay or {}).get("stopped", {})
    ended = {role: stopped.get(role, {}).get("connectionBroken") is True for role in ("sender", "receiver")}
    if gap is None and any(ended.values()) and isinstance(collector.get("last_arrival_monotonic_ns"), int):
        stop = round((collector["last_arrival_monotonic_ns"] - injection) / 1_000_000)
        timeline["media_downstream_stop"] = [stop, stop]
        timeline["media_downstream_resume"] = None
        timeline["media_downstream_gap_ms"] = None
    elif gap is None:
        timeline["media_downstream_stop"] = None
        timeline["media_downstream_resume"] = None
        timeline["media_downstream_gap_ms"] = None
    else:
        stop = round((gap["start_ns"] - injection) / 1_000_000)
        start = round((gap["end_ns"] - injection) / 1_000_000)
        timeline["media_downstream_stop"] = [stop, stop]
        timeline["media_downstream_resume"] = [start, start]
        timeline["media_downstream_gap_ms"] = start - stop

    observed = [
        (name, timeline[name]) for name in TIMELINE_EVENTS if timeline.get(name) is not None
    ]
    observed.sort(key=lambda item: (item[1][1], item[0]))
    ordering = [{"event": name, "interval": interval} for name, interval in observed]
    resolved = len(observed) >= 2 and all(
        observed[0][1][1] < (later[1][0] if later[1][0] is not None else -10**12)
        for later in observed[1:]
    )
    timeline["divergence_ordering"] = ordering
    timeline["earliest_observed_change"] = observed[0][0] if observed else None
    timeline["ordering_resolved"] = resolved
    if any(ended.values()):
        # The relay stops at the first send or receive that reports the ended session,
        # so each endpoint's last relayed message bounds its session end from below.
        def last_message(role: str) -> int | None:
            moment = stopped.get(role, {}).get("lastMessageMonotonicNano")
            return round((moment - injection) / 1_000_000) if _positive(moment) else None
        timeline["srt_session_end"] = {
            "sender_ended": ended["sender"], "receiver_ended": ended["receiver"],
            "sender_last_relayed_message": last_message("sender"),
            "receiver_last_relayed_message": last_message("receiver"),
        }
    if reconnect is not None:
        def at(moment: int | None) -> int | None:
            return None if moment is None else round((moment - injection) / 1_000_000)
        inferred = reconnect["end_inferred"]
        connected = reconnect["connected_monotonic_ns"]
        previous, moment = first_after(
            receiver_second or [], lambda item: _positive(receiver_delta(item)), connected)
        last_relayed = stopped.get("sender", {}).get("lastMessageMonotonicNano")
        confirmed = at(reconnect["end_confirmed_monotonic_ns"])
        timeline["srt_reconnect"] = {
            "end_inferred": _bracket(inferred["previous_sample_monotonic_ns"],
                                     inferred["sample_monotonic_ns"], injection),
            "end_confirmed": confirmed,
            # Time the coordinator added between the sender's last relayed message and
            # its confirmation of the ended session; an application sees the end at once.
            "detection_delay_ms": confirmed - at(last_relayed) if _positive(last_relayed) else None,
            "attempts": [{"started": at(item["started_monotonic_ns"]),
                          "ended": at(item["ended_monotonic_ns"]), "outcome": item["outcome"]}
                         for item in reconnect["attempts"]],
            "connected": at(connected),
            "media_restarted": at(reconnect["media_restarted_monotonic_ns"]),
            "second_session_first_delivery": None if moment is None else _bracket(previous, moment, injection),
        }
    timeline["causal_claim"] = None
    return timeline


def retimed_frame_count(reference: Path, observed: Path) -> int:
    """Count observed frames whose content is a reference frame at another timestamp.

    A non-zero count means the downstream decode re-timed frames, so a per-timestamp
    comparison would misattribute missing and changed frames; the run fails closed.
    """
    from .media_frames import parse_framehash

    _, expected = parse_framehash(reference)
    _, actual = parse_framehash(observed)
    by_hash: dict[str, set[int]] = {}
    for pts, (_, _, digest) in expected.items():
        by_hash.setdefault(digest, set()).add(pts)
    return sum(
        1 for pts, (_, _, digest) in actual.items()
        if expected.get(pts, (None, None, None))[2] != digest and by_hash.get(digest, set()) - {pts}
    )


def _ffmpeg_version(ffmpeg: Path) -> str:
    return _run([str(ffmpeg), "-hide_banner", "-version"], label="FFmpeg version").stdout.splitlines()[0]


def _generate_fixture(ffmpeg: Path, output: Path) -> None:
    _run(
        [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", FIXTURE_FILTER, *FIXTURE_ENCODE, str(output)],
        label="deterministic media fixture",
        timeout=300,
    )


# FFmpeg's MPEG-TS input treats a timestamp jump beyond dts_delta_threshold (default 10 s)
# as a discontinuity and re-bases later timestamps. That closes an outage gap in the
# numbering: post-gap frames compare as "changed" and the missing frames appear at the end.
# The fixture has no real discontinuity, so the correction is disabled for both decodes.
DECODE_OPTIONS = ("-dts_delta_threshold", "1000000")


def _framehash(ffmpeg: Path, media: Path, output: Path, label: str) -> None:
    _run(
        [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", *DECODE_OPTIONS,
         "-i", str(media), "-map", "0:v:0", "-f", "framehash", "-hash", "SHA256", str(output)],
        label=label,
        timeout=300,
    )


def _peer_arguments(role: str, recording: Path, flow_id: str, peer_idle_ms: int) -> list[str]:
    return [
        "--role", role,
        "--peer-idle-timeout-ms", str(peer_idle_ms),
        "--receive-timeout-ms", str(SRT_RECEIVE_TIMEOUT_MS),
        "--message-bytes", str(DATAGRAM_BYTES),
        "--jsonl-output", str(recording),
        "--flow-id", flow_id,
        "--provider-version", EXPECTED_SRT_VERSION,
        "--provider-revision", EXPECTED_SRT_COMMIT,
        "--build-profile", "ubuntu-24.04-release-shared-openssl",
        "--recorder-capacity", str(RECORDER_CAPACITY),
    ]


def _adapter_context(domain_id: str, namespace: str, run_id: str, transition_ns: int) -> dict:
    return {
        "schema_version": 1,
        "event_namespace": namespace,
        "route_epoch": 1,
        "route_epoch_transitions": [{"route_epoch": 2, "from_monotonic_ns": transition_ns}],
        "clock": _clock(domain_id),
        "fabric_identity": {
            "tenant_id": "qualification",
            "device_id": DEVICE_ID,
            "stream_id": run_id,
            "mapping": {
                "tenant_id": "explicit-policy",
                "device_id": "explicit-policy",
                "stream_id": "explicit-policy",
            },
        },
        "source_identifiers_pseudonymous": True,
        "telemetry_revision": EXPECTED_TELEMETRY_COMMIT,
    }


def _failure_result(run_id: str, started_at: str, project_revision: str, phase: str,
                    cleanup: dict, error: Exception) -> dict:
    return {
        "schema_version": 1,
        "evidence_type": EVIDENCE_TYPE,
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G4"],
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "project_revision": project_revision,
        "failure_phase": phase,
        "failure_class": type(error).__name__,
        "failure_detail": IDENTITY_RE.sub("<redacted-identity>", str(error))[:512],
        "cleanup": cleanup,
        "gate_conclusion": {"G4": "not-passed", "reason": "experiment-failed-before-completion"},
    }


# Predeclared FIPS liveness profiles. "g2-alternate-route" is the retained G2 diamond's
# timer set (also FIPS v0.5.3's defaults) and the profile of the first two retained runs,
# whose results predate this field. "fast-detection" was predeclared on 2026-10-30.
FIPS_TIMER_PROFILES: dict[str, dict[str, int]] = {
    "g2-alternate-route": {"tick_interval_secs": TICK_INTERVAL_SECS,
                           "heartbeat_interval_secs": HEARTBEAT_INTERVAL_SECS,
                           "link_dead_timeout_secs": LINK_DEAD_TIMEOUT_SECS},
    "fast-detection": {"tick_interval_secs": 1, "heartbeat_interval_secs": 1, "link_dead_timeout_secs": 3},
}
DEFAULT_FIPS_TIMER_PROFILE = "g2-alternate-route"


def fips_timer_profile(name: str) -> dict[str, Any]:
    if name not in FIPS_TIMER_PROFILES:
        raise QualificationError(f"unknown FIPS timer profile {name!r}")
    return {"name": name, **FIPS_TIMER_PROFILES[name]}


# Fault types. "transit-sigkill" is the fault of every run retained through 2026-11-12:
# SIGKILL of the active transit's FIPS daemon. "transit-blackhole" was predeclared on
# 2026-11-12: netem loss 100% on the four veth ends of the active transit's two links,
# with the daemon left running and every interface up.
FAULT_TYPES = ("transit-sigkill", "transit-blackhole")
DEFAULT_FAULT = "transit-sigkill"
# Fabric fault events that open and close each fault, and the timeline key of the second.
FAULT_EVENTS = {
    "transit-sigkill": ("sigkill-sent", "process-exit-observed", "process_exit_observed"),
    "transit-blackhole": ("blackhole-start", "blackhole-applied", "fault_applied"),
}


def _take_line(peer: _Peer, prefix: str) -> str | None:
    """Return the peer's next `prefix` line if it has already printed one, without waiting."""
    while True:
        try:
            line = peer._stdout.get_nowait()
        except queue.Empty:
            return None
        if line == prefix or line.startswith(prefix + " "):
            return line


def srt_peer_idle_timeout_ms(name: str) -> int:
    if name not in SRT_PEER_IDLE_PROFILES:
        raise QualificationError(f"unknown SRT peer-idle profile {name!r}")
    return SRT_PEER_IDLE_PROFILES[name]


def run_g4_faulted_diamond(
    *,
    fips_source: Path,
    fips_binary: Path,
    fipsctl_binary: Path,
    srt_source: Path,
    srt_library: Path,
    telemetry_source: Path,
    incident_peer: Path,
    library_dir: Path,
    ffmpeg: Path,
    output_dir: Path,
    project_revision: str,
    fips_timers: str = DEFAULT_FIPS_TIMER_PROFILE,
    srt_peer_idle: str = DEFAULT_SRT_PEER_IDLE_PROFILE,
    srt_reconnect: str = DEFAULT_SRT_RECONNECT_POLICY,
    fault: str = DEFAULT_FAULT,
) -> dict[str, Any]:
    timers = fips_timer_profile(fips_timers)
    peer_idle_ms = srt_peer_idle_timeout_ms(srt_peer_idle)
    # Only the default profile may end with a session that did not resume delivery.
    session_end_allowed = srt_peer_idle != DEFAULT_SRT_PEER_IDLE_PROFILE
    if srt_reconnect not in SRT_RECONNECT_POLICIES:
        raise QualificationError(f"unknown SRT reconnect policy {srt_reconnect!r}")
    reconnecting = srt_reconnect != DEFAULT_SRT_RECONNECT_POLICY
    if reconnecting and not session_end_allowed:
        raise QualificationError("the reconnect policy is predeclared only for the default SRT peer-idle profile")
    if fault not in FAULT_TYPES:
        raise QualificationError(f"unknown fault type {fault!r}")
    blackhole = fault != DEFAULT_FAULT
    if blackhole and (session_end_allowed or reconnecting):
        raise QualificationError(
            "the blackhole fault is predeclared only for the extended SRT peer-idle profile without reconnect")
    # Delivery must come back unless an ended session without reconnect is the outcome.
    recovery_required = not session_end_allowed or reconnecting
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    phase = "preflight"
    if platform.system() != "Linux":
        raise QualificationError("the faulted-diamond runner requires Linux")
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise QualificationError("the faulted-diamond runner requires root")
    if not COMMIT_RE.fullmatch(project_revision):
        raise QualificationError("project revision must be a full lowercase Git commit")
    for utility in ("dig", "git", "ip", "ping", "sysctl", "tc"):
        if shutil.which(utility) is None:
            raise QualificationError(f"required utility is unavailable: {utility}")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise QualificationError("faulted-diamond output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    fips_binary = _validate_executable(fips_binary, "fips")
    fipsctl_binary = _validate_executable(fipsctl_binary, "fipsctl")
    incident_peer = _validate_executable(incident_peer, "SRT telemetry incident peer")
    ffmpeg = _validate_executable(ffmpeg, "ffmpeg")
    srt_library = srt_library.resolve()
    library_dir = library_dir.resolve()
    if not srt_library.is_file() or not library_dir.is_dir():
        raise QualificationError("SRT library or runtime library directory is unavailable")
    ffmpeg_version = _ffmpeg_version(ffmpeg)
    if not ffmpeg_version.startswith(EXPECTED_FFMPEG_VERSION + " "):
        raise QualificationError("FFmpeg does not match the pinned decoder version")
    peer_cli = _run(
        ["env", f"LD_LIBRARY_PATH={library_dir}", str(incident_peer), "--help"],
        label="incident peer CLI",
        check=False,
    )
    if "--media-udp-input HOST:PORT" not in peer_cli.stderr or "--peer-idle-timeout-ms" not in peer_cli.stderr:
        raise QualificationError("incident peer does not expose the media relay CLI")
    provenance = _source_provenance(fips_source)
    provenance.update(
        {
            "project_revision": project_revision,
            "srt_repository": SRT_REPOSITORY,
            "srt_commit": _source_revision(srt_source, EXPECTED_SRT_COMMIT, "Robotweax SRT"),
            "srt_library_sha256": sha256_file(srt_library),
            "telemetry_repository": TELEMETRY_REPOSITORY,
            "telemetry_commit": _source_revision(
                telemetry_source, EXPECTED_TELEMETRY_COMMIT, "SRT Telemetry"
            ),
            "incident_peer_sha256": sha256_file(incident_peer),
            "fips_binary_sha256": sha256_file(fips_binary),
            "fipsctl_binary_sha256": sha256_file(fipsctl_binary),
            "ffmpeg_version": ffmpeg_version,
            "ffmpeg_binary_sha256": sha256_file(ffmpeg),
        }
    )
    if provenance["fips_repository"] != FIPS_REPOSITORY:
        raise QualificationError("unexpected FIPS repository provenance")

    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    work = Path(tempfile.mkdtemp(prefix="rimf-g4-diamond-", dir="/tmp"))
    os.chmod(work, 0o755)
    suffix = str(os.getpid())
    namespaces = tuple(f"rg4{name}{suffix}" for name in ROLE_NAMES)
    interfaces = tuple(f"g4{tag}{suffix}" for tag in ("a1", "r1a", "r1b", "b1", "a2", "r2a", "r2b", "b2"))
    if any(len(name) > 15 for name in (*namespaces, *interfaces)):
        raise QualificationError("generated namespace or interface name exceeds Linux limits")
    daemons: list[subprocess.Popen | None] = [None, None, None, None]
    streams: list[Any] = [None, None, None, None]
    daemon_logs: tuple[Path, ...] = ()
    helpers: list[subprocess.Popen] = []
    listener: _Peer | None = None
    caller: _Peer | None = None
    second_peers: list[_Peer] = []
    cleanup = {
        "srt_peers_stopped": False,
        "media_processes_stopped": False,
        "fips_daemons_stopped": False,
        "faulted_daemon_reaped": False,
        "namespaces_removed": False,
        "work_directory_removed": False,
    }
    error: Exception | None = None
    result: dict[str, Any] | None = None
    sender_samples: list[dict] = []
    receiver_samples: list[dict] = []
    second_sender_samples: list[dict] = []
    fips_observations: list[dict] = []
    fault_events: list[dict] = []
    route_epochs: list[dict] = []

    try:
        phase = "media-fixture"
        fixture = work / "fixture.ts"
        _generate_fixture(ffmpeg, fixture)
        fixture.chmod(0o644)
        _framehash(ffmpeg, fixture, staging / "reference.framehash", "reference decode")
        reference_frames = sum(
            1 for line in (staging / "reference.framehash").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )
        if reference_frames != FIXTURE_FRAMES:
            raise QualificationError("reference decode does not hold the predeclared frame count")

        phase = "identity-and-config-setup"
        records = []
        for index in range(4):
            directory = work / f"identity-{index}"
            directory.mkdir(mode=0o700)
            _run([str(fipsctl_binary), "keygen", "--dir", str(directory)], label="generate identity")
            npub = (directory / "fips.pub").read_text(encoding="utf-8").strip()
            records.append((node_addr_from_npub(npub), npub, directory))
        records.sort(key=lambda item: item[0])
        node_addrs = tuple(item[0] for item in records)
        identities = tuple(item[1] for item in records)
        role_dirs = tuple(item[2] for item in records)
        if len(set(node_addrs)) != 4 or not all(NODE_ADDR_RE.fullmatch(item) for item in node_addrs):
            raise QualificationError("temporary identities did not produce unique node addresses")
        if not all(stat.S_IMODE((d / "fips.key").stat().st_mode) == 0o600 for d in role_dirs):
            raise QualificationError("temporary identity file modes are invalid")
        sockets = tuple(d / "control.sock" for d in role_dirs)
        configs = tuple(d / "fips.yaml" for d in role_dirs)
        daemon_logs = tuple(d / "daemon.log" for d in role_dirs)
        peer_specs = (
            [],
            [("endpoint-a", identities[0], NODE_ADDRESSES[0][0])],
            [("endpoint-a", identities[0], NODE_ADDRESSES[0][1])],
            [("transit-r1", identities[1], NODE_ADDRESSES[1][1]),
             ("transit-r2", identities[2], NODE_ADDRESSES[2][1])],
        )
        for index, config in enumerate(configs):
            config.write_text(
                render_alternate_route_config(sockets[index], dns_enabled=index in (0, 3), peers=peer_specs[index],
                                              heartbeat_interval_secs=timers["heartbeat_interval_secs"],
                                              link_dead_timeout_secs=timers["link_dead_timeout_secs"]),
                encoding="utf-8",
            )
            config.chmod(0o600)

        def control(index: int, *arguments: str, timeout: float = 30) -> dict:
            return _json_command(
                [str(fipsctl_binary), "-s", str(sockets[index]), *arguments],
                label=f"node {ROLE_NAMES[index]} {' '.join(arguments)}",
                timeout=timeout,
            )

        def status(index: int) -> dict:
            return control(index, "show", "status")

        phase = "namespace-setup"
        for namespace in namespaces:
            _run(["ip", "netns", "add", namespace], label=f"create namespace {namespace}")
            _run(["ip", "-n", namespace, "link", "set", "lo", "up"], label="bring loopback up")
        links = (
            (interfaces[0], interfaces[1], 0, 1, NODE_ADDRESSES[0][0], NODE_ADDRESSES[1][0]),
            (interfaces[2], interfaces[3], 1, 3, NODE_ADDRESSES[1][1], NODE_ADDRESSES[3][0]),
            (interfaces[4], interfaces[5], 0, 2, NODE_ADDRESSES[0][1], NODE_ADDRESSES[2][0]),
            (interfaces[6], interfaces[7], 2, 3, NODE_ADDRESSES[2][1], NODE_ADDRESSES[3][1]),
        )
        transit_interfaces = {1: (interfaces[1], interfaces[2]), 2: (interfaces[5], interfaces[6])}
        # The four veth ends of a transit's two links as (node, interface, node at the other end):
        # the transit's own two first, then a's end and b's end.
        blackhole_ends = {
            1: ((1, interfaces[1], 0), (1, interfaces[2], 3), (0, interfaces[0], 1), (3, interfaces[3], 1)),
            2: ((2, interfaces[5], 0), (2, interfaces[6], 3), (0, interfaces[4], 2), (3, interfaces[7], 2)),
        }
        delayed_interfaces = {interfaces[6], interfaces[7]}
        for left, right, left_node, right_node, left_address, right_address in links:
            _run(["ip", "link", "add", left, "type", "veth", "peer", "name", right], label="create diamond veth")
            for interface, node, address in ((left, left_node, left_address), (right, right_node, right_address)):
                _run(["ip", "link", "set", interface, "netns", namespaces[node]], label="move diamond interface")
                _run(["ip", "-n", namespaces[node], "addr", "add", f"{address}/30", "dev", interface],
                     label="assign diamond underlay address")
                _run(["ip", "-n", namespaces[node], "link", "set", interface, "up"], label="bring interface up")
        for index in (1, 2):
            _run(["ip", "netns", "exec", namespaces[index], "sysctl", "-q", "-w", "net.ipv4.ip_forward=0"],
                 label=f"disable IPv4 forwarding on {ROLE_NAMES[index]}")
        for index, interface in ((2, interfaces[6]), (3, interfaces[7])):
            _run(["ip", "netns", "exec", namespaces[index], "tc", "qdisc", "add", "dev", interface,
                  "root", "netem", "delay", f"{ALTERNATE_PATH_ONE_WAY_DELAY_MS}ms"],
                 label="apply alternate-path latency stimulus")
        direct = _run(["ip", "netns", "exec", namespaces[0], "ping", "-c", "1", "-W", "1", NODE_ADDRESSES[3][0]],
                      label="direct-underlay exclusion probe", timeout=5, check=False)
        if direct.returncode == 0:
            raise QualificationError("endpoint A unexpectedly reached B over the IPv4 underlay")

        phase = "daemon-start"
        for index, (namespace, config, log) in enumerate(zip(namespaces, configs, daemon_logs)):
            streams[index] = log.open("w", encoding="utf-8")
            daemons[index] = subprocess.Popen(
                ["ip", "netns", "exec", namespace, str(fips_binary), "-c", str(config)],
                stdout=streams[index], stderr=subprocess.STDOUT, text=True, start_new_session=True,
            )

        def controls_ready():
            if any(process is None or process.poll() is not None for process in daemons):
                raise QualificationError("a FIPS daemon exited before control became ready")
            if not all(path.is_socket() for path in sockets):
                return None
            try:
                return [status(index) for index in range(4)]
            except QualificationError:
                return None

        statuses = _wait_for(controls_ready, label="four FIPS control sockets", timeout=30)
        if [item.get("npub") for item in statuses] != list(identities):
            raise QualificationError("daemon identities did not match role-assigned key files")
        endpoint_mtus = [statuses[0].get("effective_ipv6_mtu"), statuses[3].get("effective_ipv6_mtu")]
        packet_budget = {
            "endpoint_effective_ipv6_mtu": endpoint_mtus,
            "srt_ipv6_udp_header_bytes": SRT_IPV6_UDP_HEADER_BYTES,
            "clear_srt_payload_budget_bytes": min(endpoint_mtus) - SRT_IPV6_UDP_HEADER_BYTES
            if all(isinstance(value, int) for value in endpoint_mtus) else None,
            "media_datagram_bytes": DATAGRAM_BYTES,
            "ts_packets_per_datagram": DATAGRAM_BYTES // TS_PACKET_BYTES,
        }
        if (packet_budget["clear_srt_payload_budget_bytes"] is None
                or DATAGRAM_BYTES > packet_budget["clear_srt_payload_budget_bytes"]):
            raise QualificationError("media datagrams do not fit the fips0 clear SRT payload budget")
        for index, node_status in enumerate(statuses):
            if (node_status.get("tun_state") != "active" or node_status.get("tun_name") != "fips0"
                    or node_status.get("effective_ipv6_mtu") != EFFECTIVE_IPV6_MTU):
                raise QualificationError(f"node {ROLE_NAMES[index]} runtime state is invalid")
            link = _json_value_command(["ip", "-n", namespaces[index], "-j", "link", "show", "dev", "fips0"],
                                       label="kernel TUN state")
            if not isinstance(link, list) or len(link) != 1 or link[0].get("mtu") != TUN_MTU:
                raise QualificationError(f"node {ROLE_NAMES[index]} kernel TUN state is invalid")

        phase = "diamond-convergence"

        def converged():
            current = [status(index) for index in range(4)]
            if not all(item.get("peer_count") == 2 and item.get("link_count") == 2 for item in current):
                return None
            if not diamond_peer_relationships([control(i, "show", "peers") for i in range(4)], list(identities)):
                return None
            if not diamond_tree_relationships([control(i, "show", "tree") for i in range(4)], node_addrs):
                return None
            return current

        statuses = _wait_for(converged, label="authenticated diamond and spanning tree", timeout=60)

        phase = "endpoint-identity-resolution"
        destination = str(ipaddress.IPv6Address(statuses[3]["ipv6_addr"]))
        for namespace, remote, expected in ((namespaces[0], identities[3], statuses[3]["ipv6_addr"]),
                                            (namespaces[3], identities[0], statuses[0]["ipv6_addr"])):
            query = _run(["ip", "netns", "exec", namespace, "dig", "@::1", "-p", "5354",
                          f"{remote}.fips", "AAAA", "+short"], label="local FIPS DNS resolution", timeout=10)
            answers = set()
            for line in query.stdout.splitlines():
                try:
                    answers.add(str(ipaddress.IPv6Address(line.strip())))
                except ipaddress.AddressValueError:
                    continue
            if str(ipaddress.IPv6Address(expected)) not in answers:
                raise QualificationError("FIPS DNS did not return the remote overlay address")

        phase = "initial-data-plane"

        def route_ready():
            probe = _run(["ip", "netns", "exec", namespaces[0], "ping", "-6", "-c", "1", "-W", "2",
                          "-s", "32", destination], label="initial overlay probe", timeout=5, check=False)
            return probe.returncode == 0

        _wait_for(route_ready, label="initial overlay route", timeout=45, interval=1)
        active_addr = control(3, "show", "tree").get("parent")
        if active_addr not in node_addrs[1:3]:
            raise QualificationError("endpoint B parent was not a managed transit")
        active_index = node_addrs.index(active_addr)
        alternate_index = 1 if active_index == 2 else 2
        if status(1).get("session_count") != 0 or status(2).get("session_count") != 0:
            raise QualificationError("a managed transit terminated an end-to-end FSP session")

        phase = "srt-connect"
        flow_id = f"g4d-{run_id}"
        sender_source = staging / "sender-source.jsonl"
        receiver_source = staging / "receiver-source.jsonl"
        collector_summary = work / "media-collector.json"
        collector_ready = work / "collector.ready"
        received = work / "received.ts"
        package_root = str(Path(__file__).resolve().parents[1])
        collector = subprocess.Popen(
            ["ip", "netns", "exec", namespaces[3], "env", f"PYTHONPATH={package_root}",
             sys.executable, "-m", "rimf_lab.media_stream", "collect",
             "--bind", f"127.0.0.1:{OUTPUT_PORT}", "--stream", str(received),
             "--output", str(collector_summary), "--ready", str(collector_ready)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        helpers.append(collector)

        def collector_up():
            if collector.poll() is not None:
                raise QualificationError("media collector exited before becoming ready")
            return collector_ready.is_file()

        _wait_for(collector_up, label="independent media collector", timeout=10)
        listener = _Peer(_peer_command(
            namespaces[3], incident_peer, library_dir,
            _peer_arguments("listener", receiver_source, flow_id, peer_idle_ms)
            + ["--bind-address", destination, "--media-udp-output", f"127.0.0.1:{OUTPUT_PORT}"]))
        ready = _parse_prefixed_json(listener.wait_for("READY"), "READY")
        port = ready.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port <= 65_535:
            raise QualificationError("SRT listener returned an invalid port")
        caller = _Peer(_peer_command(
            namespaces[0], incident_peer, library_dir,
            _peer_arguments("caller", sender_source, flow_id, peer_idle_ms)
            + ["--remote-address", destination, "--port", str(port),
               "--media-udp-input", f"127.0.0.1:{SOURCE_PORT}"]))
        profiles = {}
        for name, peer, direction in (("receiver", listener, "srt-to-udp"), ("sender", caller, "udp-to-srt")):
            peer.wait_for("CONNECTED", timeout=30)
            profile = _parse_prefixed_json(peer.wait_for("PROFILE"), "PROFILE")
            if (profile.get("peerIdleTimeoutMillis") != peer_idle_ms
                    or profile.get("receiveTimeoutMillis") != SRT_RECEIVE_TIMEOUT_MS
                    or profile.get("mediaRelay") != direction
                    or profile.get("tooLatePacketDrop") is not True):
                raise QualificationError(f"{name} SRT profile does not match the predeclared profile")
            profiles[name] = profile
        for peer, direction in ((listener, "srt-to-udp"), (caller, "udp-to-srt")):
            peer.send("START_MEDIA")
            if _parse_prefixed_json(peer.wait_for("MEDIA_STARTED"), "MEDIA_STARTED") != {"direction": direction}:
                raise QualificationError("media relay did not start in the expected direction")

        phase = "faulted-capture"
        domain_id = _clock_domain()
        source_summary = work / "media-source.json"
        source = subprocess.Popen(
            ["ip", "netns", "exec", namespaces[0], "env", f"PYTHONPATH={package_root}",
             sys.executable, "-m", "rimf_lab.media_stream", "source", "--fixture", str(fixture),
             "--destination", f"127.0.0.1:{SOURCE_PORT}", "--rate-bps", str(SOURCE_RATE_BPS),
             "--datagram-bytes", str(DATAGRAM_BYTES), "--output", str(source_summary)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        helpers.append(source)
        source_started = time.monotonic_ns()
        inject_at = source_started + INJECT_AFTER_SOURCE_START_NS
        route_epochs.append({
            "schema_version": 1, "route_epoch": 1,
            "observed_at": _rfc3339_nano(time.time_ns()), "monotonic_ns": source_started,
            "reason": "initial", "previous_path_id": None,
            "current_path_id": f"transit-{ROLE_NAMES[active_index]}", "confidence": 1.0,
        })
        epoch = 1
        injected_ns: int | None = None
        reparent_ns: int | None = None
        stall_seen = False
        recovered_ns: int | None = None
        first_session_resumed = False
        session = 1  # 1: first session live; 0: ended, reconnecting; 2: second session live
        reconnect: dict[str, Any] | None = None
        first_relay: dict[str, Any] | None = None
        second_listener: _Peer | None = None
        second_caller: _Peer | None = None
        pending_caller: _Peer | None = None
        second_profiles: dict[str, Any] = {}
        second_port = 0
        source_done_ns: int | None = None
        previous_observation: dict | None = None
        missed_intervals = 0
        tick = 0

        def observe_fips(index: int) -> dict:
            unix_ns = time.time_ns()
            moment = time.monotonic_ns()
            payload: dict[str, Any] = {"metric_namespace": "fips.control",
                                       "metric_semantics": "tree-and-link-state",
                                       "observation_index": index}
            availability, reason = "available", None
            try:
                b_status = control(3, "show", "status", timeout=2)
                b_tree = control(3, "show", "tree", timeout=2)
                a_status = control(0, "show", "status", timeout=2)
                alt_status = control(alternate_index, "show", "status", timeout=2)
                payload.update({
                    "b_parent_role": {node_addrs[i]: ROLE_NAMES[i] for i in range(4)}.get(b_tree.get("parent"), "unknown"),
                    "b_root_role": {node_addrs[i]: ROLE_NAMES[i] for i in range(4)}.get(b_tree.get("root"), "unknown"),
                    "b_depth": b_tree.get("depth"),
                    "b_peer_count": b_status.get("peer_count"),
                    "b_link_count": b_status.get("link_count"),
                    "a_peer_count": a_status.get("peer_count"),
                    "a_link_count": a_status.get("link_count"),
                    "alternate_peer_count": alt_status.get("peer_count"),
                    "alternate_link_count": alt_status.get("link_count"),
                    "alternate_forwarded_packets": forwarding_counters(
                        control(alternate_index, "show", "routing", timeout=2))[0],
                })
            except (QualificationError, IndexError, TypeError) as exc:
                availability, reason = "unavailable", type(exc).__name__
                for field in ("b_parent_role", "b_root_role", "b_depth", "b_peer_count", "b_link_count",
                              "a_peer_count", "a_link_count", "alternate_peer_count",
                              "alternate_link_count", "alternate_forwarded_packets"):
                    payload.setdefault(field, None)
            envelope = _envelope(source="fips", name=f"fips:{index}", run_id=run_id, domain_id=domain_id,
                                 route_epoch=epoch, monotonic_ns=moment, unix_ns=unix_ns, payload=payload,
                                 availability=availability, reason=reason)
            fips_observations.append(envelope)
            return envelope

        def reparented(envelope: dict) -> bool:
            p = envelope["payload"]
            return (envelope["quality"]["availability"] == "available"
                    and p["b_parent_role"] == ROLE_NAMES[alternate_index] and p["b_root_role"] == "a"
                    and p["b_depth"] == 2 and p["b_peer_count"] == 1 and p["b_link_count"] == 1
                    and p["a_peer_count"] == 1 and p["a_link_count"] == 1
                    and p["alternate_peer_count"] == 2 and p["alternate_link_count"] == 2)

        def complete_reconnect() -> None:
            """The pending caller printed CONNECTED: start both relays of the second session."""
            nonlocal session, second_caller, pending_caller, second_profiles
            moment = time.monotonic_ns()
            reconnect["attempts"][-1].update(outcome="connected", ended_monotonic_ns=moment)
            reconnect["connected_monotonic_ns"] = moment
            second_caller, pending_caller = pending_caller, None
            second_listener.wait_for("CONNECTED", timeout=10)
            second_profiles = {}
            for name, peer, direction in (("receiver", second_listener, "srt-to-udp"),
                                          ("sender", second_caller, "udp-to-srt")):
                profile = _parse_prefixed_json(peer.wait_for("PROFILE"), "PROFILE")
                if (profile.get("peerIdleTimeoutMillis") != peer_idle_ms
                        or profile.get("receiveTimeoutMillis") != SRT_RECEIVE_TIMEOUT_MS
                        or profile.get("mediaRelay") != direction
                        or profile.get("tooLatePacketDrop") is not True):
                    raise QualificationError(f"second {name} SRT profile does not match the predeclared profile")
                second_profiles[name] = profile
            for peer, direction in ((second_listener, "srt-to-udp"), (second_caller, "udp-to-srt")):
                peer.send("START_MEDIA")
                if _parse_prefixed_json(peer.wait_for("MEDIA_STARTED"), "MEDIA_STARTED") != {"direction": direction}:
                    raise QualificationError("second media relay did not start in the expected direction")
            reconnect["media_restarted_monotonic_ns"] = time.monotonic_ns()
            session = 2

        while True:
            target = source_started + tick * SRT_SAMPLE_INTERVAL_NS
            while (remaining := target - time.monotonic_ns()) > 0:
                if session == 0 and pending_caller is not None:
                    # Notice the connect within about 10 ms instead of at the next sample tick.
                    if _take_line(pending_caller, "CONNECTED") is not None:
                        complete_reconnect()
                        continue
                    time.sleep(min(remaining, RECONNECT_POLL_NS) / 1_000_000_000)
                else:
                    time.sleep(remaining / 1_000_000_000)
            if time.monotonic_ns() - target >= SRT_SAMPLE_INTERVAL_NS:
                missed_intervals += 1
            if len(sender_samples) + len(second_sender_samples) >= MAX_SAMPLES:
                raise QualificationError("faulted capture exceeded its bounded sample count")
            delta = None
            if session == 1:
                sender, receiver = _sample_pair(listener, caller, tick)
                sender_samples.append(sender)
                receiver_samples.append(receiver)
                delta = receiver.get("delta", {}).get("unique_received_packet_delta")
                if (reconnecting and injected_ns is not None and recovered_ns is None
                        and source.poll() is None
                        and sender.get("delta", {}).get("unique_sent_packet_delta") == 0):
                    # The source is still running, so a sender that sent nothing in a whole
                    # sample interval has stopped relaying. Confirm the ended session first.
                    inferred = {"previous_sample_monotonic_ns": sender_samples[-2]["sampleMonotonicNano"],
                                "sample_monotonic_ns": sender["sampleMonotonicNano"]}
                    first_relay = {}
                    for name, peer in (("sender", caller), ("receiver", listener)):
                        peer.send("STOP_MEDIA")
                        first_relay[name] = _parse_prefixed_json(
                            peer.wait_for("MEDIA_STOPPED", timeout=10), "MEDIA_STOPPED")
                    if first_relay["sender"].get("connectionBroken") is not True:
                        raise QualificationError("the sender stopped sending although its session had not ended")
                    confirmed_ns = time.monotonic_ns()
                    sender, receiver = _sample_pair(listener, caller, tick + 1)
                    sender_samples.append(sender)
                    receiver_samples.append(receiver)
                    second_listener = _Peer(_peer_command(
                        namespaces[3], incident_peer, library_dir,
                        _peer_arguments("listener", staging / "receiver-source-2.jsonl", f"{flow_id}-2", peer_idle_ms)
                        + ["--bind-address", destination, "--media-udp-output", f"127.0.0.1:{OUTPUT_PORT}"]))
                    second_peers.append(second_listener)
                    second_port = _parse_prefixed_json(second_listener.wait_for("READY"), "READY").get("port")
                    if (not isinstance(second_port, int) or isinstance(second_port, bool)
                            or not 0 < second_port <= 65_535):
                        raise QualificationError("second SRT listener returned an invalid port")
                    reconnect = {
                        "schema_version": 1, "policy": srt_reconnect, "end_inferred": inferred,
                        "end_confirmed_monotonic_ns": confirmed_ns,
                        "listener_ready_monotonic_ns": time.monotonic_ns(),
                        "attempts": [], "connected_monotonic_ns": None,
                        "media_restarted_monotonic_ns": None,
                    }
                    session = 0
            elif session == 2:
                sender, receiver = _sample_pair(second_listener, second_caller, tick)
                second_sender_samples.append(sender)
                delta = receiver.get("delta", {}).get("unique_received_packet_delta")
            if session == 0:
                # One caller attempt at a time; a failed attempt is followed by the next at once.
                if pending_caller is not None and _take_line(pending_caller, "CONNECTED") is not None:
                    complete_reconnect()
                elif pending_caller is None or pending_caller.process.poll() is not None:
                    if pending_caller is not None:
                        reconnect["attempts"][-1].update(outcome="failed", ended_monotonic_ns=time.monotonic_ns())
                    if len(reconnect["attempts"]) >= SRT_RECONNECT_MAX_ATTEMPTS:
                        raise QualificationError("the SRT caller did not reconnect within its attempt bound")
                    pending_caller = _Peer(_peer_command(
                        namespaces[0], incident_peer, library_dir,
                        _peer_arguments("caller", staging / "sender-source-2.jsonl", f"{flow_id}-2", peer_idle_ms)
                        + ["--remote-address", destination, "--port", str(second_port),
                           "--media-udp-input", f"127.0.0.1:{SOURCE_PORT}"]))
                    second_peers.append(pending_caller)
                    reconnect["attempts"].append({"started_monotonic_ns": time.monotonic_ns(),
                                                  "ended_monotonic_ns": None, "outcome": "pending"})
            if injected_ns is not None and delta == 0:
                stall_seen = True
            if stall_seen and recovered_ns is None and _positive(delta):
                recovered_ns = time.monotonic_ns()
                first_session_resumed = session == 1
            if tick % FIPS_OBSERVATION_EVERY == 0 or (injected_ns is not None and reparent_ns is None):
                envelope = observe_fips(len(fips_observations))
                if (injected_ns is None and envelope["quality"]["availability"] == "available"
                        and envelope["payload"]["b_parent_role"] != ROLE_NAMES[active_index]):
                    raise QualificationError("b's tree parent changed before the fault was injected")
                if injected_ns is not None and reparent_ns is None and reparented(envelope):
                    reparent_ns = envelope["monotonic_ns"]
                    epoch = 2
                    envelope["route_epoch"] = 2
                    evidence = [previous_observation["event_id"], envelope["event_id"]] if previous_observation else [envelope["event_id"]]
                    route_epochs.append({
                        "schema_version": 1, "route_epoch": 2, "observed_at": envelope["observed_at"],
                        "monotonic_ns": reparent_ns, "reason": "relay-change",
                        "previous_path_id": f"transit-{ROLE_NAMES[active_index]}",
                        "current_path_id": f"transit-{ROLE_NAMES[alternate_index]}",
                        "confidence": 1.0, "evidence_event_ids": evidence,
                    })
                previous_observation = envelope
            now = time.monotonic_ns()
            if injected_ns is None and now >= inject_at:
                if not _positive(delta):
                    raise QualificationError("no SRT media delivery was observed before fault injection")
                injected_ns = time.monotonic_ns()
                if blackhole:
                    fault_events.append(_envelope(
                        source="fabric", name="fault:blackhole-start", run_id=run_id, domain_id=domain_id,
                        route_epoch=1, monotonic_ns=injected_ns, unix_ns=time.time_ns(),
                        payload={"metric_namespace": "fabric.fault", "metric_semantics": "fault-injection",
                                 "event": "blackhole-start", "target_role": ROLE_NAMES[active_index],
                                 "mechanism": "netem-loss-100-percent",
                                 "interfaces": len(blackhole_ends[active_index])}))
                    for node, interface, _ in blackhole_ends[active_index]:
                        stimulus = (["delay", f"{ALTERNATE_PATH_ONE_WAY_DELAY_MS}ms"]
                                    if interface in delayed_interfaces else [])
                        _run(["ip", "netns", "exec", namespaces[node], "tc", "qdisc", "replace", "dev", interface,
                              "root", "netem", *stimulus, "loss", "100%"], label="apply transit blackhole")
                    fault_events.append(_envelope(
                        source="fabric", name="fault:blackhole-applied", run_id=run_id, domain_id=domain_id,
                        route_epoch=1, monotonic_ns=time.monotonic_ns(), unix_ns=time.time_ns(),
                        payload={"metric_namespace": "fabric.fault", "metric_semantics": "fault-injection",
                                 "event": "blackhole-applied", "target_role": ROLE_NAMES[active_index],
                                 "interfaces": len(blackhole_ends[active_index])}))
                    running = daemons[active_index].poll() is None
                    fault_events.append(_envelope(
                        source="os", name="os:faulted-transit-process-state", run_id=run_id, domain_id=domain_id,
                        route_epoch=1, monotonic_ns=time.monotonic_ns(), unix_ns=time.time_ns(),
                        payload={"metric_namespace": "os.process", "metric_semantics": "daemon-process-state",
                                 "target_role": ROLE_NAMES[active_index], "running": running}))
                    if not running:
                        raise QualificationError("the blackholed transit's daemon is not running")
                else:
                    fault_events.append(_envelope(
                        source="fabric", name="fault:sigkill-sent", run_id=run_id, domain_id=domain_id,
                        route_epoch=1, monotonic_ns=injected_ns, unix_ns=time.time_ns(),
                        payload={"metric_namespace": "fabric.fault", "metric_semantics": "fault-injection",
                                 "event": "sigkill-sent", "target_role": ROLE_NAMES[active_index],
                                 "signal": "SIGKILL"}))
                    if not _hard_kill_process(daemons[active_index]):
                        raise QualificationError("active transit did not terminate from SIGKILL")
                    exited = time.monotonic_ns()
                    cleanup["faulted_daemon_reaped"] = True
                    daemons[active_index] = None
                    streams[active_index].close()
                    streams[active_index] = None
                    fault_events.append(_envelope(
                        source="fabric", name="fault:process-exit-observed", run_id=run_id, domain_id=domain_id,
                        route_epoch=1, monotonic_ns=exited, unix_ns=time.time_ns(),
                        payload={"metric_namespace": "fabric.fault", "metric_semantics": "fault-injection",
                                 "event": "process-exit-observed", "target_role": ROLE_NAMES[active_index],
                                 "exit_signal": "SIGKILL"}))
                states = []
                for interface in transit_interfaces[active_index]:
                    info = _json_value_command(["ip", "-n", namespaces[active_index], "-j", "link", "show",
                                                "dev", interface], label="faulted transit underlay state")
                    states.append(isinstance(info, list) and len(info) == 1 and "UP" in info[0].get("flags", []))
                fault_events.append(_envelope(
                    source="os", name="os:faulted-underlay-state", run_id=run_id, domain_id=domain_id,
                    route_epoch=1, monotonic_ns=time.monotonic_ns(), unix_ns=time.time_ns(),
                    payload={"metric_namespace": "os.link", "metric_semantics": "underlay-interface-state",
                             "interfaces": len(states), "interfaces_up": all(states)}))
                if not all(states):
                    raise QualificationError("faulted transit underlay did not stay up")
            if injected_ns is not None and reparent_ns is None and now - injected_ns > REPARENT_BUDGET_SECS * 1_000_000_000:
                raise QualificationError("automatic reparenting was not observed within its budget")
            if (injected_ns is not None and recovered_ns is None and recovery_required
                    and now - injected_ns > SRT_RECOVERY_BUDGET_NS):
                raise QualificationError("SRT media delivery did not resume within its budget")
            if source.poll() is not None and source_done_ns is None:
                if source.returncode != 0:
                    raise QualificationError("media source failed")
                source_done_ns = now
            if source_done_ns is not None and now - source_done_ns >= DRAIN_NS:
                break
            tick += 1
        if injected_ns is None or reparent_ns is None or (recovered_ns is None and recovery_required):
            raise QualificationError("the fixture ended before injection, reparenting and recovery were observed")
        if recovered_ns is not None and source_done_ns - recovered_ns < POST_RECOVERY_MINIMUM_NS:
            raise QualificationError("too little media followed recovery to observe it")

        if blackhole:
            # The blackhole must have been silent: daemon still running, packets dropped.
            running = daemons[active_index] is not None and daemons[active_index].poll() is None
            drops = []
            for node, interface, far in blackhole_ends[active_index]:
                qdiscs = _json_value_command(
                    ["ip", "netns", "exec", namespaces[node], "tc", "-s", "-j", "qdisc", "show", "dev", interface],
                    label="blackhole drop counters")
                netem = [item for item in qdiscs if isinstance(item, dict) and item.get("kind") == "netem"] \
                    if isinstance(qdiscs, list) else []
                if len(netem) != 1 or not isinstance(netem[0].get("drops"), int):
                    raise QualificationError("the blackhole qdisc is missing when the fixture ended")
                drops.append({"node_role": ROLE_NAMES[node], "toward_role": ROLE_NAMES[far],
                              "dropped_packets": netem[0]["drops"]})
            fault_events.append(_envelope(
                source="os", name="os:blackhole-drop-counters", run_id=run_id, domain_id=domain_id,
                route_epoch=epoch, monotonic_ns=time.monotonic_ns(), unix_ns=time.time_ns(),
                payload={"metric_namespace": "os.qdisc", "metric_semantics": "netem-drop-counters",
                         "target_role": ROLE_NAMES[active_index], "transit_running": running,
                         "drops": drops, "dropped_packets": sum(item["dropped_packets"] for item in drops)}))
            if not running:
                raise QualificationError("the blackholed transit's daemon exited during the run")
            if sum(item["dropped_packets"] for item in drops) < 1:
                raise QualificationError("the blackhole dropped no packet")
            if not _stop_process(daemons[active_index]):
                raise QualificationError("the blackholed transit's daemon did not stop")
            cleanup["faulted_daemon_reaped"] = True
            daemons[active_index] = None
            streams[active_index].close()
            streams[active_index] = None

        phase = "media-stop"
        final = tick + 1
        if reconnect is None:
            relay = {}
            for name, peer in (("sender", caller), ("receiver", listener)):
                peer.send("STOP_MEDIA")
                relay[name] = _parse_prefixed_json(peer.wait_for("MEDIA_STOPPED", timeout=10), "MEDIA_STOPPED")
            sender, receiver = _sample_pair(listener, caller, final)
            sender_samples.append(sender)
            receiver_samples.append(receiver)
        else:
            # The first session's relays were stopped and sampled when its end was confirmed.
            relay = first_relay
            if session != 2:
                raise QualificationError("the fixture ended before the second SRT session carried media")
            reconnect["profiles"] = second_profiles
            reconnect["stopped"] = {}
            for name, peer in (("sender", second_caller), ("receiver", second_listener)):
                peer.send("STOP_MEDIA")
                reconnect["stopped"][name] = _parse_prefixed_json(
                    peer.wait_for("MEDIA_STOPPED", timeout=10), "MEDIA_STOPPED")
            sender, receiver = _sample_pair(second_listener, second_caller, final)
            second_sender_samples.append(sender)
        session_survived = not relay["sender"]["connectionBroken"] and not relay["receiver"]["connectionBroken"]
        if recovered_ns is None and session_survived:
            raise QualificationError("SRT media delivery did not resume although no endpoint reported an ended session")
        finishing = [listener, caller] + ([second_listener, second_caller] if reconnect is not None else [])
        for peer in finishing:
            peer.send("DONE")
        for peer in finishing:
            peer.wait_for("RECORDED", timeout=20)
            peer.finish()
        listener = caller = None
        second_peers = [peer for peer in second_peers if peer not in finishing]
        collector.send_signal(signal.SIGTERM)
        try:
            collector.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise QualificationError("media collector did not stop") from exc
        if collector.returncode != 0:
            raise QualificationError("media collector failed")

        phase = "decode-and-adapt"
        _framehash(ffmpeg, received, staging / "observed.framehash", "independent downstream decode")
        assessment = assess_media_frames(staging / "reference.framehash", staging / "observed.framehash")
        retimed = retimed_frame_count(staging / "reference.framehash", staging / "observed.framehash")
        if retimed:
            raise QualificationError(f"downstream decode re-timed {retimed} frames; comparison is invalid")
        _write_json(staging / "frame-assessment.json", assessment)
        for name in ("media-source.json", "media-collector.json"):
            shutil.copyfile(work / name, staging / name)
        _write_json(staging / "media-relay.json", {"schema_version": 1, "profiles": profiles, "stopped": relay})
        for name, namespace in (("sender", SENDER_EVENT_NAMESPACE), ("receiver", RECEIVER_EVENT_NAMESPACE)):
            context_path = staging / f"{name}-context.json"
            _write_json(context_path, _adapter_context(domain_id, namespace, run_id, reparent_ns))
            adapt_srt_telemetry_jsonl(staging / f"{name}-source.jsonl", context_path,
                                      staging / f"{name}-observations.jsonl")
        receiver_second_observations = None
        if reconnect is not None:
            _write_json(staging / "srt-reconnect.json", reconnect)
            for name, namespace in (("sender", SENDER_EVENT_NAMESPACE_2), ("receiver", RECEIVER_EVENT_NAMESPACE_2)):
                context_path = staging / f"{name}-context-2.json"
                _write_json(context_path, _adapter_context(domain_id, namespace, run_id, reparent_ns))
                adapt_srt_telemetry_jsonl(staging / f"{name}-source-2.jsonl", context_path,
                                          staging / f"{name}-observations-2.jsonl")
            receiver_second_observations = _read_jsonl(staging / "receiver-observations-2.jsonl")
        _write_jsonl(staging / "fips-observations.jsonl", fips_observations)
        _write_jsonl(staging / "fault-events.jsonl", fault_events)
        _write_jsonl(staging / "route-epochs.jsonl", route_epochs)
        sender_observations = _read_jsonl(staging / "sender-observations.jsonl")
        receiver_observations = _read_jsonl(staging / "receiver-observations.jsonl")
        timeline = compute_timeline(
            fault_events=fault_events, fips_observations=fips_observations, route_epochs=route_epochs,
            sender=sender_observations, receiver=receiver_observations,
            collector=load_json(staging / "media-collector.json"),
            relay=load_json(staging / "media-relay.json"),
            reconnect=reconnect, receiver_second=receiver_second_observations)
        bundle_files = BUNDLE_FILES + (RECONNECT_FILES if reconnect is not None else ())
        source_record = load_json(staging / "media-source.json")
        collector_record = load_json(staging / "media-collector.json")
        result = {
            "schema_version": 1,
            "evidence_type": EVIDENCE_TYPE,
            "status": "passed",
            "classification": "experiment",
            "gate_ids": ["G4"],
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": utc_now(),
            "provenance": provenance,
            "platform": {"system": platform.system(), "release": platform.release(),
                         "machine": platform.machine(), "python": platform.python_version()},
            "clock": {**_clock(domain_id), "same_host": True},
            "topology": {
                "node_count": 4, "isolation": "linux-network-namespaces",
                "underlay": "diamond-veth-ipv4-udp", "direct_endpoint_underlay": False,
                "overlay": "srt-ipv6-over-fips0", "alternate_path_one_way_delay_ms": ALTERNATE_PATH_ONE_WAY_DELAY_MS,
                "initial_active_transit": ROLE_NAMES[active_index],
                "alternate_transit": ROLE_NAMES[alternate_index],
            },
            "profile": {
                "fixture": {"generator": FIXTURE_FILTER, "encode": list(FIXTURE_ENCODE),
                            "frames": FIXTURE_FRAMES, "sha256": source_record["fixture_sha256"]},
                "source_rate_bps": SOURCE_RATE_BPS,
                "datagram_bytes": DATAGRAM_BYTES,
                "packet_budget": packet_budget,
                "inject_after_source_start_ms": INJECT_AFTER_SOURCE_START_NS // 1_000_000,
                "srt_sample_interval_ms": SRT_SAMPLE_INTERVAL_NS // 1_000_000,
                "fips_observation_interval_ms": SRT_SAMPLE_INTERVAL_NS * FIPS_OBSERVATION_EVERY // 1_000_000,
                "srt_peer_idle_timeout_ms": peer_idle_ms,
                "srt_receive_timeout_ms": SRT_RECEIVE_TIMEOUT_MS,
                "reparent_budget_ms": REPARENT_BUDGET_SECS * 1000,
                "srt_recovery_budget_ms": SRT_RECOVERY_BUDGET_NS // 1_000_000,
                "collector_gap_threshold_ms": GAP_THRESHOLD_NS // 1_000_000,
                "decode_options": list(DECODE_OPTIONS),
                "fips_timers": timers,
                "srt_reconnect_policy": srt_reconnect,
                "fault": fault,
            },
            "capture": {
                "srt_samples_per_endpoint": len(sender_samples),
                "missed_sample_intervals": missed_intervals,
                "fips_observations": len(fips_observations),
                "route_epochs": [item["route_epoch"] for item in route_epochs],
                "srt_session_survived": session_survived,
                "srt_delivery_resumed": first_session_resumed,
                "srt_reconnected": reconnect is not None,
                "srt_second_session_samples_per_endpoint": len(second_sender_samples),
                "source_datagrams": source_record["datagrams"],
                "collected_datagrams": collector_record["datagrams"],
                "frames": {name: assessment[name] for name in (
                    "status", "expected_frames", "observed_frames", "missing_frames", "unexpected_frames",
                    "changed_frames", "max_consecutive_missing_frames")},
            },
            "timeline": timeline,
            "files": {name: _file_record(staging / name) for name in bundle_files},
            "cleanup": cleanup,
            "gate_conclusion": {
                "G4": "not-passed",
                "reason": "single faulted run; ordering-only; no first-divergent-layer or causal claim",
            },
            "limitations": [
                ("One run of one topology and one fault class (SIGKILL of the observed active transit)."
                 if not blackhole else
                 "One run of one topology and one fault class (netem loss 100% on both links of the observed "
                 "active transit, daemon left running). It says nothing about partial or one-way loss."),
                "Each layer is observed at its own resolution (collector per datagram, SRT 500 ms, FIPS about 1 s); "
                "overlapping intervals are reported as unordered.",
                "Temporal ordering does not establish a cause or a first divergent layer.",
                ("The SRT profile raises the peer idle timeout to 60 s for this experiment; it is not a product setting."
                 if not session_end_allowed else
                 "The SRT peer idle timeout is the 5 s default; the incident peer does not reconnect, so an ended "
                 "session ends media for the rest of the run and no reconnection time is measured."
                 if not reconnecting else
                 "The SRT peer idle timeout is the 5 s default. The coordinator, not the application, restarts "
                 "the session: it infers the end from a 500 ms sample, so the interruption includes a recorded "
                 "detection delay, and each caller attempt uses the incident peer's own connect timeout."),
                "The downstream decode runs after the run on the collected stream; it is not a live player.",
            ],
        }
    except Exception as exc:
        error = exc
    finally:
        phase_at_failure = phase
        peer_cleanup = [peer is None or peer.stop() for peer in (listener, caller, *second_peers)]
        cleanup["srt_peers_stopped"] = all(peer_cleanup)
        helper_cleanup = []
        for helper in helpers:
            if helper.poll() is None:
                try:
                    os.killpg(helper.pid, signal.SIGTERM)
                    helper.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(helper.pid, signal.SIGKILL)
                        helper.wait(timeout=5)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        pass
            helper_cleanup.append(helper.poll() is not None)
        cleanup["media_processes_stopped"] = all(helper_cleanup)
        cleanup["fips_daemons_stopped"] = all(_stop_process(process) for process in daemons)
        for item in streams:
            if item is not None:
                item.close()
        if error is not None:
            _print_redacted_log_tails(daemon_logs)
        for namespace in namespaces:
            _run(["ip", "netns", "del", namespace], label="remove namespace", timeout=10, check=False)
        listing = _run(["ip", "netns", "list"], label="verify namespace cleanup", check=False).stdout
        cleanup["namespaces_removed"] = all(namespace not in listing for namespace in namespaces)
        shutil.rmtree(work, ignore_errors=True)
        cleanup["work_directory_removed"] = not work.exists()

    if error is None and not all(cleanup.values()):
        error = QualificationError("faulted-diamond teardown did not complete")
        phase_at_failure = "teardown"
    if error is not None:
        failure = _failure_result(run_id, started_at, project_revision, phase_at_failure, cleanup, error)
        # Partial, redacted diagnostics stay beside the failed result; they are not evidence.
        diagnostics = {
            "schema_version": 1,
            "srt_samples_per_endpoint": len(sender_samples),
            "receiver_unique_received_deltas": [
                item.get("delta", {}).get("unique_received_packet_delta") for item in receiver_samples[-40:]
            ],
            "fips_observations": [item["payload"] | {"monotonic_ns": item["monotonic_ns"]}
                                  for item in fips_observations[-40:]],
            "fault_events": [item["payload"] | {"monotonic_ns": item["monotonic_ns"]} for item in fault_events],
            "route_epochs": route_epochs,
        }
        if not (staging / "diagnostics.json").exists():
            _write_json(staging / "diagnostics.json", diagnostics)
        if (staging / "result.json").exists():
            os.unlink(staging / "result.json")
        _write_json(staging / "result.json", failure)
        staging.rename(output_dir)
        raise QualificationError(
            f"faulted-diamond experiment failed during {phase_at_failure}: {failure['failure_detail']}"
        ) from error
    assert result is not None
    result["cleanup"] = cleanup
    _write_json(staging / "result.json", result)
    validate_g4_faulted_diamond_bundle(staging)
    staging.rename(output_dir)
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_g4_faulted_diamond_result(
    result: Any,
    *,
    expected_srt_commit: str = EXPECTED_SRT_COMMIT,
    expected_telemetry_commit: str = EXPECTED_TELEMETRY_COMMIT,
    expected_fips_commit: str = EXPECTED_FIPS_COMMIT,
) -> None:
    _require(isinstance(result, dict), "faulted-diamond result must be an object")
    _require(result.get("schema_version") == 1 and result.get("evidence_type") == EVIDENCE_TYPE,
             "faulted-diamond result schema/evidence_type is invalid")
    _require(result.get("classification") == "experiment" and result.get("gate_ids") == ["G4"],
             "faulted-diamond result classification/gates are invalid")
    try:
        uuid.UUID(result.get("run_id", ""))
    except (TypeError, ValueError) as exc:
        raise ContractError("faulted-diamond run_id is invalid") from exc
    conclusion = result.get("gate_conclusion")
    _require(isinstance(conclusion, dict) and set(conclusion) == {"G4", "reason"}
             and conclusion["G4"] == "not-passed" and isinstance(conclusion["reason"], str)
             and conclusion["reason"], "faulted-diamond result must record G4 as not-passed")
    cleanup = result.get("cleanup")
    expected_cleanup = {"srt_peers_stopped", "media_processes_stopped", "fips_daemons_stopped",
                        "faulted_daemon_reaped", "namespaces_removed", "work_directory_removed"}
    _require(isinstance(cleanup, dict) and set(cleanup) == expected_cleanup
             and all(isinstance(value, bool) for value in cleanup.values()),
             "faulted-diamond cleanup is invalid")
    common = {"schema_version", "evidence_type", "status", "classification", "gate_ids", "run_id",
              "started_at", "finished_at", "cleanup", "gate_conclusion"}
    if result.get("status") == "failed":
        _require(set(result) == common | {"project_revision", "failure_phase", "failure_class", "failure_detail"},
                 "failed faulted-diamond result fields are invalid")
        _require(bool(COMMIT_RE.fullmatch(result.get("project_revision", ""))),
                 "failed faulted-diamond project revision is invalid")
        return
    _require(result.get("status") == "passed", "faulted-diamond status is invalid")
    _require(set(result) == common | {"provenance", "platform", "clock", "topology", "profile", "capture",
                                      "timeline", "files", "limitations"},
             "passed faulted-diamond result fields are invalid")
    _require(all(cleanup.values()), "passed faulted-diamond result requires complete cleanup")
    provenance = result["provenance"]
    for field, expected in (("fips_repository", FIPS_REPOSITORY), ("fips_commit", expected_fips_commit),
                            ("fips_source_tree_state", "clean"), ("srt_repository", SRT_REPOSITORY),
                            ("srt_commit", expected_srt_commit), ("telemetry_repository", TELEMETRY_REPOSITORY),
                            ("telemetry_commit", expected_telemetry_commit)):
        _require(provenance.get(field) == expected, f"faulted-diamond provenance {field} is invalid")
    _require(str(provenance.get("ffmpeg_version", "")).startswith(EXPECTED_FFMPEG_VERSION + " "),
             "faulted-diamond provenance ffmpeg_version is invalid")
    for field in ("cargo_lock_sha256", "rust_toolchain_sha256", "srt_library_sha256", "incident_peer_sha256",
                  "fips_binary_sha256", "fipsctl_binary_sha256", "ffmpeg_binary_sha256"):
        value = provenance.get(field)
        _require(isinstance(value, str) and len(value) == 64, f"faulted-diamond provenance {field} is invalid")
    _require(bool(COMMIT_RE.fullmatch(provenance.get("project_revision", ""))),
             "faulted-diamond provenance project_revision is invalid")
    clock = result["clock"]
    _require(clock.get("same_host") is True and clock.get("synchronization") == "local-only"
             and clock.get("cross_host_ordering_allowed") is False, "faulted-diamond clock is invalid")
    topology = result["topology"]
    _require(topology.get("node_count") == 4 and topology.get("direct_endpoint_underlay") is False
             and topology.get("overlay") == "srt-ipv6-over-fips0"
             and {topology.get("initial_active_transit"), topology.get("alternate_transit")} == {"r1", "r2"},
             "faulted-diamond topology is invalid")
    profile = result["profile"]
    budget = profile.get("packet_budget", {})
    _require(profile.get("datagram_bytes") == DATAGRAM_BYTES
             and budget.get("media_datagram_bytes") == DATAGRAM_BYTES
             and isinstance(budget.get("clear_srt_payload_budget_bytes"), int)
             and DATAGRAM_BYTES <= budget["clear_srt_payload_budget_bytes"],
             "faulted-diamond media datagrams do not fit the recorded packet budget")
    _require(profile.get("srt_peer_idle_timeout_ms") in SRT_PEER_IDLE_PROFILES.values()
             and profile.get("inject_after_source_start_ms") == INJECT_AFTER_SOURCE_START_NS // 1_000_000
             and profile.get("fixture", {}).get("frames") == FIXTURE_FRAMES
             and profile.get("fixture", {}).get("encode") == list(FIXTURE_ENCODE)
             and profile.get("decode_options") == list(DECODE_OPTIONS),
             "faulted-diamond profile is not the predeclared profile")
    # Results written before the field existed ran the G2 diamond's timers.
    timers = profile.get("fips_timers", fips_timer_profile(DEFAULT_FIPS_TIMER_PROFILE))
    _require(isinstance(timers, dict) and timers.get("name") in FIPS_TIMER_PROFILES
             and timers == fips_timer_profile(timers["name"]),
             "faulted-diamond FIPS timers are not a predeclared profile")
    capture = result["capture"]
    _require(capture.get("route_epochs") == [1, 2], "faulted-diamond capture must hold two route epochs")
    # Results written before the field existed all resumed delivery. Delivery that never
    # resumed is a valid outcome only for an ended session under the default peer-idle profile.
    resumed = capture.get("srt_delivery_resumed", True)
    _require(isinstance(resumed, bool) and isinstance(capture.get("srt_session_survived"), bool)
             and (resumed or (capture["srt_session_survived"] is False
                              and profile["srt_peer_idle_timeout_ms"] == SRT_PEER_IDLE_PROFILES["default"])),
             "faulted-diamond delivery outcome does not match the predeclared SRT peer-idle profile")
    # Results written before the fields existed used no reconnect policy.
    policy = profile.get("srt_reconnect_policy", DEFAULT_SRT_RECONNECT_POLICY)
    reconnected = capture.get("srt_reconnected", False)
    _require(policy in SRT_RECONNECT_POLICIES and isinstance(reconnected, bool)
             and (policy == DEFAULT_SRT_RECONNECT_POLICY
                  or profile["srt_peer_idle_timeout_ms"] == SRT_PEER_IDLE_PROFILES["default"])
             and (not reconnected or (policy != DEFAULT_SRT_RECONNECT_POLICY and not resumed
                                      and capture["srt_session_survived"] is False)),
             "faulted-diamond reconnect outcome does not match the predeclared reconnect policy")
    # Results written before the field existed killed the transit.
    fault = profile.get("fault", DEFAULT_FAULT)
    _require(fault in FAULT_TYPES
             and (fault == DEFAULT_FAULT
                  or (profile["srt_peer_idle_timeout_ms"] == SRT_PEER_IDLE_PROFILES[DEFAULT_SRT_PEER_IDLE_PROFILE]
                      and policy == DEFAULT_SRT_RECONNECT_POLICY)),
             "faulted-diamond fault is not a predeclared fault")
    _require(capture.get("frames", {}).get("expected_frames") == FIXTURE_FRAMES,
             "faulted-diamond frame comparison is incomplete")
    _require(set(result["files"]) == set(BUNDLE_FILES + (RECONNECT_FILES if reconnected else ())),
             "faulted-diamond file inventory is invalid")
    limitations = result["limitations"]
    _require(isinstance(limitations, list) and len(limitations) >= 3, "faulted-diamond limitations are invalid")
    timeline = result["timeline"]
    _require(isinstance(timeline, dict) and timeline.get("causal_claim") is None,
             "faulted-diamond timeline must not carry a causal claim")


def validate_reconnect_record(record: Any, profile: dict) -> None:
    """Check the coordinator's reconnect record: one connected attempt, last, in time order."""
    _require(isinstance(record, dict) and set(record) == {
        "schema_version", "policy", "end_inferred", "end_confirmed_monotonic_ns",
        "listener_ready_monotonic_ns", "attempts", "connected_monotonic_ns",
        "media_restarted_monotonic_ns", "profiles", "stopped"}
             and record["schema_version"] == 1, "reconnect record fields are invalid")
    _require(record["policy"] == profile.get("srt_reconnect_policy") != DEFAULT_SRT_RECONNECT_POLICY,
             "reconnect record policy disagrees with the profile")
    inferred = record["end_inferred"]
    attempts = record["attempts"]
    _require(isinstance(inferred, dict)
             and set(inferred) == {"previous_sample_monotonic_ns", "sample_monotonic_ns"}
             and isinstance(attempts, list) and 1 <= len(attempts) <= SRT_RECONNECT_MAX_ATTEMPTS
             and all(isinstance(item, dict)
                     and set(item) == {"started_monotonic_ns", "ended_monotonic_ns", "outcome"}
                     for item in attempts),
             "reconnect record structure is invalid")
    _require([item["outcome"] for item in attempts] == ["failed"] * (len(attempts) - 1) + ["connected"],
             "reconnect attempts must be failures followed by one connected attempt")
    order = [inferred["previous_sample_monotonic_ns"], inferred["sample_monotonic_ns"],
             record["end_confirmed_monotonic_ns"], record["listener_ready_monotonic_ns"]]
    for item in attempts:
        order += [item["started_monotonic_ns"], item["ended_monotonic_ns"]]
    order.append(record["media_restarted_monotonic_ns"])
    _require(all(_positive(value) for value in order) and order == sorted(order)
             and record["connected_monotonic_ns"] == attempts[-1]["ended_monotonic_ns"],
             "reconnect record times are not in order")
    profiles, stopped = record["profiles"], record["stopped"]
    _require(isinstance(profiles, dict) and isinstance(stopped, dict)
             and set(profiles) == set(stopped) == {"sender", "receiver"}
             and all(item.get("peerIdleTimeoutMillis") == profile["srt_peer_idle_timeout_ms"]
                     for item in profiles.values())
             and all(isinstance(item.get("connectionBroken"), bool) for item in stopped.values()),
             "reconnect record profiles or relay counters are invalid")


def validate_g4_faulted_diamond_bundle(directory: Path) -> None:
    directory = directory.resolve()
    result_path = directory / "result.json"
    result = load_json(result_path)
    pins = HISTORICAL_G4_FAULTED_DIAMOND_BUNDLES.get(sha256_file(result_path), {
        "srt_commit": EXPECTED_SRT_COMMIT,
        "srt_version": EXPECTED_SRT_VERSION,
        "telemetry_commit": EXPECTED_TELEMETRY_COMMIT,
        "fips_commit": EXPECTED_FIPS_COMMIT,
    })
    validate_g4_faulted_diamond_result(
        result,
        expected_srt_commit=pins["srt_commit"],
        expected_telemetry_commit=pins["telemetry_commit"],
        expected_fips_commit=pins["fips_commit"],
    )
    if result["status"] == "failed":
        return
    for name, record in result["files"].items():
        try:
            actual = _file_record(directory / name)
        except OSError as exc:
            raise ContractError(f"cannot read faulted-diamond file {name}: {exc}") from exc
        _require(actual == record, f"faulted-diamond file digest/size mismatch: {name}")
    route_epochs = _read_jsonl(directory / "route-epochs.jsonl")
    for event in route_epochs:
        validate_route_epoch_event(event)
    _require([event["route_epoch"] for event in route_epochs] == [1, 2], "route epochs must be 1 then 2")
    marker = route_epochs[1]
    _require(marker["reason"] == "relay-change" and marker["previous_path_id"] != marker["current_path_id"],
             "route epoch 2 must mark a relay change")
    fips = _read_jsonl(directory / "fips-observations.jsonl")
    faults = _read_jsonl(directory / "fault-events.jsonl")
    for envelope in fips + faults:
        validate_correlation_envelope(envelope)
        expected_epoch = 2 if envelope["monotonic_ns"] >= marker["monotonic_ns"] else 1
        _require(envelope["route_epoch"] == expected_epoch, "envelope route epoch disagrees with the marker")
    evidence = {item["event_id"] for item in fips}
    _require(all(item in evidence for item in marker["evidence_event_ids"]),
             "route epoch 2 evidence does not reference retained FIPS observations")
    reconnected = result["capture"].get("srt_reconnected", False)
    sessions = [("", SENDER_EVENT_NAMESPACE, RECEIVER_EVENT_NAMESPACE)]
    if reconnected:
        sessions.append(("-2", SENDER_EVENT_NAMESPACE_2, RECEIVER_EVENT_NAMESPACE_2))
    for suffix, sender_namespace, receiver_namespace in sessions:
        for role, namespace in (("sender", sender_namespace), ("receiver", receiver_namespace)):
            label = f"{role}{suffix}"
            context = load_json(directory / f"{role}-context{suffix}.json")
            _require(context.get("event_namespace") == namespace
                     and context.get("route_epoch_transitions") == [
                         {"route_epoch": 2, "from_monotonic_ns": marker["monotonic_ns"]}],
                     f"{label} adapter context does not carry the observed route epoch marker")
            records = _read_jsonl(directory / f"{role}-source{suffix}.jsonl")
            _require(bool(records) and records[0].get("providerVersion") == pins["srt_version"]
                     and records[0].get("providerRevision") == pins["srt_commit"],
                     f"{label} provider identity does not match provenance")
            with tempfile.TemporaryDirectory() as scratch:
                replay = Path(scratch) / "replay.jsonl"
                adapt_srt_telemetry_jsonl(directory / f"{role}-source{suffix}.jsonl",
                                          directory / f"{role}-context{suffix}.json", replay)
                _require(replay.read_bytes() == (directory / f"{role}-observations{suffix}.jsonl").read_bytes(),
                         f"{label} observations are not a byte-exact adapter replay")
            for observation in _read_jsonl(directory / f"{role}-observations{suffix}.jsonl"):
                validate_srt_telemetry_observation(observation)
    reconnect = None
    receiver_second = None
    if reconnected:
        reconnect = load_json(directory / "srt-reconnect.json")
        validate_reconnect_record(reconnect, result["profile"])
        receiver_second = _read_jsonl(directory / "receiver-observations-2.jsonl")
    stored = load_json(directory / "frame-assessment.json")
    recomputed = assess_media_frames(directory / "reference.framehash", directory / "observed.framehash")
    _require(stored == recomputed, "frame assessment is not reproducible from the retained framehashes")
    _require(retimed_frame_count(directory / "reference.framehash", directory / "observed.framehash") == 0,
             "downstream decode re-timed frames; the frame comparison is invalid")
    timeline = compute_timeline(
        fault_events=faults, fips_observations=fips, route_epochs=route_epochs,
        sender=_read_jsonl(directory / "sender-observations.jsonl"),
        receiver=_read_jsonl(directory / "receiver-observations.jsonl"),
        collector=load_json(directory / "media-collector.json"),
        relay=load_json(directory / "media-relay.json"),
        reconnect=reconnect, receiver_second=receiver_second)
    _require(timeline == result["timeline"], "timeline is not reproducible from the retained files")
    fault = result["profile"].get("fault", DEFAULT_FAULT)
    _require(timeline["origin"] == FAULT_EVENTS[fault][0], "fault events disagree with the profile's fault")
    if fault != DEFAULT_FAULT:
        by_name = {item["payload"].get("metric_semantics"): item["payload"] for item in faults
                   if item["source"] == "os"}
        counters = by_name.get("netem-drop-counters", {})
        entries = counters.get("drops")
        _require(by_name.get("daemon-process-state", {}).get("running") is True
                 and by_name.get("underlay-interface-state", {}).get("interfaces_up") is True
                 and counters.get("transit_running") is True
                 and isinstance(entries, list) and len(entries) == 4
                 and all(isinstance(item.get("dropped_packets"), int) for item in entries)
                 and counters.get("dropped_packets") == sum(item["dropped_packets"] for item in entries) >= 1,
                 "blackhole fault events do not show a silent, dropping transit")
    _require(not reconnected or timeline["srt_reconnect"]["second_session_first_delivery"] is not None,
             "a reconnected run must show delivery over the second session")
    relay = load_json(directory / "media-relay.json")
    ended = [relay.get("stopped", {}).get(role, {}).get("connectionBroken") for role in ("sender", "receiver")]
    _require(all(isinstance(value, bool) for value in ended)
             and result["capture"]["srt_session_survived"] is (not any(ended)),
             "srt_session_survived disagrees with the retained media-relay record")
    _require(all(profile.get("peerIdleTimeoutMillis") == result["profile"]["srt_peer_idle_timeout_ms"]
                 for profile in relay.get("profiles", {}).values()) and len(relay.get("profiles", {})) == 2,
             "recorded SRT peer-idle timeout disagrees with the profile")
    resumed = result["capture"].get("srt_delivery_resumed", True)
    _require(resumed is (result["timeline"]["srt_receiver_resume"] is not None),
             "srt_delivery_resumed disagrees with the recomputed timeline")
    source = load_json(directory / "media-source.json")
    _require(source.get("fixture_sha256") == result["profile"]["fixture"]["sha256"]
             and source.get("datagram_bytes") == DATAGRAM_BYTES
             and source.get("interval_ns") == datagram_interval_ns(SOURCE_RATE_BPS, DATAGRAM_BYTES),
             "media source record disagrees with the profile")
