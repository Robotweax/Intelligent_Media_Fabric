from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from rimf_lab.contracts import (
    ContractError,
    load_json,
    validate_baselines,
    validate_fips_source_assessment,
    validate_scenario,
    validate_toolchain,
)


def valid_baselines():
    return {
        "schema_version": 1,
        "as_of": "2026-08-29",
        "dependencies": [
            {
                "id": "dependency",
                "repository": "https://github.com/example/dependency.git",
                "commit": "a" * 40,
                "role": "test",
                "integration": "external",
                "evidence_class": "candidate",
            }
        ],
    }


def valid_scenario():
    return {
        "schema_version": 1,
        "scenario_id": "contract-test-v1",
        "description": "test",
        "classification": "harness-only",
        "execution_enabled": True,
        "gate_ids": ["G0-B"],
        "repetitions": 1,
        "cases": [
            {
                "case_id": "success-case",
                "command": ["python3", "-c", "pass"],
                "timeout_seconds": 10,
                "expected_exit_code": 0,
            }
        ],
    }


class BaselineContractTests(unittest.TestCase):
    def test_accepts_full_immutable_commit(self):
        validate_baselines(valid_baselines())

    def test_rejects_moving_commit_name(self):
        data = valid_baselines()
        data["dependencies"][0]["commit"] = "main"
        with self.assertRaisesRegex(ContractError, "40 lowercase hex"):
            validate_baselines(data)

    def test_rejects_duplicate_dependency(self):
        data = valid_baselines()
        data["dependencies"].append(dict(data["dependencies"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate dependency"):
            validate_baselines(data)


class ScenarioContractTests(unittest.TestCase):
    def test_accepts_argument_array(self):
        validate_scenario(valid_scenario())

    def test_rejects_shell_command_string(self):
        data = valid_scenario()
        data["cases"][0]["command"] = "python3 -c pass"
        with self.assertRaisesRegex(ContractError, "argument array"):
            validate_scenario(data)

    def test_rejects_secret_like_environment_name(self):
        data = valid_scenario()
        data["cases"][0]["environment"] = {"API_TOKEN": "must-not-be-here"}
        with self.assertRaisesRegex(ContractError, "secret-like"):
            validate_scenario(data)

    def test_disabled_template_may_contain_placeholder(self):
        data = valid_scenario()
        data["execution_enabled"] = False
        data["cases"][0]["command"] = ["REPLACE_WITH_PINNED_RUNNER"]
        validate_scenario(data)

    def test_enabled_scenario_rejects_placeholder(self):
        data = valid_scenario()
        data["cases"][0]["command"] = ["REPLACE_WITH_PINNED_RUNNER"]
        with self.assertRaisesRegex(ContractError, "placeholder"):
            validate_scenario(data)


class ToolchainContractTests(unittest.TestCase):
    def test_accepts_immutable_action_commit(self):
        data = {
            "schema_version": 1,
            "python": {"minimum": "3.11"},
            "ci": {
                "runner": "ubuntu-24.04",
                "actions": [
                    {
                        "repository": "https://github.com/actions/checkout.git",
                        "commit": "c" * 40,
                    }
                ],
            },
        }
        validate_toolchain(data)

    def test_rejects_moving_action_commit(self):
        data = {
            "schema_version": 1,
            "python": {"minimum": "3.11"},
            "ci": {
                "runner": "ubuntu-24.04",
                "actions": [
                    {
                        "repository": "https://github.com/actions/checkout.git",
                        "commit": "v4",
                    }
                ],
            },
        }
        with self.assertRaisesRegex(ContractError, "40 lowercase hex"):
            validate_toolchain(data)


class FipsAssessmentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assessment = load_json(
            Path(__file__).parents[1]
            / "qualification/retained-results/2026-08-29-fips-source-build-assessment-macos-arm64.json"
        )

    def test_accepts_retained_wp1_assessment(self):
        validate_fips_source_assessment(self.assessment)

    def test_rejects_unassessed_primary_candidate(self):
        data = deepcopy(self.assessment)
        data["decision"]["primary_candidate_id"] = "not-assessed"
        with self.assertRaisesRegex(ContractError, "not an assessed candidate"):
            validate_fips_source_assessment(data)

    def test_rejects_candidate_without_passing_test_attempt(self):
        data = deepcopy(self.assessment)
        data["candidates"][0]["tests"]["attempts"][0]["status"] = "failed"
        data["candidates"][0]["tests"]["attempts"][0]["failed"] = 1
        with self.assertRaisesRegex(ContractError, "requires a passing full test attempt"):
            validate_fips_source_assessment(data)

    def test_rejects_runtime_smoke_that_enables_tun(self):
        data = deepcopy(self.assessment)
        data["runtime_smoke"]["tun_enabled"] = True
        with self.assertRaisesRegex(ContractError, "tun_enabled"):
            validate_fips_source_assessment(data)


if __name__ == "__main__":
    unittest.main()
