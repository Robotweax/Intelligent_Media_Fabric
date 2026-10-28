from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .contracts import (
    ContractError,
    SRT_ADAPTER_CONTRACT,
    SRT_TELEMETRY_SCHEMA_ID,
    SRT_TELEMETRY_SCHEMA_SHA256,
    SRT_TELEMETRY_VERSION,
    load_json,
    route_epoch_at,
    validate_srt_adapter_context,
    validate_srt_telemetry_observation,
)


MAX_SOURCE_LINE_BYTES = 1024 * 1024
QUALITY_FLAGS = {
    1: "first-sample-delta-baseline",
    2: "monotonic-clock-regression",
    4: "provider-changed",
    8: "counter-reset",
}

RECORDING_FIELDS = {
    "schemaVersion",
    "kind",
    "streamId",
    "flowId",
    "role",
    "configuredProvider",
    "providerVersion",
    "providerRevision",
    "buildProfile",
    "telemetryVersion",
    "recordCount",
    "capacity",
    "overwrittenCount",
}
RAW_UNSIGNED_FIELDS = {
    "sent_packet_total",
    "received_packet_total",
    "unique_sent_packet_total",
    "unique_received_packet_total",
    "sender_loss_packet_total",
    "receiver_loss_packet_total",
    "retransmitted_packet_total",
    "sender_drop_packet_total",
    "receiver_drop_packet_total",
    "receiver_undecryptable_packet_total",
    "sent_wire_byte_total",
    "received_wire_byte_total",
    "unique_sent_wire_byte_total",
    "unique_received_wire_byte_total",
    "retransmitted_wire_byte_total",
    "flight_size_packets",
    "flow_window_packets",
    "congestion_window_packets",
    "available_send_buffer_bytes",
    "available_receive_buffer_bytes",
    "send_buffer_bytes",
    "receive_buffer_bytes",
}
RAW_NUMBER_FIELDS = {
    "rtt_seconds",
    "send_buffer_seconds",
    "receive_buffer_seconds",
    "sender_tsbpd_delay_seconds",
    "receiver_tsbpd_delay_seconds",
}
RAW_FIELDS = {
    "provider",
    "capabilities",
    "available_fields",
    "observed_at_unix_nano",
    "sample_monotonic_nano",
    *RAW_UNSIGNED_FIELDS,
    *RAW_NUMBER_FIELDS,
}
DELTA_UNSIGNED_FIELDS = {
    "sent_packet_delta",
    "received_packet_delta",
    "unique_sent_packet_delta",
    "unique_received_packet_delta",
    "sender_loss_packet_delta",
    "receiver_loss_packet_delta",
    "retransmitted_packet_delta",
    "sender_drop_packet_delta",
    "receiver_drop_packet_delta",
    "receiver_undecryptable_packet_delta",
    "sent_wire_byte_delta",
    "received_wire_byte_delta",
    "unique_sent_wire_byte_delta",
    "unique_received_wire_byte_delta",
    "retransmitted_wire_byte_delta",
}
DELTA_NUMBER_FIELDS = {
    "sent_wire_bits_per_second",
    "received_wire_bits_per_second",
    "unique_sent_wire_bits_per_second",
    "unique_received_wire_bits_per_second",
}
DELTA_FIELDS = {
    "quality_flags",
    "interval_nano",
    "available_delta_fields",
    "counter_reset_fields",
    "available_rates",
    *DELTA_UNSIGNED_FIELDS,
    *DELTA_NUMBER_FIELDS,
}
SAMPLE_FIELDS = {"schemaVersion", "kind", "streamId", "sampleIndex", "raw", "delta"}


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(value)
    unexpected = set(value) - expected
    if missing:
        raise ContractError(f"{context} is missing fields: {', '.join(sorted(missing))}")
    if unexpected:
        raise ContractError(f"{context} has unexpected fields: {', '.join(sorted(unexpected))}")


def _string(value: Any, context: str, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(f"{context} must be a non-empty string of at most {maximum} characters")
    return value


def _unsigned(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"{context} must be a non-negative integer")
    return value


def _nullable_unsigned(value: Any, context: str) -> None:
    if value is not None:
        _unsigned(value, context)


def _nullable_number(value: Any, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ContractError(f"{context} must be a finite number or null")


def _parse_json_line(line: str, line_number: int) -> dict[str, Any]:
    if not line.strip():
        raise ContractError(f"source JSONL line {line_number} is blank")
    if len(line.encode("utf-8")) > MAX_SOURCE_LINE_BYTES:
        raise ContractError(f"source JSONL line {line_number} exceeds the one MiB limit")

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        return _object(
            json.loads(line, parse_constant=reject_constant),
            f"source JSONL line {line_number}",
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"source JSONL line {line_number} is invalid JSON: {exc}") from exc


def _validate_recording(recording: dict[str, Any]) -> None:
    _exact_fields(recording, RECORDING_FIELDS, "source recording")
    if (
        recording.get("schemaVersion") != "1alpha1"
        or recording.get("kind") != "robotweax-srt-telemetry-recording"
    ):
        raise ContractError("source recording does not use the pinned v1alpha1 contract")
    for field in ("streamId", "flowId", "providerVersion", "providerRevision", "buildProfile"):
        _string(recording.get(field), f"source recording.{field}")
    if recording.get("role") not in {"sender", "receiver"}:
        raise ContractError("source recording.role is invalid")
    if recording.get("configuredProvider") not in {"robotweax-srt", "haivision-srt"}:
        raise ContractError("source recording.configuredProvider is not a qualified provider")
    if recording.get("telemetryVersion") != SRT_TELEMETRY_VERSION:
        raise ContractError("source recording.telemetryVersion is not pinned")
    for field in ("recordCount", "capacity", "overwrittenCount"):
        _unsigned(recording.get(field), f"source recording.{field}")
    if not 1 <= recording["capacity"] <= 1_000_000:
        raise ContractError("source recording.capacity is outside the upstream contract")
    if recording["recordCount"] > recording["capacity"]:
        raise ContractError("source recording.recordCount exceeds capacity")


def _validate_sample(sample: dict[str, Any], recording: dict[str, Any]) -> None:
    _exact_fields(sample, SAMPLE_FIELDS, "source sample")
    if (
        sample.get("schemaVersion") != "1alpha1"
        or sample.get("kind") != "robotweax-srt-telemetry-sample"
    ):
        raise ContractError("source sample does not use the pinned v1alpha1 contract")
    if sample.get("streamId") != recording["streamId"]:
        raise ContractError("source sample streamId does not match the recording header")
    _unsigned(sample.get("sampleIndex"), "source sample.sampleIndex")

    raw = _object(sample.get("raw"), "source sample.raw")
    _exact_fields(raw, RAW_FIELDS, "source sample.raw")
    if raw.get("provider") != recording["configuredProvider"]:
        raise ContractError("source sample provider does not match the recording header")
    for field in ("capabilities", "available_fields", "observed_at_unix_nano", "sample_monotonic_nano"):
        _unsigned(raw.get(field), f"source sample.raw.{field}")
    for field in RAW_UNSIGNED_FIELDS:
        _nullable_unsigned(raw.get(field), f"source sample.raw.{field}")
    for field in RAW_NUMBER_FIELDS:
        _nullable_number(raw.get(field), f"source sample.raw.{field}")

    delta = _object(sample.get("delta"), "source sample.delta")
    _exact_fields(delta, DELTA_FIELDS, "source sample.delta")
    for field in (
        "quality_flags",
        "interval_nano",
        "available_delta_fields",
        "counter_reset_fields",
        "available_rates",
    ):
        _unsigned(delta.get(field), f"source sample.delta.{field}")
    for field in DELTA_UNSIGNED_FIELDS:
        _nullable_unsigned(delta.get(field), f"source sample.delta.{field}")
    for field in DELTA_NUMBER_FIELDS:
        _nullable_number(delta.get(field), f"source sample.delta.{field}")
    has_reset_flag = bool(delta["quality_flags"] & 8)
    has_reset_fields = delta["counter_reset_fields"] != 0
    if has_reset_flag != has_reset_fields:
        raise ContractError("source sample counter-reset flag and field mask are inconsistent")


def _quality(delta: dict[str, Any], available_fields: int) -> dict[str, Any]:
    flags = delta["quality_flags"]
    if available_fields == 0:
        availability = "unavailable"
        reason: str | None = "source-fields-unavailable"
    elif flags:
        availability = "partial"
        reasons = [name for bit, name in QUALITY_FLAGS.items() if flags & bit]
        unknown_flags = flags & ~sum(QUALITY_FLAGS.keys())
        if unknown_flags:
            reasons.append(f"unknown-source-quality-flags-0x{unknown_flags:x}")
        reason = ",".join(reasons)
    else:
        availability = "available"
        reason = None
    return {
        "availability": availability,
        "reason": reason,
        "source_available_fields": available_fields,
        "source_quality_flags": flags,
        "source_available_delta_fields": delta["available_delta_fields"],
        "source_counter_reset_fields": delta["counter_reset_fields"],
        "source_available_rates": delta["available_rates"],
    }


def _observation(
    recording: dict[str, Any], sample: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    raw = sample["raw"]
    delta = sample["delta"]
    event_name = "\x1f".join(
        (
            recording["configuredProvider"],
            recording["providerVersion"],
            recording["providerRevision"],
            recording["telemetryVersion"],
            context["telemetry_revision"],
            recording["flowId"],
            recording["streamId"],
            recording["role"],
            str(sample["sampleIndex"]),
            str(raw["observed_at_unix_nano"]),
            str(raw["sample_monotonic_nano"]),
        )
    )
    event_id = str(uuid.uuid5(uuid.UUID(context["event_namespace"]), event_name))
    observation = {
        "schema_version": 1,
        "event_id": event_id,
        "source": "srt",
        "observed_at_unix_nano": raw["observed_at_unix_nano"],
        "monotonic_ns": raw["sample_monotonic_nano"],
        "route_epoch": route_epoch_at(context, raw["sample_monotonic_nano"]),
        "clock": deepcopy(context["clock"]),
        "fabric_identity": deepcopy(context["fabric_identity"]),
        "source_identity": {
            "stream_id": recording["streamId"],
            "flow_id": recording["flowId"],
            "role": recording["role"],
            "sample_index": sample["sampleIndex"],
            "identifiers_pseudonymous": context["source_identifiers_pseudonymous"],
        },
        "provenance": {
            "provider": recording["configuredProvider"],
            "provider_version": recording["providerVersion"],
            "provider_revision": recording["providerRevision"],
            "build_profile": recording["buildProfile"],
            "telemetry_version": recording["telemetryVersion"],
            "telemetry_revision": context["telemetry_revision"],
            "source_schema_id": SRT_TELEMETRY_SCHEMA_ID,
            "source_schema_sha256": SRT_TELEMETRY_SCHEMA_SHA256,
            "adapter_contract": SRT_ADAPTER_CONTRACT,
        },
        "quality": _quality(delta, raw["available_fields"]),
        "payload": {"recording": deepcopy(recording), "sample": deepcopy(sample)},
    }
    validate_srt_telemetry_observation(observation)
    return observation


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def adapt_srt_telemetry_jsonl(
    source_path: Path, context_path: Path, output_path: Path
) -> dict[str, Any]:
    source_path = source_path.resolve()
    context_path = context_path.resolve()
    output_path = output_path.resolve()
    if len({source_path, context_path, output_path}) != 3:
        raise ContractError("source, context, and output paths must be distinct")
    if output_path.exists():
        raise ContractError("adapter output already exists")

    context = load_json(context_path)
    validate_srt_adapter_context(context)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_name: str | None = None
    sample_count = 0
    previous_sample_index: int | None = None
    try:
        try:
            source_handle = source_path.open("r", encoding="utf-8", newline="")
        except OSError as exc:
            raise ContractError(f"cannot open source JSONL {source_path}: {exc}") from exc
        with source_handle, tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output_handle:
            temporary_name = output_handle.name
            first_line = source_handle.readline()
            if not first_line:
                raise ContractError("source JSONL is empty")
            recording = _parse_json_line(first_line, 1)
            _validate_recording(recording)

            for line_number, line in enumerate(source_handle, start=2):
                sample = _parse_json_line(line, line_number)
                _validate_sample(sample, recording)
                sample_index = sample["sampleIndex"]
                if previous_sample_index is not None and sample_index <= previous_sample_index:
                    raise ContractError("source sample indices must be strictly increasing")
                previous_sample_index = sample_index
                observation = _observation(recording, sample, context)
                json.dump(
                    observation,
                    output_handle,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                output_handle.write("\n")
                sample_count += 1

            if sample_count != recording["recordCount"]:
                raise ContractError(
                    "source JSONL sample count does not match recording.recordCount"
                )
            output_handle.flush()
            os.fsync(output_handle.fileno())

        try:
            os.link(temporary_name, output_path)
        except FileExistsError as exc:
            raise ContractError("adapter output already exists") from exc
        return {
            "status": "passed",
            "sample_count": sample_count,
            "source_sha256": _sha256_file(source_path),
            "context_sha256": _sha256_file(context_path),
            "output_sha256": _sha256_file(output_path),
        }
    except UnicodeError as exc:
        raise ContractError(f"source JSONL is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise ContractError(f"SRT adapter I/O failure: {exc}") from exc
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
