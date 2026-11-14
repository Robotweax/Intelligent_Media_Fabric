from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from rimf_lab.contracts import ContractError
from rimf_lab.fips_g2_linux import (
    EFFECTIVE_IPV6_MTU,
    EXPECTED_FIPS_COMMIT,
    FIPS_REPOSITORY,
    QualificationError,
)
from rimf_lab.g4_faulted_diamond import (
    DATAGRAM_BYTES,
    DECODE_OPTIONS,
    EXPECTED_FFMPEG_VERSION,
    FIXTURE_ENCODE,
    FIXTURE_FRAMES,
    INJECT_AFTER_SOURCE_START_NS,
    SRT_IPV6_UDP_HEADER_BYTES,
)
from rimf_lab.g4_srt_over_fips import (
    EXPECTED_SRT_COMMIT,
    EXPECTED_TELEMETRY_COMMIT,
    SRT_REPOSITORY,
    TELEMETRY_REPOSITORY,
)
from rimf_lab.g5_srt_group import MEMBER_WEIGHTS, SRT_PEER_IDLE_TIMEOUT_MS, group_member_record
from rimf_lab.g5_srt_group_fips import (
    BUNDLE_FILES,
    CLEANUP_FIELDS,
    DAEMONS,
    ENDPOINT_ROUTING,
    ENDPOINT_TUN_NAMES,
    FIPS_TIMERS,
    INTACT_OVERLAY,
    compute_fips_group_timeline,
    overlay_relationships,
    overlay_state,
    render_overlay_config,
    run_g5_srt_group_fips,
    validate_g5_srt_group_fips_result,
)

MS = 1_000_000
INJECT = 100_000 * MS
NPUB = "npub1" + "q" * 58
ADDRS = ["0" * 31 + "1", "0" * 31 + "2", "0" * 31 + "3"]
IDS = ["npub-a", "npub-t", "npub-b"]
LOCAL = ("fd11::1", "fd22::1")
REMOTE = ("fd33::1", "fd44::1")
LOST = {**INTACT_OVERLAY, "a_peer_count": 0, "a_link_count": 0, "b_peer_count": 0, "b_link_count": 0,
        "b_parent_role": "b", "b_root_role": "b", "b_depth": 0}


def fips(offset_ms: int, first: dict, second: dict | None = None, availability: str = "available") -> dict:
    return {"monotonic_ns": INJECT + offset_ms * MS, "quality": {"availability": availability},
            "payload": {"overlays": [{"transit": "r1", **first},
                                     {"transit": "r2", **(INTACT_OVERLAY if second is None else second)}]}}


FAULTS = [{"source": "fabric", "monotonic_ns": INJECT, "payload": {"event": "blackhole-start"}}]


class OverlayConfigTests(unittest.TestCase):
    def test_config_carries_the_tun_name_bind_address_dns_port_and_frozen_timers(self):
        text = render_overlay_config(Path("/tmp/c.sock"), tun_name="fipsg2", bind_address="10.208.3.1",
                                     peers=[("transit", NPUB, "10.208.4.1")], dns_port=5355)
        self.assertIn('name: "fipsg2"', text)
        self.assertIn('bind_addr: "10.208.3.1:2121"', text)
        self.assertIn('addr: "10.208.4.1:2121"', text)
        self.assertIn("port: 5355", text)
        self.assertIn(f"link_dead_timeout_secs: {FIPS_TIMERS['link_dead_timeout_secs']}", text)
        self.assertEqual(FIPS_TIMERS["link_dead_timeout_secs"], 30)

    def test_a_transit_has_no_dns_and_no_static_peer_is_an_empty_list(self):
        text = render_overlay_config(Path("/tmp/c.sock"), tun_name="fips0", bind_address="0.0.0.0", peers=[])
        self.assertIn("dns:\n  enabled: false", text)
        self.assertIn("peers: []", text)

    def test_rejects_invalid_configuration(self):
        for arguments in (
            {"tun_name": "fips 0", "bind_address": "0.0.0.0", "peers": []},
            {"tun_name": "fips0", "bind_address": "::", "peers": []},
            {"tun_name": "fips0", "bind_address": "0.0.0.0", "peers": [("t", "not-an-npub", "10.0.0.1")]},
            {"tun_name": "fips0", "bind_address": "0.0.0.0", "peers": [], "dns_port": 53},
        ):
            with self.assertRaises(ValueError):
                render_overlay_config(Path("/tmp/c.sock"), **arguments)

    def test_six_daemons_form_two_overlays_with_two_per_endpoint_namespace(self):
        self.assertEqual(len(DAEMONS), 6)
        self.assertEqual([item[2] for item in DAEMONS], [0, 1, 3, 0, 2, 3])
        endpoint_tuns = {(namespace, tun) for _, role, namespace, tun in DAEMONS if role != "transit"}
        self.assertEqual(len(endpoint_tuns), 4)
        self.assertEqual({tun for _, tun in endpoint_tuns}, set(ENDPOINT_TUN_NAMES))


class OverlayStateTests(unittest.TestCase):
    def views(self):
        peers = [{"peers": [{"npub": IDS[1]}]}, {"peers": [{"npub": IDS[0]}, {"npub": IDS[2]}]},
                 {"peers": [{"npub": IDS[1]}]}]
        trees = [{"root": ADDRS[0], "depth": 0, "parent": ADDRS[0]},
                 {"root": ADDRS[0], "depth": 1, "parent": ADDRS[0]},
                 {"root": ADDRS[0], "depth": 2, "parent": ADDRS[1]}]
        return peers, trees

    def test_an_intact_overlay_is_a_transit_b(self):
        peers, trees = self.views()
        self.assertTrue(overlay_relationships(peers, trees, IDS, ADDRS))
        statuses = [{"peer_count": 1, "link_count": 1}, {"peer_count": 2, "link_count": 2},
                    {"peer_count": 1, "link_count": 1}]
        self.assertEqual(overlay_state(statuses, trees[2], ADDRS), INTACT_OVERLAY)

    def test_rejects_a_foreign_peer_a_wrong_parent_or_a_wrong_root(self):
        peers, trees = self.views()
        foreign = deepcopy(peers)
        foreign[0]["peers"].append({"npub": "npub-other-overlay"})
        parent = deepcopy(trees)
        parent[2]["parent"] = ADDRS[0]
        root = deepcopy(trees)
        root[2]["root"] = ADDRS[2]
        self.assertFalse(overlay_relationships(foreign, trees, IDS, ADDRS))
        self.assertFalse(overlay_relationships(peers, parent, IDS, ADDRS))
        self.assertFalse(overlay_relationships(peers, root, IDS, ADDRS))
        self.assertFalse(overlay_relationships(peers[:2], trees, IDS, ADDRS))

    def test_an_unknown_parent_is_reported_as_unknown(self):
        statuses = [{}, {}, {}]
        state = overlay_state(statuses, {"parent": "f" * 32, "root": ADDRS[2], "depth": 0}, ADDRS)
        self.assertEqual((state["b_parent_role"], state["b_root_role"]), ("unknown", "b"))


class FipsTimelineTests(unittest.TestCase):
    def test_link_loss_is_bracketed_per_endpoint_and_the_other_overlay_must_stay_intact(self):
        a_only = {**INTACT_OVERLAY, "a_peer_count": 0, "a_link_count": 0}
        observations = [fips(-1000, INTACT_OVERLAY), fips(30000, INTACT_OVERLAY), fips(31000, a_only),
                        fips(32000, LOST)]
        timeline = compute_fips_group_timeline({"origin": "blackhole-start"}, FAULTS, observations)
        self.assertEqual(timeline["faulted_overlay_link_loss"], {"a": [30000, 31000], "b": [31000, 32000]})
        self.assertTrue(timeline["surviving_overlay_stable"])
        self.assertEqual(timeline["origin"], "blackhole-start")

    def test_a_loss_that_is_not_observed_is_none(self):
        timeline = compute_fips_group_timeline({}, FAULTS, [fips(-1000, INTACT_OVERLAY), fips(1000, INTACT_OVERLAY)])
        self.assertEqual(timeline["faulted_overlay_link_loss"], {"a": None, "b": None})

    def test_a_change_or_an_unavailable_observation_on_the_other_overlay_is_not_stable(self):
        changed = [fips(-1000, INTACT_OVERLAY), fips(1000, INTACT_OVERLAY, {**INTACT_OVERLAY, "b_link_count": 0})]
        unavailable = [fips(-1000, INTACT_OVERLAY), fips(1000, INTACT_OVERLAY, availability="unavailable")]
        for observations in (changed, unavailable, []):
            self.assertFalse(compute_fips_group_timeline({}, FAULTS, observations)["surviving_overlay_stable"])


class MemberAddressTests(unittest.TestCase):
    def described(self) -> dict:
        def member(index: int, local: str, peer: str, local_port: int, peer_port: int) -> dict:
            return {"index": index, "weight": MEMBER_WEIGHTS[index], "localAddress": local,
                    "localPort": local_port, "peerAddress": peer, "peerPort": peer_port}

        return {"sender": {"type": "backup", "members": [
                    member(index, LOCAL[index], REMOTE[index], 40000 + index, 5000) for index in (0, 1)]},
                "receiver": {"type": "backup", "members": [
                    member(index, REMOTE[index], LOCAL[index], 5000, 40000 + index) for index in (0, 1)]}}

    def test_members_are_matched_against_the_overlay_addresses(self):
        record = group_member_record(self.described(), "backup", LOCAL, REMOTE)
        self.assertEqual([item["caller_address"] for item in record["members"]], list(LOCAL))
        self.assertEqual([item["listener_address"] for item in record["members"]], list(REMOTE))

    def test_rejects_members_on_the_wrong_overlay(self):
        with self.assertRaises(QualificationError):
            group_member_record(self.described(), "backup", LOCAL, tuple(reversed(REMOTE)))
        with self.assertRaises(QualificationError):
            group_member_record(self.described(), "backup")


def passed_result() -> dict:
    budget = EFFECTIVE_IPV6_MTU - SRT_IPV6_UDP_HEADER_BYTES
    return {
        "schema_version": 1,
        "evidence_type": "g5-srt-group-fips",
        "status": "passed",
        "classification": "experiment",
        "gate_ids": ["G5"],
        "run_id": "6f1d1c2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f",
        "started_at": "2026-11-14T18:00:00Z",
        "finished_at": "2026-11-14T18:05:00Z",
        "provenance": {
            "srt_repository": SRT_REPOSITORY, "srt_commit": EXPECTED_SRT_COMMIT,
            "telemetry_repository": TELEMETRY_REPOSITORY, "telemetry_commit": EXPECTED_TELEMETRY_COMMIT,
            "fips_repository": FIPS_REPOSITORY, "fips_commit": EXPECTED_FIPS_COMMIT,
            "fips_source_tree_state": "clean",
            "project_revision": "0" * 40,
            "ffmpeg_version": EXPECTED_FFMPEG_VERSION + " Copyright (c) 2000-2023 the FFmpeg developers",
            **{field: "0" * 64 for field in (
                "srt_library_sha256", "incident_peer_sha256", "ffmpeg_binary_sha256", "fips_binary_sha256",
                "fipsctl_binary_sha256", "cargo_lock_sha256", "rust_toolchain_sha256")},
        },
        "platform": {"system": "Linux"},
        "clock": {"domain_id": "linux-host-monotonic-" + "a" * 24, "synchronization": "local-only",
                  "max_error_ns": None, "cross_host_ordering_allowed": False, "same_host": True},
        "topology": {"node_count": 4, "fips": True, "fips_daemons": 6, "overlays": 2,
                     "endpoint_tun_names": list(ENDPOINT_TUN_NAMES), "endpoint_routing": ENDPOINT_ROUTING,
                     "member_transits": ["r1", "r2"], "faulted_transit": "r1"},
        "profile": {"group_type": "backup", "members": 2, "member_weights": list(MEMBER_WEIGHTS),
                    "fault": "transit-blackhole", "fips_timers": dict(FIPS_TIMERS),
                    "datagram_bytes": DATAGRAM_BYTES,
                    "packet_budget": {"endpoint_effective_ipv6_mtu": [EFFECTIVE_IPV6_MTU] * 4,
                                      "clear_srt_payload_budget_bytes": budget,
                                      "media_datagram_bytes": DATAGRAM_BYTES},
                    "srt_peer_idle_timeout_ms": SRT_PEER_IDLE_TIMEOUT_MS,
                    "inject_after_source_start_ms": INJECT_AFTER_SOURCE_START_NS // MS,
                    "decode_options": list(DECODE_OPTIONS),
                    "fixture": {"frames": FIXTURE_FRAMES, "encode": list(FIXTURE_ENCODE), "sha256": "0" * 64}},
        "capture": {"missed_sample_intervals": 0, "hitless": True, "fips_observations": 160,
                    "frames": {"expected_frames": FIXTURE_FRAMES, "missing_frames": 0, "changed_frames": 0}},
        "timeline": {"causal_claim": None, "surviving_overlay_stable": True},
        "files": {name: {"bytes": 1, "sha256": "0" * 64} for name in BUNDLE_FILES},
        "cleanup": {name: True for name in CLEANUP_FIELDS},
        "gate_conclusion": {"G5": "not-passed", "reason": "ordering-only"},
        "limitations": ["a", "the endpoint routing is a lab workaround", "c", "d"],
    }


class ResultContractTests(unittest.TestCase):
    def test_accepts_a_passed_result_without_gate_passage(self):
        validate_g5_srt_group_fips_result(passed_result())

    def test_bundle_is_stage_one_plus_the_fips_observations(self):
        self.assertEqual(len(BUNDLE_FILES), 22)
        self.assertIn("fips-observations.jsonl", BUNDLE_FILES)
        self.assertIn("fips_daemons_stopped", CLEANUP_FIELDS)

    def test_rejects_invalid_results(self):
        cases = (
            (("gate_conclusion", "G5"), "passed", "not-passed"),
            (("cleanup", "fips_daemons_stopped"), False, "cleanup"),
            (("profile", "group_type"), "ring", "predeclared"),
            (("profile", "fips_timers"), {**FIPS_TIMERS, "link_dead_timeout_secs": 3}, "predeclared"),
            (("profile", "packet_budget"), {"endpoint_effective_ipv6_mtu": [1203] * 4,
                                           "clear_srt_payload_budget_bytes": 1000,
                                           "media_datagram_bytes": DATAGRAM_BYTES}, "packet budget"),
            (("provenance", "fips_commit"), "f" * 40, "fips_commit"),
            (("provenance", "fips_source_tree_state"), "dirty", "fips_source_tree_state"),
            (("topology", "fips"), False, "topology"),
            (("topology", "endpoint_routing"), "fips-native", "topology"),
            (("topology", "fips_daemons"), 4, "topology"),
            (("capture", "missed_sample_intervals"), 1, "incomplete"),
            (("timeline", "causal_claim"), "fips", "causal"),
            (("timeline", "surviving_overlay_stable"), False, "other overlay"),
        )
        for (section, field), value, message in cases:
            with self.subTest(field=field):
                result = deepcopy(passed_result())
                result[section][field] = value
                with self.assertRaisesRegex(ContractError, message):
                    validate_g5_srt_group_fips_result(result)

    def test_the_workaround_must_be_named_as_a_limitation(self):
        result = passed_result()
        result["limitations"] = ["a", "b", "c", "d"]
        with self.assertRaisesRegex(ContractError, "limitations"):
            validate_g5_srt_group_fips_result(result)

    def test_hitless_must_follow_the_frame_comparison(self):
        result = passed_result()
        result["capture"]["frames"]["missing_frames"] = 2
        with self.assertRaisesRegex(ContractError, "hitless"):
            validate_g5_srt_group_fips_result(result)

    def test_failed_result_needs_only_failure_fields(self):
        result = {key: passed_result()[key] for key in (
            "schema_version", "evidence_type", "classification", "gate_ids", "run_id",
            "started_at", "finished_at", "cleanup", "gate_conclusion")}
        result.update(status="failed", project_revision="0" * 40, failure_phase="overlay-convergence",
                      failure_class="QualificationError", failure_detail="timed out")
        result["cleanup"]["fips_daemons_stopped"] = False
        validate_g5_srt_group_fips_result(result)
        result["timeline"] = {}
        with self.assertRaisesRegex(ContractError, "failed"):
            validate_g5_srt_group_fips_result(result)

    def test_a_stage_one_result_is_not_a_stage_two_result(self):
        result = passed_result()
        result["evidence_type"] = "g5-srt-group"
        with self.assertRaisesRegex(ContractError, "evidence_type"):
            validate_g5_srt_group_fips_result(result)

    def test_runner_refuses_an_unknown_group_type(self):
        arguments = {name: Path("/nonexistent") for name in (
            "fips_source", "fips_binary", "fipsctl_binary", "srt_source", "srt_library", "telemetry_source",
            "incident_peer", "library_dir", "ffmpeg", "output_dir")}
        with self.assertRaisesRegex(QualificationError, "unknown group type"):
            run_g5_srt_group_fips(**arguments, project_revision="0" * 40, group_type="ring")


if __name__ == "__main__":
    unittest.main()
