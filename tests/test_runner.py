from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from rimf_lab.contracts import ContractError, validate_result
from rimf_lab.runner import run_scenario

from test_contracts import valid_baselines, valid_scenario


def valid_toolchain():
    return {
        "schema_version": 1,
        "as_of": "2026-08-29",
        "python": {"minimum": "3.11", "runtime_version_recorded_per_result": True},
        "ci": {
            "runner": "ubuntu-24.04",
            "retained_evidence_environment": False,
            "actions": [
                {
                    "repository": "https://github.com/actions/checkout.git",
                    "major": "v4",
                    "commit": "b" * 40,
                }
            ],
        },
    }


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "dependency-pins").mkdir()
        (self.root / "dependency-pins/baselines.json").write_text(
            json.dumps(valid_baselines()), encoding="utf-8"
        )
        (self.root / "dependency-pins/toolchain.json").write_text(
            json.dumps(valid_toolchain()), encoding="utf-8"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_scenario(self, scenario):
        path = self.root / "scenario.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        return path

    def test_run_records_digests_without_raw_output(self):
        scenario = valid_scenario()
        scenario["cases"][0]["command"] = [
            sys.executable,
            "-c",
            "import sys; print('public-marker'); print('error-marker', file=sys.stderr)",
        ]
        scenario_path = self.write_scenario(scenario)
        output_path = self.root / "result.json"

        result = run_scenario(scenario_path, output_path, self.root)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["classification"], "harness-only")
        self.assertGreater(result["cases"][0]["stdout"]["bytes"], 0)
        self.assertGreater(result["cases"][0]["stderr"]["bytes"], 0)
        serialized = output_path.read_text(encoding="utf-8")
        self.assertNotIn("public-marker", serialized)
        self.assertNotIn("error-marker", serialized)
        validate_result(json.loads(serialized))

    def test_expected_nonzero_exit_can_pass(self):
        scenario = valid_scenario()
        scenario["cases"][0]["command"] = [sys.executable, "-c", "raise SystemExit(7)"]
        scenario["cases"][0]["expected_exit_code"] = 7
        result = run_scenario(
            self.write_scenario(scenario), self.root / "result.json", self.root
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["cases"][0]["exit_code"], 7)

    def test_missing_executable_writes_failed_result(self):
        scenario = valid_scenario()
        scenario["cases"][0]["command"] = ["rimf-command-that-does-not-exist"]
        result = run_scenario(
            self.write_scenario(scenario), self.root / "result.json", self.root
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["cases"][0]["error"], "executable-not-found")

    def test_timeout_is_bounded_and_recorded(self):
        scenario = valid_scenario()
        scenario["cases"][0]["command"] = [
            sys.executable,
            "-c",
            "import time; time.sleep(5)",
        ]
        scenario["cases"][0]["timeout_seconds"] = 0.05
        result = run_scenario(
            self.write_scenario(scenario), self.root / "result.json", self.root
        )
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["cases"][0]["timed_out"])
        self.assertEqual(result["cases"][0]["error"], "timeout")

    def test_disabled_scenario_is_not_executed(self):
        scenario = valid_scenario()
        scenario["execution_enabled"] = False
        with self.assertRaisesRegex(ContractError, "execution is disabled"):
            run_scenario(
                self.write_scenario(scenario), self.root / "result.json", self.root
            )

    def test_scenario_cannot_be_overwritten_by_result(self):
        scenario_path = self.write_scenario(valid_scenario())
        with self.assertRaisesRegex(ContractError, "must differ"):
            run_scenario(scenario_path, scenario_path, self.root)


if __name__ == "__main__":
    unittest.main()
