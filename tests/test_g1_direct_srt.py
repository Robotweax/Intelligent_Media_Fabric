from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from rimf_lab.contracts import ContractError
from rimf_lab.g1_direct_srt import (
    ACTIVE_SAMPLE_COUNT,
    DEVICE_ID,
    EXPECTED_SRT_COMMIT,
    EXPECTED_TELEMETRY_COMMIT,
    HISTORICAL_G1_BUNDLES,
    MESSAGE_BYTES,
    MESSAGE_COUNT,
    RECORDED_COUNTERS,
    REPETITION_FILES,
    SAMPLE_INTERVAL_NS,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
    _summary,
    validate_g1_direct_srt_bundle,
    validate_g1_direct_srt_result,
)
from rimf_lab.g4_srt_over_fips import HISTORICAL_G4_BUNDLES


RUN_ID = "0f3f2b4e-5d7a-4a0b-9c1d-2e3f4a5b6c7d"


def endpoint(role: str) -> dict:
    counters = {name: 0 for name in RECORDED_COUNTERS}
    if role == "sender":
        counters.update(
            sent_packet_total=MESSAGE_COUNT + 3,
            unique_sent_packet_total=MESSAGE_COUNT + 3,
            sent_wire_byte_total=(MESSAGE_COUNT + 3) * 1072,
        )
    else:
        counters.update(
            received_packet_total=MESSAGE_COUNT + 3,
            unique_received_packet_total=MESSAGE_COUNT + 3,
            received_wire_byte_total=(MESSAGE_COUNT + 3) * 1072,
        )
    return {
        **counters,
        "rtt_seconds_min": 0.0001,
        "rtt_seconds_max": 0.0012,
        "cpu_user_ms": 40,
        "cpu_system_ms": 20,
        "peak_rss_kib": 12_000,
        "accounting": "procfs-before-exit",
    }


def repetition(index: int) -> dict:
    errors = [1_000 * index + 10 * sample for sample in range(ACTIVE_SAMPLE_COUNT)]
    return {
        "index": index,
        "flow_id": f"g1-{RUN_ID}-{index}",
        "application_exact_delivery": True,
        "srt_samples_per_endpoint": ACTIVE_SAMPLE_COUNT + 2,
        "sampling": {
            "missed_intervals": 0,
            "schedule_error_ns": errors,
            "max_abs_schedule_error_ns": max(abs(value) for value in errors),
        },
        "receiver_complete_sample_index": 12,
        "transfer_confirmed_after_ms": 1_250 + index,
        "endpoints": {"sender": endpoint("sender"), "receiver": endpoint("receiver")},
        "srt_media_ordering": "srt-before-peer",
    }


def success_result(repetitions: int = 3) -> dict:
    reps = [repetition(index) for index in range(1, repetitions + 1)]
    return {
        "schema_version": 1,
        "evidence_type": "g1-direct-srt-baseline",
        "status": "passed",
        "classification": "experiment",
        "gate_ids": ["G1"],
        "run_id": RUN_ID,
        "started_at": "2026-10-22T16:00:00Z",
        "finished_at": "2026-10-22T16:01:00Z",
        "provenance": {
            "project_revision": "0" * 40,
            "srt_repository": SRT_REPOSITORY,
            "srt_commit": EXPECTED_SRT_COMMIT,
            "srt_library_sha256": "0" * 64,
            "telemetry_repository": TELEMETRY_REPOSITORY,
            "telemetry_commit": EXPECTED_TELEMETRY_COMMIT,
            "incident_peer_sha256": "0" * 64,
        },
        "platform": {"system": "Linux", "release": "test", "machine": "x86_64", "python": "3.12"},
        "clock": {
            "domain_id": "linux-host-monotonic-" + "a" * 24,
            "synchronization": "local-only",
            "max_error_ns": None,
            "cross_host_ordering_allowed": False,
            "same_host": True,
        },
        "route_epoch": 1,
        "topology": {
            "node_count": 2,
            "isolation": "linux-network-namespaces",
            "underlay": "direct-veth-ipv6",
            "overlay": "none",
            "link_mtu": 1500,
        },
        "workload": {
            "application_message_count": MESSAGE_COUNT,
            "application_message_bytes": MESSAGE_BYTES,
            "send_pacing_microseconds": 5_000,
            "sample_interval_ns": SAMPLE_INTERVAL_NS,
            "active_sample_count": ACTIVE_SAMPLE_COUNT,
            "repetitions": repetitions,
        },
        "repetitions": reps,
        "summary": _summary(reps),
        "files": {
            f"rep-{index}/{name}": {"bytes": 1, "sha256": "0" * 64}
            for index in range(1, repetitions + 1)
            for name in REPETITION_FILES
        },
        "cleanup": {
            "srt_peers_stopped": True,
            "namespaces_removed": True,
            "work_directory_removed": True,
        },
        "gate_conclusion": {"G1": "not-passed", "reason": "single-run-direct-control-evidence"},
        "limitations": ["a", "b", "c", "d"],
    }


def failure_result() -> dict:
    return {
        "schema_version": 1,
        "evidence_type": "g1-direct-srt-baseline",
        "status": "failed",
        "classification": "experiment",
        "gate_ids": ["G1"],
        "run_id": RUN_ID,
        "started_at": "2026-10-22T16:00:00Z",
        "finished_at": "2026-10-22T16:00:30Z",
        "project_revision": "0" * 40,
        "failure_phase": "repetition-2-capture",
        "failure_class": "QualificationError",
        "failure_detail": "G1 SRT sampling missed a complete 100 ms interval",
        "completed_repetitions": 1,
        "cleanup": {
            "srt_peers_stopped": True,
            "namespaces_removed": True,
            "work_directory_removed": True,
        },
        "gate_conclusion": {"G1": "not-passed", "reason": "experiment-failed-before-completion"},
    }


class G1DirectSrtResultTests(unittest.TestCase):
    def test_accepts_repeated_direct_control_without_gate_passage(self):
        validate_g1_direct_srt_result(success_result())
        validate_g1_direct_srt_result(success_result(repetitions=1))

    def test_accepts_failed_result_with_completed_repetition_count(self):
        validate_g1_direct_srt_result(failure_result())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(failure_result()) + "\n", encoding="utf-8")
            validate_g1_direct_srt_bundle(Path(directory))

    def test_rejects_gate_passage_claim(self):
        result = success_result()
        result["gate_conclusion"]["G1"] = "passed"
        with self.assertRaisesRegex(ContractError, "not-passed"):
            validate_g1_direct_srt_result(result)

    def test_rejects_dropped_application_packets(self):
        result = success_result()
        result["repetitions"][1]["endpoints"]["receiver"]["receiver_drop_packet_total"] = 1
        with self.assertRaisesRegex(ContractError, "dropped application packets"):
            validate_g1_direct_srt_result(result)

    def test_rejects_missed_or_overlong_sampling_interval(self):
        result = success_result()
        result["repetitions"][0]["sampling"]["missed_intervals"] = 1
        with self.assertRaisesRegex(ContractError, "sampling record"):
            validate_g1_direct_srt_result(result)
        result = success_result()
        sampling = result["repetitions"][0]["sampling"]
        sampling["schedule_error_ns"][3] = SAMPLE_INTERVAL_NS
        sampling["max_abs_schedule_error_ns"] = SAMPLE_INTERVAL_NS
        with self.assertRaisesRegex(ContractError, "sampling record"):
            validate_g1_direct_srt_result(result)

    def test_rejects_summary_that_disagrees_with_repetitions(self):
        result = success_result()
        result["summary"]["sender_retransmitted_packet_total_range"] = [0, 99]
        with self.assertRaisesRegex(ContractError, "summary"):
            validate_g1_direct_srt_result(result)

    def test_rejects_repetition_count_mismatch_and_incomplete_inventory(self):
        result = success_result()
        result["repetitions"].pop()
        with self.assertRaisesRegex(ContractError, "declared workload"):
            validate_g1_direct_srt_result(result)
        result = success_result()
        result["summary"] = _summary(result["repetitions"])
        del result["files"]["rep-2/media-observation.json"]
        with self.assertRaisesRegex(ContractError, "file inventory"):
            validate_g1_direct_srt_result(result)

    def test_rejects_recorded_values_as_thresholded_pass_only_for_correctness(self):
        # Retransmissions and loss are recorded, not judged: a result with them passes.
        result = success_result()
        result["repetitions"][0]["endpoints"]["sender"]["retransmitted_packet_total"] = 7
        result["repetitions"][0]["endpoints"]["receiver"]["receiver_loss_packet_total"] = 7
        result["summary"] = _summary(result["repetitions"])
        validate_g1_direct_srt_result(result)

    def test_rejects_historical_srt_pin_as_active_control(self):
        for historical in HISTORICAL_G4_BUNDLES.values():
            result = success_result()
            result["provenance"]["srt_commit"] = historical["srt_commit"]
            with self.assertRaisesRegex(ContractError, "srt_commit"):
                validate_g1_direct_srt_result(result)

    def test_rejects_historical_g1_pin_as_active_control(self):
        for historical in HISTORICAL_G1_BUNDLES.values():
            result = success_result()
            result["provenance"]["srt_commit"] = historical["srt_commit"]
            with self.assertRaisesRegex(ContractError, "srt_commit"):
                validate_g1_direct_srt_result(result)

    def test_rejects_rewritten_historical_g1_bundle(self):
        historical = next(iter(HISTORICAL_G1_BUNDLES.values()))
        result = success_result(repetitions=1)
        result["provenance"]["srt_commit"] = historical["srt_commit"]
        result["provenance"]["telemetry_commit"] = historical["telemetry_commit"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "digest mismatch"):
                validate_g1_direct_srt_bundle(Path(directory))

    def test_rejects_flow_identity_drift(self):
        result = success_result()
        result["repetitions"][2]["flow_id"] = f"g1-{RUN_ID}-9"
        with self.assertRaisesRegex(ContractError, "identity"):
            validate_g1_direct_srt_result(result)

    def test_rejects_wrong_topology_or_workload(self):
        result = success_result()
        result["topology"]["overlay"] = "srt-ipv6-over-fips0"
        with self.assertRaisesRegex(ContractError, "topology"):
            validate_g1_direct_srt_result(result)
        result = success_result()
        result["workload"]["application_message_count"] = MESSAGE_COUNT - 1
        with self.assertRaisesRegex(ContractError, "workload"):
            validate_g1_direct_srt_result(result)

    def test_bundle_validator_requires_media_identity(self):
        result = success_result(repetitions=1)
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            rep = bundle / "rep-1"
            rep.mkdir()
            for name in REPETITION_FILES:
                (rep / name).write_text("{}\n", encoding="utf-8")
            result["files"] = {
                f"rep-1/{name}": {
                    "bytes": (rep / name).stat().st_size,
                    "sha256": __import__("hashlib").sha256((rep / name).read_bytes()).hexdigest(),
                }
                for name in REPETITION_FILES
            }
            (bundle / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "provider identity|JSONL|source"):
                validate_g1_direct_srt_bundle(bundle)
        self.assertEqual(DEVICE_ID, "two-node-direct-control")


if __name__ == "__main__":
    unittest.main()
