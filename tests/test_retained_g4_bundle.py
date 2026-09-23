from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from rimf_lab.contracts import ContractError
from rimf_lab.g4_srt_over_fips import validate_g4_live_capture_bundle


BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "qualification/retained-bundles/2026-09-23-g4-srt-over-fips-live-35857439840"
)


class RetainedG4BundleTests(unittest.TestCase):
    def test_committed_bundle_replays_and_validates(self):
        validate_g4_live_capture_bundle(BUNDLE)

    def test_changed_source_sample_breaks_retained_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "bundle"
            shutil.copytree(BUNDLE, copy)
            path = copy / "sender-source.jsonl"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ContractError, "digest/size mismatch"):
                validate_g4_live_capture_bundle(copy)
