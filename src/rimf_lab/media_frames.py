"""Bounded, fail-closed comparison of independent FFmpeg decoded-frame hashes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import ContractError


MAX_FRAMEHASH_BYTES = 2_000_000
MAX_FRAMES = 6_000
_TIME_BASE = re.compile(r"#tb 0: ([1-9][0-9]*)/([1-9][0-9]*)")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_COLUMNS = re.compile(r"#stream#,\s*dts,\s*pts,\s*duration,\s*size,\s*hash")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_framehash(path: Path) -> tuple[str, dict[int, tuple[int, int, str]]]:
    """Parse one video stream of FFmpeg framehash/SHA256 output, keyed by PTS."""
    try:
        if path.stat().st_size > MAX_FRAMEHASH_BYTES:
            raise ContractError("framehash recording exceeds its byte limit")
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot read framehash recording: {exc}") from exc
    time_base: str | None = None
    hash_declared = False
    video_declared = False
    column_header = False
    frames: dict[int, tuple[int, int, str]] = {}
    for line in lines:
        if line.startswith("#"):
            match = _TIME_BASE.fullmatch(line.strip())
            if match:
                if time_base is not None:
                    raise ContractError("framehash has duplicate time-base metadata")
                time_base = f"{match.group(1)}/{match.group(2)}"
            elif line.strip() == "#hash: SHA256":
                if hash_declared:
                    raise ContractError("framehash has duplicate hash metadata")
                hash_declared = True
            elif line.strip() == "#media_type 0: video":
                video_declared = True
            elif _COLUMNS.fullmatch(line.strip()):
                column_header = True
            elif line.startswith("#tb ") or line.startswith("#hash:") or line.startswith("#media_type "):
                raise ContractError("framehash has unsupported stream or hash metadata")
            continue
        if not line.strip():
            continue
        columns = [part.strip() for part in line.split(",")]
        if len(columns) != 6 or columns[0] != "0":
            raise ContractError("framehash requires exactly one video stream")
        try:
            pts = int(columns[2])
            duration = int(columns[3])
            size = int(columns[4])
        except ValueError as exc:
            raise ContractError("framehash frame timing or size is invalid") from exc
        if duration < 0 or size <= 0 or not _SHA256.fullmatch(columns[5]):
            raise ContractError("framehash frame duration, size or SHA256 is invalid")
        if pts in frames:
            raise ContractError("framehash contains a duplicate presentation timestamp")
        frames[pts] = (duration, size, columns[5].lower())
        if len(frames) > MAX_FRAMES:
            raise ContractError("framehash recording exceeds its frame limit")
    if not (time_base and hash_declared and video_declared and column_header and frames):
        raise ContractError("framehash is missing required SHA256 video metadata or frames")
    return time_base, frames


def assess_media_frames(reference: Path, observed: Path) -> dict[str, Any]:
    """Compare decoded frames without inferring a cause or a G4 gate result."""
    reference = reference.resolve()
    observed = observed.resolve()
    if reference == observed:
        raise ContractError("reference and observed framehash paths must differ")
    reference_base, expected = parse_framehash(reference)
    observed_base, actual = parse_framehash(observed)
    if reference_base != observed_base:
        raise ContractError("framehash time bases differ; implicit rescaling is forbidden")

    missing = sorted(expected.keys() - actual.keys())
    unexpected = sorted(actual.keys() - expected.keys())
    changed = sorted(
        pts for pts in expected.keys() & actual.keys() if expected[pts] != actual[pts]
    )
    size_changed = sum(expected[pts][1] != actual[pts][1] for pts in changed)
    missing_set = set(missing)
    max_missing_run = 0
    current_run = 0
    for pts in sorted(expected):
        current_run = current_run + 1 if pts in missing_set else 0
        max_missing_run = max(max_missing_run, current_run)
    exact = not (missing or unexpected or changed)
    return {
        "schema_version": 1,
        "evidence_type": "decoded-media-frame-comparison",
        "classification": "observer-component",
        "status": "exact" if exact else "diverged",
        "time_base": reference_base,
        "expected_frames": len(expected),
        "observed_frames": len(actual),
        "missing_frames": len(missing),
        "unexpected_frames": len(unexpected),
        "changed_frames": len(changed),
        "size_changed_frames": size_changed,
        "max_consecutive_missing_frames": max_missing_run,
        "first_missing_pts": missing[0] if missing else None,
        "first_unexpected_pts": unexpected[0] if unexpected else None,
        "first_changed_pts": changed[0] if changed else None,
        "reference_sha256": _digest(reference),
        "observed_sha256": _digest(observed),
        "gate_conclusion": {"G4": "not-passed", "reason": "observer-only-no-fault-causality"},
    }


def write_media_frame_assessment(
    reference: Path, observed: Path, output: Path
) -> dict[str, Any]:
    """Publish one bounded assessment without replacing an existing artifact."""
    result = assess_media_frames(reference, observed)
    output = output.resolve()
    if output.exists():
        raise ContractError("media frame assessment output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_name, output)
        except FileExistsError as exc:
            raise ContractError("media frame assessment output already exists") from exc
    except OSError as exc:
        raise ContractError(f"media frame assessment I/O failure: {exc}") from exc
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return result
