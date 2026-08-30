from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .contracts import (
    ContractError,
    load_json,
    rfc3339_to_unix_nano,
    validate_correlation_envelope,
    validate_g4_ordering_assessment,
    validate_srt_telemetry_observation,
)


ANALYSIS_NAMESPACE = uuid.UUID("b9ec6548-e01d-4b88-a8fe-8ec42baedcb8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _insufficient(reason: str, same_domain: bool) -> tuple[dict[str, Any], str, str]:
    return (
        {
            "same_domain": same_domain,
            "ordering_authorized": False,
            "basis": "none",
            "combined_max_error_ns": None,
        },
        "insufficient-evidence",
        reason,
    )


def build_g4_ordering_assessment(
    srt: dict[str, Any],
    peer: dict[str, Any],
    *,
    srt_sha256: str,
    peer_sha256: str,
) -> dict[str, Any]:
    validate_srt_telemetry_observation(srt)
    validate_correlation_envelope(peer)
    same_domain = srt["clock"]["domain_id"] == peer["clock"]["domain_id"]
    ordering = "unknown"

    if srt["route_epoch"] != peer["route_epoch"]:
        clock_assessment, outcome, reason = _insufficient("route-epoch-mismatch", same_domain)
    elif (
        srt["quality"]["availability"] == "unavailable"
        or peer["quality"]["availability"] == "unavailable"
    ):
        clock_assessment, outcome, reason = _insufficient(
            "source-quality-unavailable", same_domain
        )
    elif same_domain:
        if srt["quality"]["source_quality_flags"] & 2:
            clock_assessment, outcome, reason = _insufficient(
                "source-quality-unavailable", True
            )
        else:
            difference = peer["monotonic_ns"] - srt["monotonic_ns"]
            clock_assessment = {
                "same_domain": True,
                "ordering_authorized": True,
                "basis": "shared-monotonic-domain",
                "combined_max_error_ns": None,
            }
            if difference == 0:
                outcome = "insufficient-evidence"
                reason = "clock-resolution-tie"
            else:
                outcome = "ordered"
                reason = "shared-monotonic-order"
                ordering = "srt-before-peer" if difference > 0 else "peer-before-srt"
    elif (
        srt["clock"]["cross_host_ordering_allowed"]
        and peer["clock"]["cross_host_ordering_allowed"]
    ):
        combined_error = srt["clock"]["max_error_ns"] + peer["clock"]["max_error_ns"]
        difference = rfc3339_to_unix_nano(peer["observed_at"], "observed_at") - srt[
            "observed_at_unix_nano"
        ]
        clock_assessment = {
            "same_domain": False,
            "ordering_authorized": True,
            "basis": "bounded-wall-clock",
            "combined_max_error_ns": combined_error,
        }
        if abs(difference) <= combined_error:
            outcome = "insufficient-evidence"
            reason = "clock-uncertainty-overlap"
        else:
            outcome = "ordered"
            reason = "bounded-wall-clock-order"
            ordering = "srt-before-peer" if difference > 0 else "peer-before-srt"
    else:
        clock_assessment, outcome, reason = _insufficient(
            "clock-domains-not-comparable", False
        )

    analysis_id = str(
        uuid.uuid5(ANALYSIS_NAMESPACE, f"{srt['event_id']}\x1f{peer['event_id']}")
    )
    supported_claims = [
        "The declared route epochs and clock domains were evaluated without changing source data.",
    ]
    if peer["source"] == "fips":
        supported_claims.append(
            "FIPS link-estimator metrics remain semantically separate from SRT sender and receiver counters."
        )
        metric_non_claim = "FIPS loss_rate is not an SRT loss, drop, or retransmission counter."
    else:
        supported_claims.append(
            "The peer metric namespace remains semantically separate from SRT sender and receiver counters."
        )
        metric_non_claim = (
            "Peer metrics are not SRT loss, drop, or retransmission counters unless the source contract says so."
        )
    if outcome == "ordered":
        supported_claims.append(
            "The two event timestamps have the reported order under the declared clock contract."
        )
    else:
        supported_claims.append(
            "The available clock contract does not authorize a temporal order for the two events."
        )
    result = {
        "schema_version": 1,
        "analysis_id": analysis_id,
        "analysis_scope": "ordering-only",
        "inputs": {
            "srt": {
                "event_id": srt["event_id"],
                "sha256": srt_sha256,
                "route_epoch": srt["route_epoch"],
                "clock_domain": srt["clock"]["domain_id"],
            },
            "peer": {
                "event_id": peer["event_id"],
                "source": peer["source"],
                "sha256": peer_sha256,
                "route_epoch": peer["route_epoch"],
                "clock_domain": peer["clock"]["domain_id"],
            },
        },
        "clock_assessment": clock_assessment,
        "outcome": outcome,
        "ordering": ordering,
        "reason": reason,
        "metric_semantics_separate": True,
        "supported_claims": supported_claims,
        "non_claims": [
            "Temporal ordering alone does not identify the first divergent layer or a root cause.",
            metric_non_claim,
            "This assessment does not authorize route, SRT, encoder, or relay mutation.",
        ],
    }
    validate_g4_ordering_assessment(result)
    return result


def assess_cross_layer_ordering(
    srt_path: Path, peer_path: Path, output_path: Path
) -> dict[str, Any]:
    srt_path = srt_path.resolve()
    peer_path = peer_path.resolve()
    output_path = output_path.resolve()
    if len({srt_path, peer_path, output_path}) != 3:
        raise ContractError("SRT, peer, and output paths must be distinct")
    if output_path.exists():
        raise ContractError("ordering assessment output already exists")
    srt = load_json(srt_path)
    peer = load_json(peer_path)
    result = build_g4_ordering_assessment(
        srt,
        peer,
        srt_sha256=_sha256_file(srt_path),
        peer_sha256=_sha256_file(peer_path),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(result, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, output_path)
        except FileExistsError as exc:
            raise ContractError("ordering assessment output already exists") from exc
    except OSError as exc:
        raise ContractError(f"ordering assessment I/O failure: {exc}") from exc
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return result
