from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from rimf_lab.contracts import ContractError, validate_g4_clock_domain_golden_case
from rimf_lab.cross_layer import assess_cross_layer_ordering, build_g4_ordering_assessment


ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "qualification/golden-cases/g4-clock-domain-boundary-v1"
ZERO_DIGEST = "0" * 64


class CrossLayerOrderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srt = json.loads((GOLDEN / "srt-observation.json").read_text(encoding="utf-8"))
        cls.peer = json.loads((GOLDEN / "fips-observation.json").read_text(encoding="utf-8"))

    def test_golden_manifest_and_hashes_are_valid(self):
        validate_g4_clock_domain_golden_case(GOLDEN)

    def test_golden_assessment_is_byte_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assessment.json"
            result = assess_cross_layer_ordering(
                GOLDEN / "srt-observation.json",
                GOLDEN / "fips-observation.json",
                output,
            )
            self.assertEqual(result["outcome"], "insufficient-evidence")
            self.assertEqual(result["reason"], "clock-domains-not-comparable")
            self.assertEqual(
                output.read_bytes(), (GOLDEN / "expected-assessment.json").read_bytes()
            )

    def test_same_monotonic_domain_authorizes_only_temporal_order(self):
        peer = deepcopy(self.peer)
        peer["clock"] = deepcopy(self.srt["clock"])
        peer["monotonic_ns"] = self.srt["monotonic_ns"] + 1
        result = build_g4_ordering_assessment(
            self.srt, peer, srt_sha256=ZERO_DIGEST, peer_sha256="1" * 64
        )
        self.assertEqual(result["outcome"], "ordered")
        self.assertEqual(result["ordering"], "srt-before-peer")
        self.assertEqual(result["reason"], "shared-monotonic-order")
        self.assertIn("does not identify", result["non_claims"][0])

    def test_bounded_wall_clock_overlap_remains_unknown(self):
        srt = deepcopy(self.srt)
        peer = deepcopy(self.peer)
        for observation in (srt, peer):
            observation["clock"] = {
                "domain_id": f"{observation['source']}-ntp-domain",
                "synchronization": "ntp",
                "max_error_ns": 2_000_000,
                "cross_host_ordering_allowed": True,
            }
        observed_seconds = srt["observed_at_unix_nano"] / 1_000_000_000
        peer["observed_at"] = datetime.fromtimestamp(
            observed_seconds, tz=timezone.utc
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        result = build_g4_ordering_assessment(
            srt, peer, srt_sha256=ZERO_DIGEST, peer_sha256="1" * 64
        )
        self.assertEqual(result["outcome"], "insufficient-evidence")
        self.assertEqual(result["reason"], "clock-uncertainty-overlap")
        self.assertEqual(result["ordering"], "unknown")

    def test_bounded_wall_clock_preserves_nanosecond_precision(self):
        srt = deepcopy(self.srt)
        peer = deepcopy(self.peer)
        srt["clock"] = {
            "domain_id": "srt-ptp-domain",
            "synchronization": "ptp",
            "max_error_ns": 0,
            "cross_host_ordering_allowed": True,
        }
        peer["clock"] = {
            "domain_id": "fips-ptp-domain",
            "synchronization": "ptp",
            "max_error_ns": 0,
            "cross_host_ordering_allowed": True,
        }
        peer["observed_at"] = "2027-01-15T08:00:01.000000001Z"
        result = build_g4_ordering_assessment(
            srt, peer, srt_sha256=ZERO_DIGEST, peer_sha256="1" * 64
        )
        self.assertEqual(result["outcome"], "ordered")
        self.assertEqual(result["reason"], "bounded-wall-clock-order")
        self.assertEqual(result["ordering"], "srt-before-peer")

    def test_route_epoch_mismatch_precedes_clock_inference(self):
        peer = deepcopy(self.peer)
        peer["route_epoch"] += 1
        result = build_g4_ordering_assessment(
            self.srt, peer, srt_sha256=ZERO_DIGEST, peer_sha256="1" * 64
        )
        self.assertEqual(result["outcome"], "insufficient-evidence")
        self.assertEqual(result["reason"], "route-epoch-mismatch")

    def test_rejects_cross_namespace_metric_disguise(self):
        peer = deepcopy(self.peer)
        peer["payload"]["metric_namespace"] = "srt.transport"
        with self.assertRaisesRegex(ContractError, "must begin with 'fips\\.'"):
            build_g4_ordering_assessment(
                self.srt, peer, srt_sha256=ZERO_DIGEST, peer_sha256="1" * 64
            )

    def test_rejects_non_finite_peer_metric(self):
        peer = deepcopy(self.peer)
        peer["payload"]["loss_rate"] = float("nan")
        with self.assertRaisesRegex(ContractError, "non-finite"):
            build_g4_ordering_assessment(
                self.srt, peer, srt_sha256=ZERO_DIGEST, peer_sha256="1" * 64
            )

    def test_refuses_to_overwrite_existing_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assessment.json"
            output.write_text("preserve-me\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "already exists"):
                assess_cross_layer_ordering(
                    GOLDEN / "srt-observation.json",
                    GOLDEN / "fips-observation.json",
                    output,
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve-me\n")


if __name__ == "__main__":
    unittest.main()
