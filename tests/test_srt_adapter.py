from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rimf_lab.contracts import (
    ContractError,
    validate_srt_adapter_golden_case,
    validate_srt_telemetry_observation,
)
from rimf_lab.srt_adapter import adapt_srt_telemetry_jsonl


ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "qualification/golden-cases/srt-adapter-v1"


class SrtTelemetryAdapterTests(unittest.TestCase):
    def test_golden_manifest_and_hashes_are_valid(self):
        validate_srt_adapter_golden_case(GOLDEN)

    def test_golden_output_is_byte_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "observations.jsonl"
            result = adapt_srt_telemetry_jsonl(
                GOLDEN / "source.jsonl", GOLDEN / "context.json", output
            )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["sample_count"], 1)
            self.assertEqual(
                output.read_bytes(), (GOLDEN / "expected-observations.jsonl").read_bytes()
            )
            observation = json.loads(output.read_text(encoding="utf-8"))
            validate_srt_telemetry_observation(observation)
            self.assertEqual(observation["quality"]["availability"], "partial")
            self.assertEqual(
                observation["quality"]["reason"], "first-sample-delta-baseline"
            )

    def test_refuses_to_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "observations.jsonl"
            output.write_text("preserve-me\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "already exists"):
                adapt_srt_telemetry_jsonl(
                    GOLDEN / "source.jsonl", GOLDEN / "context.json", output
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve-me\n")

    def test_count_mismatch_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            lines = (GOLDEN / "source.jsonl").read_text(encoding="utf-8").splitlines()
            header = json.loads(lines[0])
            header["recordCount"] = 2
            source = temporary / "source.jsonl"
            source.write_text(
                json.dumps(header, separators=(",", ":")) + "\n" + lines[1] + "\n",
                encoding="utf-8",
            )
            output = temporary / "observations.jsonl"
            with self.assertRaisesRegex(ContractError, "sample count"):
                adapt_srt_telemetry_jsonl(source, GOLDEN / "context.json", output)
            self.assertFalse(output.exists())

    def test_invalid_clock_context_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            context = json.loads((GOLDEN / "context.json").read_text(encoding="utf-8"))
            context["clock"]["cross_host_ordering_allowed"] = True
            context_path = temporary / "context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            output = temporary / "observations.jsonl"
            with self.assertRaisesRegex(ContractError, "cannot authorize cross-host ordering"):
                adapt_srt_telemetry_jsonl(GOLDEN / "source.jsonl", context_path, output)
            self.assertFalse(output.exists())

    def test_inconsistent_counter_reset_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            lines = (GOLDEN / "source.jsonl").read_text(encoding="utf-8").splitlines()
            sample = json.loads(lines[1])
            sample["delta"]["counter_reset_fields"] = 1
            source = temporary / "source.jsonl"
            source.write_text(
                lines[0] + "\n" + json.dumps(sample, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            output = temporary / "observations.jsonl"
            with self.assertRaisesRegex(ContractError, "counter-reset"):
                adapt_srt_telemetry_jsonl(source, GOLDEN / "context.json", output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
