from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from rimf_lab.contracts import ContractError
from rimf_lab.fips_g2_linux import QualificationError
from rimf_lab.g4_srt_over_fips import (
    ACTIVE_SAMPLE_COUNT,
    EXPECTED_BUNDLE_FILES,
    EXPECTED_SRT_COMMIT,
    EXPECTED_TELEMETRY_COMMIT,
    MESSAGE_BYTES,
    MESSAGE_COUNT,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
    run_g4_srt_over_fips_live,
    validate_g4_live_capture_bundle,
    validate_g4_live_capture_result,
)


def failure_result() -> dict:
    return {
        "schema_version": 1,
        "evidence_type": "g4-srt-over-fips-live",
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G3", "G4"],
        "run_id": "11111111-1111-4111-8111-111111111111",
        "started_at": "2026-08-30T00:00:00Z",
        "finished_at": "2026-08-30T00:00:01Z",
        "project_revision": "0" * 40,
        "failure_phase": "preflight",
        "failure_class": "QualificationError",
        "failure_detail": "expected failure",
        "cleanup": {
            "srt_peers_stopped": True,
            "fips_daemons_stopped": True,
            "namespaces_removed": True,
            "ephemeral_identity_directory_removed": True,
        },
        "gate_conclusion": {
            "G3": "not-passed",
            "G4": "not-passed",
            "reason": "live-capture-failed",
        },
    }


def success_result() -> dict:
    result = failure_result()
    for field in (
        "project_revision",
        "failure_phase",
        "failure_class",
        "failure_detail",
    ):
        del result[field]
    result.update(
        {
            "status": "passed",
            "provenance": {
                "fips_repository": "https://github.com/jmcorgan/fips.git",
                "fips_commit": "c5aeef39ef9442d9e5047331156df368ace40cbd",
                "fips_source_tree_state": "clean",
                "cargo_lock_sha256": "0" * 64,
                "rust_toolchain_sha256": "0" * 64,
                "project_revision": "0" * 40,
                "srt_repository": SRT_REPOSITORY,
                "srt_commit": EXPECTED_SRT_COMMIT,
                "srt_library_sha256": "0" * 64,
                "telemetry_repository": TELEMETRY_REPOSITORY,
                "telemetry_commit": EXPECTED_TELEMETRY_COMMIT,
                "incident_peer_sha256": "0" * 64,
                "fips_binary_sha256": "0" * 64,
                "fipsctl_binary_sha256": "0" * 64,
            },
            "platform": {},
            "clock": {
                "domain_id": "linux-host-monotonic-test",
                "synchronization": "local-only",
                "max_error_ns": None,
                "cross_host_ordering_allowed": False,
                "same_host": True,
            },
            "route_epoch": 1,
            "topology": {},
            "capture": {
                "srt_samples_per_endpoint": ACTIVE_SAMPLE_COUNT + 2,
                "fips_observation_count": ACTIVE_SAMPLE_COUNT + 2,
                "sample_interval_ns": 100_000_000,
                "application_message_count": MESSAGE_COUNT,
                "application_message_bytes": MESSAGE_BYTES,
                "application_exact_delivery": True,
                "srt_fips_ordering": "srt-before-peer",
                "srt_media_ordering": "srt-before-peer",
            },
            "files": {
                name: {"bytes": 1, "sha256": "0" * 64}
                for name in EXPECTED_BUNDLE_FILES
            },
            "gate_conclusion": {
                "G3": "not-passed",
                "G4": "not-passed",
                "reason": "single-healthy-live-pilot-without-fault-or-route-transition",
            },
            "limitations": ["one", "two", "three"],
        }
    )
    return result


class G4SrtOverFipsContractTests(unittest.TestCase):
    def test_accepts_fail_closed_failure_result(self):
        validate_g4_live_capture_result(failure_result())

    def test_accepts_fail_closed_failure_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(
                json.dumps(failure_result(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            validate_g4_live_capture_bundle(Path(directory))

    def test_accepts_successful_experiment_without_gate_passage(self):
        validate_g4_live_capture_result(success_result())

    def test_rejects_gate_passage_claim(self):
        result = success_result()
        result["gate_conclusion"]["G4"] = "passed"
        with self.assertRaisesRegex(ContractError, "must not claim"):
            validate_g4_live_capture_result(result)

    def test_rejects_incomplete_cleanup_on_success(self):
        result = success_result()
        result["cleanup"]["namespaces_removed"] = False
        with self.assertRaisesRegex(ContractError, "complete cleanup"):
            validate_g4_live_capture_result(result)

    def test_rejects_missing_application_delivery(self):
        result = success_result()
        result["capture"]["application_exact_delivery"] = False
        with self.assertRaisesRegex(ContractError, "capture summary"):
            validate_g4_live_capture_result(result)

    def test_non_linux_preflight_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture"
            with patch("rimf_lab.g4_srt_over_fips.platform.system", return_value="Darwin"):
                with self.assertRaisesRegex(QualificationError, "requires Linux"):
                    run_g4_srt_over_fips_live(
                        fips_source=Path("missing"),
                        fips_binary=Path("missing"),
                        fipsctl_binary=Path("missing"),
                        srt_source=Path("missing"),
                        srt_library=Path("missing"),
                        telemetry_source=Path("missing"),
                        incident_peer=Path("missing"),
                        library_dir=Path("missing"),
                        output_dir=output,
                        project_revision="0" * 40,
                    )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
