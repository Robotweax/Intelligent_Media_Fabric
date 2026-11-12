from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from rimf_lab.contracts import ContractError
from rimf_lab.g4_faulted_diamond import (
    BUNDLE_FILES,
    DATAGRAM_BYTES,
    EXPECTED_FFMPEG_VERSION,
    FIXTURE_ENCODE,
    FIXTURE_FRAMES,
    HISTORICAL_G4_FAULTED_DIAMOND_BUNDLES,
    INJECT_AFTER_SOURCE_START_NS,
    SRT_PEER_IDLE_PROFILES,
    SRT_PEER_IDLE_TIMEOUT_MS,
    DECODE_OPTIONS,
    compute_timeline,
    fips_timer_profile,
    retimed_frame_count,
    srt_peer_idle_timeout_ms,
    validate_g4_faulted_diamond_bundle,
    validate_g4_faulted_diamond_result,
    validate_route_epoch_event,
)
from rimf_lab.g4_srt_over_fips import (
    EXPECTED_FIPS_COMMIT,
    EXPECTED_SRT_COMMIT,
    EXPECTED_TELEMETRY_COMMIT,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
)

RETAINED = Path(__file__).resolve().parents[1] / "qualification/retained-bundles"
MS = 1_000_000
INJECT = 100_000 * MS


def fault(event: str, moment: int) -> dict:
    return {"source": "fabric", "monotonic_ns": moment, "payload": {"event": event}}


def fips(index: int, moment: int, links: int | None) -> dict:
    return {"event_id": f"f{index}", "monotonic_ns": moment, "payload": {"b_link_count": links}}


def srt(moment: int, **delta: int) -> dict:
    return {"monotonic_ns": moment, "payload": {"sample": {"raw": {}, "delta": delta}}}


def series() -> dict:
    receiver = [srt(INJECT + offset * MS, unique_received_packet_delta=value)
                for offset, value in ((-1000, 48), (-500, 47), (0, 46), (500, 0), (1000, 0),
                                      (35_000, 0), (35_500, 21), (36_000, 47))]
    sender = [srt(INJECT + offset * MS, sender_drop_packet_delta=drops, retransmitted_packet_delta=0)
              for offset, drops in ((-500, 0), (0, 0), (500, 0), (1500, 12), (2000, 30))]
    observations = [fips(index, INJECT + offset * MS, links) for index, (offset, links) in enumerate(
        ((-1000, 2), (0, 2), (29_000, 2), (30_000, 1), (31_000, 1), (31_500, 1)))]
    return {
        "fault_events": [fault("sigkill-sent", INJECT), fault("process-exit-observed", INJECT + 3 * MS)],
        "fips_observations": observations,
        "route_epochs": [
            {"route_epoch": 1, "monotonic_ns": INJECT - 20_000 * MS, "evidence_event_ids": []},
            {"route_epoch": 2, "monotonic_ns": INJECT + 31_500 * MS, "evidence_event_ids": ["f4", "f5"]},
        ],
        "sender": sender,
        "receiver": receiver,
        "collector": {"gaps": [{"after_datagram": 1900, "start_ns": INJECT + 4 * MS,
                                "end_ns": INJECT + 35_200 * MS}]},
    }


def passed_result() -> dict:
    return {
        "schema_version": 1,
        "evidence_type": "g4-faulted-diamond",
        "status": "passed",
        "classification": "experiment",
        "gate_ids": ["G4"],
        "run_id": "6f1d1c2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f",
        "started_at": "2026-10-28T18:00:00Z",
        "finished_at": "2026-10-28T18:05:00Z",
        "provenance": {
            "fips_repository": "https://github.com/jmcorgan/fips.git",
            "fips_commit": EXPECTED_FIPS_COMMIT,
            "fips_source_tree_state": "clean",
            "srt_repository": SRT_REPOSITORY,
            "srt_commit": EXPECTED_SRT_COMMIT,
            "telemetry_repository": TELEMETRY_REPOSITORY,
            "telemetry_commit": EXPECTED_TELEMETRY_COMMIT,
            "project_revision": "0" * 40,
            "ffmpeg_version": EXPECTED_FFMPEG_VERSION + " Copyright (c) 2000-2023 the FFmpeg developers",
            **{field: "0" * 64 for field in (
                "cargo_lock_sha256", "rust_toolchain_sha256", "srt_library_sha256",
                "incident_peer_sha256", "fips_binary_sha256", "fipsctl_binary_sha256",
                "ffmpeg_binary_sha256")},
        },
        "platform": {"system": "Linux"},
        "clock": {"domain_id": "linux-host-monotonic-" + "a" * 24, "synchronization": "local-only",
                  "max_error_ns": None, "cross_host_ordering_allowed": False, "same_host": True},
        "topology": {"node_count": 4, "direct_endpoint_underlay": False,
                     "overlay": "srt-ipv6-over-fips0", "initial_active_transit": "r1",
                     "alternate_transit": "r2"},
        "profile": {"srt_peer_idle_timeout_ms": SRT_PEER_IDLE_TIMEOUT_MS,
                    "datagram_bytes": DATAGRAM_BYTES,
                    "decode_options": list(DECODE_OPTIONS),
                    "packet_budget": {"media_datagram_bytes": DATAGRAM_BYTES,
                                      "clear_srt_payload_budget_bytes": 1139},
                    "inject_after_source_start_ms": INJECT_AFTER_SOURCE_START_NS // MS,
                    "fixture": {"frames": FIXTURE_FRAMES, "encode": list(FIXTURE_ENCODE), "sha256": "0" * 64}},
        "capture": {"route_epochs": [1, 2], "srt_session_survived": True,
                    "frames": {"expected_frames": FIXTURE_FRAMES}},
        "timeline": {"causal_claim": None},
        "files": {name: {"bytes": 1, "sha256": "0" * 64} for name in BUNDLE_FILES},
        "cleanup": {name: True for name in (
            "srt_peers_stopped", "media_processes_stopped", "fips_daemons_stopped",
            "faulted_daemon_reaped", "namespaces_removed", "work_directory_removed")},
        "gate_conclusion": {"G4": "not-passed", "reason": "ordering-only"},
        "limitations": ["a", "b", "c"],
    }


class TimelineTests(unittest.TestCase):
    def test_intervals_are_relative_to_the_sigkill(self):
        timeline = compute_timeline(**series())
        self.assertEqual(timeline["process_exit_observed"], 3)
        self.assertEqual(timeline["srt_receiver_stall"], [0, 500])
        self.assertEqual(timeline["srt_receiver_resume"], [35_000, 35_500])
        self.assertEqual(timeline["srt_sender_loss_or_drop"], [500, 1500])
        self.assertEqual(timeline["fips_link_loss"], [29_000, 30_000])
        self.assertEqual(timeline["fips_reparent"], [31_000, 31_500])
        self.assertEqual(timeline["media_downstream_stop"], [4, 4])
        self.assertEqual(timeline["media_downstream_resume"], [35_200, 35_200])
        self.assertEqual(timeline["media_downstream_gap_ms"], 35_196)
        self.assertIsNone(timeline["causal_claim"])

    def test_overlapping_intervals_stay_unordered(self):
        timeline = compute_timeline(**series())
        self.assertEqual(timeline["earliest_observed_change"], "media_downstream_stop")
        # The SRT stall interval begins at 0 ms, before the 4 ms media point: unordered.
        self.assertFalse(timeline["ordering_resolved"])
        self.assertEqual([item["event"] for item in timeline["divergence_ordering"]],
                         ["media_downstream_stop", "srt_receiver_stall",
                          "srt_sender_loss_or_drop", "fips_link_loss"])

    def test_resolved_only_when_the_first_upper_bound_precedes_every_lower_bound(self):
        data = series()
        data["receiver"][3]["monotonic_ns"] = INJECT + 400 * MS
        data["receiver"].insert(3, srt(INJECT + 200 * MS, unique_received_packet_delta=5))
        timeline = compute_timeline(**data)
        self.assertEqual(timeline["srt_receiver_stall"], [200, 400])
        self.assertTrue(timeline["ordering_resolved"])

    def test_no_downstream_gap_and_no_stall_are_explicitly_absent(self):
        data = series()
        data["collector"] = {"gaps": []}
        for item in data["receiver"]:
            item["payload"]["sample"]["delta"]["unique_received_packet_delta"] = 40
        timeline = compute_timeline(**data)
        self.assertIsNone(timeline["media_downstream_stop"])
        self.assertIsNone(timeline["media_downstream_gap_ms"])
        self.assertIsNone(timeline["srt_receiver_stall"])
        self.assertIsNone(timeline["srt_receiver_resume"])


class EndedSessionTimelineTests(unittest.TestCase):
    @staticmethod
    def relay(sender: bool, receiver: bool) -> dict:
        return {"stopped": {
            "sender": {"connectionBroken": sender, "lastMessageMonotonicNano": INJECT + 5_300 * MS},
            "receiver": {"connectionBroken": receiver, "lastMessageMonotonicNano": INJECT + 3 * MS}}}

    def ended(self) -> dict:
        data = series()
        # Delivery never resumes: every receiver sample after the stall stays at zero and
        # the collector records no closing gap, only its last arrival.
        for item in data["receiver"]:
            if item["monotonic_ns"] > INJECT:
                item["payload"]["sample"]["delta"]["unique_received_packet_delta"] = 0
        data["collector"] = {"gaps": [], "last_arrival_monotonic_ns": INJECT + 4 * MS}
        return data

    def test_surviving_session_timeline_is_unchanged_by_the_relay_record(self):
        self.assertEqual(compute_timeline(**series(), relay=self.relay(False, False)),
                         compute_timeline(**series()))

    def test_ended_session_reports_stop_without_resume_and_the_session_end(self):
        timeline = compute_timeline(**self.ended(), relay=self.relay(True, True))
        self.assertEqual(timeline["media_downstream_stop"], [4, 4])
        self.assertIsNone(timeline["media_downstream_resume"])
        self.assertIsNone(timeline["media_downstream_gap_ms"])
        self.assertIsNone(timeline["srt_receiver_resume"])
        self.assertEqual(timeline["srt_session_end"], {
            "sender_ended": True, "receiver_ended": True,
            "sender_last_relayed_message": 5_300, "receiver_last_relayed_message": 3})
        self.assertIsNone(timeline["causal_claim"])

    def test_one_sided_end_is_reported_per_endpoint(self):
        timeline = compute_timeline(**self.ended(), relay=self.relay(True, False))
        self.assertEqual((timeline["srt_session_end"]["sender_ended"],
                          timeline["srt_session_end"]["receiver_ended"]), (True, False))

    def test_without_an_ended_session_a_missing_gap_stays_absent(self):
        timeline = compute_timeline(**self.ended(), relay=self.relay(False, False))
        self.assertIsNone(timeline["media_downstream_stop"])
        self.assertNotIn("srt_session_end", timeline)


class SrtPeerIdleProfileTests(unittest.TestCase):
    def test_predeclared_profiles(self):
        self.assertEqual(SRT_PEER_IDLE_PROFILES, {"extended": 60_000, "default": 5_000})
        self.assertEqual(srt_peer_idle_timeout_ms("extended"), SRT_PEER_IDLE_TIMEOUT_MS)
        with self.assertRaises(Exception):
            srt_peer_idle_timeout_ms("tuned")

    def test_result_contract_accepts_only_predeclared_peer_idle_values(self):
        for value in SRT_PEER_IDLE_PROFILES.values():
            result = passed_result()
            result["profile"]["srt_peer_idle_timeout_ms"] = value
            validate_g4_faulted_diamond_result(result)
        result = passed_result()
        result["profile"]["srt_peer_idle_timeout_ms"] = 10_000
        with self.assertRaisesRegex(ContractError, "predeclared profile"):
            validate_g4_faulted_diamond_result(result)

    def test_unresumed_delivery_is_valid_only_for_an_ended_default_profile_session(self):
        def result(idle: int, survived: bool, resumed: bool) -> dict:
            value = passed_result()
            value["profile"]["srt_peer_idle_timeout_ms"] = idle
            value["capture"]["srt_session_survived"] = survived
            value["capture"]["srt_delivery_resumed"] = resumed
            return value
        validate_g4_faulted_diamond_result(result(5_000, False, False))
        validate_g4_faulted_diamond_result(result(5_000, True, True))
        validate_g4_faulted_diamond_result(result(5_000, False, True))
        for idle, survived in ((60_000, False), (60_000, True), (5_000, True)):
            with self.subTest(idle=idle, survived=survived):
                with self.assertRaisesRegex(ContractError, "delivery outcome"):
                    validate_g4_faulted_diamond_result(result(idle, survived, False))


class RetimingGuardTests(unittest.TestCase):
    HEADER = "#hash: SHA256\n#tb 0: 1/25\n#media_type 0: video\n#stream#, dts, pts, duration, size, hash\n"

    def write(self, directory: Path, name: str, hashes: dict[int, str]) -> Path:
        path = directory / name
        lines = [f"0, {pts}, {pts}, 1, 86400, {digest * 64}" for pts, digest in sorted(hashes.items())]
        path.write_text(self.HEADER + "\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_detects_shifted_frames_and_accepts_a_true_gap(self):
        reference = {pts: "0123456789abcdef"[pts] for pts in range(10)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ref = self.write(root, "ref", reference)
            gap = self.write(root, "gap", {pts: reference[pts] for pts in (0, 1, 2, 7, 8, 9)})
            shifted = self.write(root, "shifted", {0: reference[0], 1: reference[1], 2: reference[2],
                                                    3: reference[7], 4: reference[8], 5: reference[9]})
            corrupt = self.write(root, "corrupt", {**{pts: reference[pts] for pts in range(10)}, 4: "f"})
            self.assertEqual(retimed_frame_count(ref, gap), 0)
            self.assertEqual(retimed_frame_count(ref, shifted), 3)
            self.assertEqual(retimed_frame_count(ref, corrupt), 0)


class RouteEpochEventTests(unittest.TestCase):
    def event(self) -> dict:
        return {"schema_version": 1, "route_epoch": 2, "observed_at": "2026-10-28T18:00:00Z",
                "monotonic_ns": 5, "reason": "relay-change", "previous_path_id": "transit-r1",
                "current_path_id": "transit-r2", "confidence": 1.0, "evidence_event_ids": ["a", "b"]}

    def test_accepts_relay_change(self):
        validate_route_epoch_event(self.event())

    def test_rejects_invalid_events(self):
        for field, value in (("route_epoch", 0), ("reason", "guess"), ("confidence", 1.5),
                             ("evidence_event_ids", ["a", "a"]), ("unexpected", True)):
            with self.subTest(field=field):
                event = self.event()
                event[field] = value
                with self.assertRaises(ContractError):
                    validate_route_epoch_event(event)


class ResultContractTests(unittest.TestCase):
    def test_accepts_passed_result_without_gate_passage(self):
        validate_g4_faulted_diamond_result(passed_result())

    def test_rejects_historical_pin_sets_as_a_new_run(self):
        for historical in HISTORICAL_G4_FAULTED_DIAMOND_BUNDLES.values():
            result = passed_result()
            for field in ("srt_commit", "telemetry_commit", "fips_commit"):
                result["provenance"][field] = historical[field]
            with self.assertRaisesRegex(ContractError, "provenance (fips|srt|telemetry)_commit"):
                validate_g4_faulted_diamond_result(result)

    def test_retained_bundles_at_old_pins_validate_only_through_their_digest(self):
        bundles = [path for path in sorted(RETAINED.iterdir())
                   if json.loads((path / "result.json").read_text())["evidence_type"] == "g4-faulted-diamond"
                   and json.loads((path / "result.json").read_text())["provenance"]["srt_commit"]
                   != EXPECTED_SRT_COMMIT]
        self.assertEqual(len(bundles), len(HISTORICAL_G4_FAULTED_DIAMOND_BUNDLES))
        for bundle in bundles:
            with self.subTest(bundle=bundle.name):
                validate_g4_faulted_diamond_bundle(bundle)
        # The same bundle with a re-serialized manifest no longer matches its digest
        # and is judged against the active pins.
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "bundle"
            shutil.copytree(bundles[0], copy)
            manifest = json.loads((copy / "result.json").read_text())
            (copy / "result.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "provenance srt_commit"):
                validate_g4_faulted_diamond_bundle(copy)

    def test_rejects_invalid_results(self):
        cases = (
            (("gate_conclusion", "G4"), "passed", "not-passed"),
            (("cleanup", "faulted_daemon_reaped"), False, "cleanup"),
            (("capture", "route_epochs"), [1], "two route epochs"),
            (("profile", "srt_peer_idle_timeout_ms"), 10_000, "predeclared"),
            (("profile", "datagram_bytes"), 1316, "packet budget"),
            (("provenance", "telemetry_commit"), "f" * 40, "telemetry_commit"),
            (("provenance", "ffmpeg_version"), "ffmpeg version 7.0", "ffmpeg_version"),
            (("timeline", "causal_claim"), "fips", "causal"),
            (("topology", "direct_endpoint_underlay"), True, "topology"),
        )
        for (section, field), value, message in cases:
            with self.subTest(field=field):
                result = deepcopy(passed_result())
                result[section][field] = value
                with self.assertRaisesRegex(ContractError, message):
                    validate_g4_faulted_diamond_result(result)

    def test_failed_result_needs_only_failure_fields(self):
        result = {key: passed_result()[key] for key in (
            "schema_version", "evidence_type", "classification", "gate_ids", "run_id",
            "started_at", "finished_at", "cleanup", "gate_conclusion")}
        result.update(status="failed", project_revision="0" * 40, failure_phase="faulted-capture",
                      failure_class="QualificationError", failure_detail="budget")
        result["cleanup"]["faulted_daemon_reaped"] = False
        validate_g4_faulted_diamond_result(result)
        result["files"] = {}
        with self.assertRaisesRegex(ContractError, "failed"):
            validate_g4_faulted_diamond_result(result)


class FipsTimerProfileTests(unittest.TestCase):
    def config(self, **timers: int) -> str:
        from rimf_lab.fips_g2_linux_alternate_route import render_alternate_route_config

        return render_alternate_route_config(Path("/run/fips.sock"), dns_enabled=False, peers=[], **timers)

    def test_default_rendering_is_the_g2_diamond_config(self):
        g2 = fips_timer_profile("g2-alternate-route")
        self.assertEqual(self.config(), self.config(heartbeat_interval_secs=g2["heartbeat_interval_secs"],
                                                    link_dead_timeout_secs=g2["link_dead_timeout_secs"]))
        self.assertIn("heartbeat_interval_secs: 10\n  link_dead_timeout_secs: 30\n", self.config())

    def test_fast_detection_renders_its_predeclared_timers(self):
        fast = fips_timer_profile("fast-detection")
        self.assertEqual((fast["tick_interval_secs"], fast["heartbeat_interval_secs"], fast["link_dead_timeout_secs"]),
                         (1, 1, 3))
        text = self.config(heartbeat_interval_secs=1, link_dead_timeout_secs=3)
        self.assertIn("tick_interval_secs: 1\n  heartbeat_interval_secs: 1\n  link_dead_timeout_secs: 3\n", text)

    def test_rejects_unordered_or_out_of_range_timers(self):
        for heartbeat, dead in ((3, 3), (0, 3), (1, 31)):
            with self.subTest(heartbeat=heartbeat, dead=dead), self.assertRaises(ValueError):
                self.config(heartbeat_interval_secs=heartbeat, link_dead_timeout_secs=dead)

    def test_result_contract_accepts_only_predeclared_timer_profiles(self):
        legacy = passed_result()
        legacy["profile"].pop("fips_timers", None)
        validate_g4_faulted_diamond_result(legacy)
        for name in ("g2-alternate-route", "fast-detection"):
            result = passed_result()
            result["profile"]["fips_timers"] = fips_timer_profile(name)
            validate_g4_faulted_diamond_result(result)
        for timers in ({**fips_timer_profile("fast-detection"), "link_dead_timeout_secs": 5},
                       {**fips_timer_profile("fast-detection"), "name": "tuned"},
                       "fast-detection"):
            with self.subTest(timers=timers):
                result = passed_result()
                result["profile"]["fips_timers"] = timers
                with self.assertRaisesRegex(ContractError, "FIPS timers"):
                    validate_g4_faulted_diamond_result(result)


if __name__ == "__main__":
    unittest.main()
