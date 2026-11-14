from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from rimf_lab.contracts import ContractError
from rimf_lab.fips_g2_linux import QualificationError
from rimf_lab.g4_faulted_diamond import (
    DATAGRAM_BYTES,
    DECODE_OPTIONS,
    EXPECTED_FFMPEG_VERSION,
    FIXTURE_ENCODE,
    FIXTURE_FRAMES,
    INJECT_AFTER_SOURCE_START_NS,
)
from rimf_lab.g4_srt_over_fips import (
    EXPECTED_SRT_COMMIT,
    EXPECTED_TELEMETRY_COMMIT,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
)
from rimf_lab.g5_srt_group import (
    BUNDLE_FILES,
    CLEANUP_FIELDS,
    MEMBER_LOCAL_ADDRESSES,
    MEMBER_REMOTE_ADDRESSES,
    MEMBER_WEIGHTS,
    SRT_PEER_IDLE_TIMEOUT_MS,
    compute_group_timeline,
    group_member_record,
    member_event_namespace,
    member_wire,
    run_g5_srt_group,
    validate_g5_srt_group_result,
)

MS = 1_000_000
INJECT = 100_000 * MS


def fault(event: str, moment: int) -> dict:
    return {"source": "fabric", "monotonic_ns": moment, "payload": {"event": event}}


def observation(offset_ms: int, **delta: int) -> dict:
    return {"monotonic_ns": INJECT + offset_ms * MS, "payload": {"sample": {"raw": {}, "delta": delta}}}


def group_sample(role: str, offset_ms: int, *states: str) -> dict:
    return {"role": role, "monotonic_ns": INJECT + offset_ms * MS,
            "members": [{"index": index, "state": state, "sampled": state != "removed"}
                        for index, state in enumerate(states)]}


def series(standby_sent=(0, 0, 0, 40, 56)) -> dict:
    offsets = (-500, 0, 500, 1000, 1500)
    return {
        "fault_events": [fault("blackhole-start", INJECT), fault("blackhole-applied", INJECT + 9 * MS)],
        "group_samples": [
            *(group_sample("sender", offset, "running", "idle") for offset in offsets),
            group_sample("sender", 5500, "removed", "running"),
            *(group_sample("receiver", offset, "running", "idle") for offset in offsets),
            group_sample("receiver", 5500, "broken", "running"),
        ],
        "observations": {
            "sender": [
                [observation(offset, unique_sent_packet_delta=56) for offset in offsets],
                [observation(offset, unique_sent_packet_delta=value)
                 for offset, value in zip(offsets, standby_sent)],
            ],
            "receiver": [
                [observation(offset, unique_received_packet_delta=value)
                 for offset, value in zip(offsets, (56, 56, 12, 0, 0))],
                [observation(offset, unique_received_packet_delta=value)
                 for offset, value in zip(offsets, (0, 0, 0, 40, 56))],
            ],
        },
        "collector": {"gaps": [
            {"after_datagram": 10, "start_ns": INJECT - 9000 * MS, "end_ns": INJECT - 8700 * MS},
            {"after_datagram": 2210, "start_ns": INJECT + 100 * MS, "end_ns": INJECT + 620 * MS},
        ]},
    }


class GroupTimelineTests(unittest.TestCase):
    def test_backup_timeline_brackets_each_change_from_the_blackhole_start(self):
        timeline = compute_group_timeline(**series(), group_type="backup")
        self.assertEqual(timeline["origin"], "blackhole-start")
        self.assertEqual(timeline["fault_applied"], 9)
        # Only the gap that ends after the fault is the fault's.
        self.assertEqual(timeline["media_downstream_gaps"], [[100, 620]])
        self.assertEqual(timeline["longest_media_downstream_gap_ms"], 520)
        self.assertEqual(timeline["faulted_member_receiver_stall"], [500, 1000])
        self.assertEqual(timeline["faulted_member_unusable"], {"sender": [1500, 5500], "receiver": [1500, 5500]})
        self.assertEqual(timeline["standby_activation"], [500, 1000])
        self.assertIsNone(timeline["causal_claim"])

    def test_broadcast_has_no_standby_and_reports_no_gap_when_none_was_seen(self):
        data = series(standby_sent=(56, 56, 56, 56, 56))
        data["collector"] = {"gaps": []}
        timeline = compute_group_timeline(**data, group_type="broadcast")
        self.assertIsNone(timeline["standby_activation"])
        self.assertEqual(timeline["media_downstream_gaps"], [])
        self.assertEqual(timeline["longest_media_downstream_gap_ms"], 0)

    def test_a_member_that_stays_usable_is_reported_as_not_observed(self):
        data = series()
        data["group_samples"] = [item for item in data["group_samples"] if item["monotonic_ns"] < INJECT + 5000 * MS]
        timeline = compute_group_timeline(**data, group_type="backup")
        self.assertEqual(timeline["faulted_member_unusable"], {"sender": None, "receiver": None})


def described() -> dict:
    def member(index: int, local: str, peer: str, local_port: int, peer_port: int) -> dict:
        return {"index": index, "socket": 100 + index, "weight": MEMBER_WEIGHTS[index],
                "localAddress": local, "localPort": local_port, "peerAddress": peer, "peerPort": peer_port}

    return {
        "sender": {"type": "backup", "members": [
            member(index, MEMBER_LOCAL_ADDRESSES[index], MEMBER_REMOTE_ADDRESSES[index], 40000 + index, 5000)
            for index in (0, 1)]},
        "receiver": {"type": "backup", "members": [
            member(index, MEMBER_REMOTE_ADDRESSES[index], MEMBER_LOCAL_ADDRESSES[index], 5000, 40000 + index)
            for index in (0, 1)]},
    }


class GroupMemberTests(unittest.TestCase):
    def test_members_are_matched_by_address_and_port_on_both_endpoints(self):
        record = group_member_record(described(), "backup")
        self.assertEqual([item["transit"] for item in record["members"]], ["r1", "r2"])
        self.assertEqual([item["weight"] for item in record["members"]], list(MEMBER_WEIGHTS))

    def test_rejects_members_that_do_not_match_the_predeclared_paths(self):
        swapped = described()
        swapped["receiver"]["members"].reverse()
        wrong_port = described()
        wrong_port["receiver"]["members"][1]["peerPort"] = 40000
        wrong_address = described()
        wrong_address["sender"]["members"][0]["peerAddress"] = MEMBER_REMOTE_ADDRESSES[1]
        wrong_type = described()
        wrong_type["receiver"]["type"] = "broadcast"
        for case in (swapped, wrong_port, wrong_address, wrong_type):
            with self.assertRaises(QualificationError):
                group_member_record(case, "backup")

    def test_member_wire_takes_each_members_last_totals(self):
        def last(total: int) -> dict:
            return {"monotonic_ns": 1, "payload": {"sample": {"raw": {
                "unique_sent_packet_total": total, "sent_packet_total": total + 1,
                "unique_sent_wire_byte_total": total * 1000, "sent_wire_byte_total": total * 1000 + 5}}}}

        wire = member_wire([[last(1), last(7)], [last(3)]])
        self.assertEqual([item["unique_sent_packet_total"] for item in wire], [7, 3])
        self.assertEqual(wire[0]["sent_wire_byte_total"], 7005)

    def test_member_event_namespaces_are_distinct_and_stable(self):
        names = {member_event_namespace(role, member) for role in ("sender", "receiver") for member in (0, 1)}
        self.assertEqual(len(names), 4)
        self.assertEqual(member_event_namespace("sender", 0), member_event_namespace("sender", 0))


def passed_result() -> dict:
    return {
        "schema_version": 1,
        "evidence_type": "g5-srt-group",
        "status": "passed",
        "classification": "experiment",
        "gate_ids": ["G5"],
        "run_id": "6f1d1c2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f",
        "started_at": "2026-11-13T18:00:00Z",
        "finished_at": "2026-11-13T18:05:00Z",
        "provenance": {
            "srt_repository": SRT_REPOSITORY,
            "srt_commit": EXPECTED_SRT_COMMIT,
            "telemetry_repository": TELEMETRY_REPOSITORY,
            "telemetry_commit": EXPECTED_TELEMETRY_COMMIT,
            "project_revision": "0" * 40,
            "ffmpeg_version": EXPECTED_FFMPEG_VERSION + " Copyright (c) 2000-2023 the FFmpeg developers",
            **{field: "0" * 64 for field in (
                "srt_library_sha256", "incident_peer_sha256", "ffmpeg_binary_sha256")},
        },
        "platform": {"system": "Linux"},
        "clock": {"domain_id": "linux-host-monotonic-" + "a" * 24, "synchronization": "local-only",
                  "max_error_ns": None, "cross_host_ordering_allowed": False, "same_host": True},
        "topology": {"node_count": 4, "fips": False, "member_transits": ["r1", "r2"],
                     "faulted_transit": "r1"},
        "profile": {"group_type": "broadcast", "members": 2, "member_weights": list(MEMBER_WEIGHTS),
                    "fault": "transit-blackhole", "datagram_bytes": DATAGRAM_BYTES,
                    "srt_peer_idle_timeout_ms": SRT_PEER_IDLE_TIMEOUT_MS,
                    "inject_after_source_start_ms": INJECT_AFTER_SOURCE_START_NS // MS,
                    "decode_options": list(DECODE_OPTIONS),
                    "fixture": {"frames": FIXTURE_FRAMES, "encode": list(FIXTURE_ENCODE), "sha256": "0" * 64}},
        "capture": {"missed_sample_intervals": 0, "hitless": True,
                    "frames": {"expected_frames": FIXTURE_FRAMES, "missing_frames": 0, "changed_frames": 0}},
        "timeline": {"causal_claim": None},
        "files": {name: {"bytes": 1, "sha256": "0" * 64} for name in BUNDLE_FILES},
        "cleanup": {name: True for name in CLEANUP_FIELDS},
        "gate_conclusion": {"G5": "not-passed", "reason": "ordering-only"},
        "limitations": ["a", "b", "c"],
    }


class ResultContractTests(unittest.TestCase):
    def test_accepts_a_passed_result_without_gate_passage(self):
        validate_g5_srt_group_result(passed_result())

    def test_bundle_holds_twenty_one_files_beside_the_result(self):
        self.assertEqual(len(BUNDLE_FILES), 21)
        self.assertEqual(len(set(BUNDLE_FILES)), 21)

    def test_hitless_must_follow_the_frame_comparison(self):
        result = passed_result()
        result["capture"]["frames"]["changed_frames"] = 3
        with self.assertRaisesRegex(ContractError, "hitless"):
            validate_g5_srt_group_result(result)
        result["capture"]["hitless"] = False
        validate_g5_srt_group_result(result)

    def test_rejects_invalid_results(self):
        cases = (
            (("gate_conclusion", "G5"), "passed", "not-passed"),
            (("cleanup", "namespaces_removed"), False, "cleanup"),
            (("profile", "group_type"), "ring", "predeclared"),
            (("profile", "srt_peer_idle_timeout_ms"), 60_000, "predeclared"),
            (("profile", "fault"), "transit-sigkill", "predeclared"),
            (("provenance", "telemetry_commit"), "f" * 40, "telemetry_commit"),
            (("topology", "fips"), True, "topology"),
            (("topology", "faulted_transit"), "r2", "topology"),
            (("capture", "missed_sample_intervals"), 1, "incomplete"),
            (("timeline", "causal_claim"), "srt", "causal"),
        )
        for (section, field), value, message in cases:
            with self.subTest(field=field):
                result = deepcopy(passed_result())
                result[section][field] = value
                with self.assertRaisesRegex(ContractError, message):
                    validate_g5_srt_group_result(result)

    def test_failed_result_needs_only_failure_fields(self):
        result = {key: passed_result()[key] for key in (
            "schema_version", "evidence_type", "classification", "gate_ids", "run_id",
            "started_at", "finished_at", "cleanup", "gate_conclusion")}
        result.update(status="failed", project_revision="0" * 40, failure_phase="faulted-capture",
                      failure_class="QualificationError", failure_detail="budget")
        result["cleanup"]["namespaces_removed"] = False
        validate_g5_srt_group_result(result)
        result["files"] = {}
        with self.assertRaisesRegex(ContractError, "failed"):
            validate_g5_srt_group_result(result)

    def test_runner_refuses_an_unknown_group_type(self):
        arguments = {name: Path("/nonexistent") for name in (
            "srt_source", "srt_library", "telemetry_source", "incident_peer", "library_dir", "ffmpeg",
            "output_dir")}
        with self.assertRaisesRegex(QualificationError, "unknown group type"):
            run_g5_srt_group(**arguments, project_revision="0" * 40, group_type="ring")


if __name__ == "__main__":
    unittest.main()
