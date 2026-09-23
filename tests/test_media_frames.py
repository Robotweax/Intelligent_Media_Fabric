from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rimf_lab.cli import main
from rimf_lab.contracts import ContractError
from rimf_lab.media_frames import (
    assess_media_frames,
    parse_framehash,
    write_media_frame_assessment,
)


def recording(frames: list[tuple[int, str]], time_base: str = "1/25") -> str:
    header = (
        "#format: frame checksums\n"
        "#version: 2\n"
        "#hash: SHA256\n"
        f"#tb 0: {time_base}\n"
        "#media_type 0: video\n"
        "#stream#, dts, pts, duration, size, hash\n"
    )
    return header + "".join(
        f"0, {pts}, {pts}, 1, 21600, {digest}\n" for pts, digest in frames
    )


class MediaFrameComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reference = self.root / "reference.framehash"
        self.observed = self.root / "observed.framehash"
        self.reference.write_text(
            recording([(0, "a" * 64), (1, "b" * 64), (2, "c" * 64)]),
            encoding="utf-8",
        )

    def test_exact_decoded_frames_do_not_claim_g4_passage(self):
        self.observed.write_text(self.reference.read_text(encoding="utf-8"), encoding="utf-8")
        result = assess_media_frames(self.reference, self.observed)
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["expected_frames"], 3)
        self.assertEqual(result["missing_frames"], 0)
        self.assertEqual(result["gate_conclusion"]["G4"], "not-passed")

    def test_records_missing_unexpected_and_changed_frames(self):
        self.observed.write_text(
            recording([(0, "a" * 64), (2, "d" * 64), (3, "e" * 64)]),
            encoding="utf-8",
        )
        result = assess_media_frames(self.reference, self.observed)
        self.assertEqual(result["status"], "diverged")
        self.assertEqual(result["missing_frames"], 1)
        self.assertEqual(result["unexpected_frames"], 1)
        self.assertEqual(result["changed_frames"], 1)
        self.assertEqual(result["max_consecutive_missing_frames"], 1)
        self.assertEqual(result["first_missing_pts"], 1)
        self.assertEqual(result["first_changed_pts"], 2)

    def test_duplicate_pts_is_rejected(self):
        self.observed.write_text(
            recording([(0, "a" * 64), (0, "b" * 64)]), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "duplicate presentation"):
            parse_framehash(self.observed)

    def test_wrong_hash_algorithm_is_rejected(self):
        self.observed.write_text(
            recording([(0, "a" * 64)]).replace("#hash: SHA256", "#hash: MD5"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContractError, "unsupported stream or hash"):
            parse_framehash(self.observed)

    def test_timebase_change_is_not_silently_rescaled(self):
        self.observed.write_text(recording([(0, "a" * 64)], "1/50"), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "time bases differ"):
            assess_media_frames(self.reference, self.observed)

    def test_output_is_exclusive_and_cli_returns_divergence(self):
        self.observed.write_text(recording([(0, "a" * 64)]), encoding="utf-8")
        output = self.root / "assessment.json"
        self.assertEqual(
            main([
                "assess-media-framehash",
                "--reference", str(self.reference),
                "--observed", str(self.observed),
                "--output", str(output),
            ]),
            1,
        )
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "diverged")
        with self.assertRaisesRegex(ContractError, "already exists"):
            write_media_frame_assessment(self.reference, self.observed, output)
