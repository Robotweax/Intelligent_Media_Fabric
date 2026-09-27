from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from rimf_lab.contracts import ContractError
from rimf_lab.g4_srt_over_fips import (
    EXPECTED_SRT_COMMIT,
    validate_g4_live_capture_bundle,
)


BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "qualification/retained-bundles/2026-09-23-g4-srt-over-fips-live-35857439840"
)
SRT_026_BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "qualification/retained-bundles/2026-09-27-g4-srt-over-fips-live-36309262514"
)


class RetainedG4BundleTests(unittest.TestCase):
    @staticmethod
    def _rewrite_bundle_json(copy: Path, name: str, value: dict, result: dict) -> None:
        path = copy / name
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        content = path.read_bytes()
        result["files"][name] = {
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        (copy / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_committed_bundle_replays_and_validates(self):
        validate_g4_live_capture_bundle(BUNDLE)
        validate_g4_live_capture_bundle(SRT_026_BUNDLE)

    def test_new_bundle_rejects_mismatched_provider_version(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "bundle"
            shutil.copytree(SRT_026_BUNDLE, copy)
            source_path = copy / "sender-source.jsonl"
            lines = source_path.read_text(encoding="utf-8").splitlines()
            recording = json.loads(lines[0])
            recording["providerVersion"] = "0.2.4"
            lines[0] = json.dumps(recording, separators=(",", ":"))
            source_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result_path = copy / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            content = source_path.read_bytes()
            result["files"]["sender-source.jsonl"] = {
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            result_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ContractError, "provider identity"):
                validate_g4_live_capture_bundle(copy)

    def test_changed_source_sample_breaks_retained_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "bundle"
            shutil.copytree(BUNDLE, copy)
            path = copy / "sender-source.jsonl"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ContractError, "digest/size mismatch"):
                validate_g4_live_capture_bundle(copy)

    def test_new_pin_cannot_relabel_old_provider_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "bundle"
            shutil.copytree(BUNDLE, copy)
            result_path = copy / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["provenance"]["srt_commit"] = EXPECTED_SRT_COMMIT
            result_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ContractError, "provider identity"):
                validate_g4_live_capture_bundle(copy)

    def test_rejects_rewritten_ordering_even_with_updated_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "bundle"
            shutil.copytree(BUNDLE, copy)
            result = json.loads((copy / "result.json").read_text(encoding="utf-8"))
            name = "srt-fips-ordering.json"
            assessment = json.loads((copy / name).read_text(encoding="utf-8"))
            assessment["ordering"] = "peer-before-srt"
            result["capture"]["srt_fips_ordering"] = "peer-before-srt"
            self._rewrite_bundle_json(copy, name, assessment, result)
            with self.assertRaisesRegex(ContractError, "historical G4 result digest mismatch"):
                validate_g4_live_capture_bundle(copy)

    def test_rejects_rewritten_media_count_even_with_updated_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "bundle"
            shutil.copytree(BUNDLE, copy)
            result = json.loads((copy / "result.json").read_text(encoding="utf-8"))
            name = "media-observation.json"
            media = json.loads((copy / name).read_text(encoding="utf-8"))
            media["payload"]["message_count"] -= 1
            self._rewrite_bundle_json(copy, name, media, result)
            with self.assertRaisesRegex(ContractError, "historical G4 result digest mismatch"):
                validate_g4_live_capture_bundle(copy)
