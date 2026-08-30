from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from rimf_lab.contracts import (
    ContractError,
    validate_fips_g2_linux_alternate_route_result,
    validate_fips_g2_linux_direct_result,
    validate_fips_g2_linux_lifecycle_result,
    validate_fips_g2_linux_managed_transit_result,
    validate_fips_g2_linux_multihop_mtu_result,
    validate_fips_g2_linux_nat_result,
    validate_fips_g2_linux_reactive_mtu_result,
)
from rimf_lab.fips_g2_linux_alternate_route import (
    alternate_route_timings_within_contract,
    diamond_peer_relationships,
    node_addr_from_npub,
    render_alternate_route_config,
)
from rimf_lab.fips_g2_linux import (
    mesh_size_converged,
    render_config,
    valid_connect_acknowledgement,
)
from rimf_lab.fips_g2_linux_nat import translated_peer_observed
from rimf_lab.fips_g2_linux_lifecycle import (
    lifecycle_timings_within_contract,
    render_lifecycle_config,
)
from rimf_lab.fips_g2_linux_managed_transit import (
    coordinate_cache_path_mtu,
    forwarding_counters,
    line_peer_relationships,
    mtu_drop_counters,
    mtu_error_counters,
    session_path_mtu,
)
from rimf_lab.icmpv6_ptb_probe import parse_packet_too_big
from rimf_lab.payload_probe import deterministic_payload


def valid_result():
    digest = "a" * 64
    return {
        "schema_version": 1,
        "evidence_type": "fips-g2-linux-direct",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "status": "passed",
        "classification": "experiment",
        "gate_ids": ["G2"],
        "started_at": "2026-08-29T20:00:00Z",
        "finished_at": "2026-08-29T20:01:00Z",
        "provenance": {
            "project_revision": "b" * 40,
            "fips_repository": "https://github.com/jmcorgan/fips.git",
            "fips_commit": "c" * 40,
            "fips_source_tree_state": "clean",
            "cargo_lock_sha256": digest,
            "rust_toolchain_sha256": digest,
            "fips_binary_sha256": digest,
            "fipsctl_binary_sha256": digest,
            "reported_version": "fips 0.4.2",
        },
        "platform": {
            "system": "Linux",
            "release": "test",
            "machine": "x86_64",
            "python": "3.11.0",
        },
        "topology": {
            "node_count": 2,
            "isolation": "linux-network-namespaces",
            "underlay": "direct-veth-ipv4-udp",
            "tun_name": "fips0",
            "configured_tun_mtu": 1280,
            "configured_udp_mtu": 1280,
        },
        "observations": {
            "nodes": [
                {
                    "node": node,
                    "tun_state": "active",
                    "tun_name": "fips0",
                    "kernel_tun_mtu": 1280,
                    "effective_ipv6_mtu": 1203,
                }
                for node in ("a", "b")
            ],
            "connection": {
                "control_acknowledged": True,
                "authenticated_peers_per_node": 1,
                "links_per_node": 1,
                "estimated_mesh_size": 2,
                "transport": "udp",
            },
            "mmp": [
                {
                    "node": node,
                    "mode": "full",
                    "loss_rate": 0.0,
                    "etx": 1.0,
                    "srtt_ms_observed": True,
                }
                for node in ("a", "b")
            ],
            "icmpv6": {
                "small_payload_bytes": 32,
                "effective_mtu_boundary_payload_bytes": 1155,
                "echo_requests_per_size": 2,
                "passed": True,
            },
            "payload_identity": {
                "protocol": "udp-over-ipv6-over-fips0",
                "records": [
                    {"bytes": size, "sha256": digest, "exact_echo": True}
                    for size in (1, 1024, 1155)
                ],
                "all_exact_echo": True,
            },
            "fsp_session_counts": [1, 1],
            "disconnect": {
                "control_acknowledged": True,
                "peers_per_node_after": 0,
                "links_per_node_after": 0,
            },
        },
        "cleanup": {
            "daemons_stopped": True,
            "namespaces_removed": True,
            "ephemeral_identity_directory_removed": True,
        },
        "limitations": ["Direct underlay only."],
    }


def valid_nat_result():
    result = deepcopy(valid_result())
    result["evidence_type"] = "fips-g2-linux-nat"
    result["topology"] = {
        "node_count": 2,
        "namespace_count": 3,
        "isolation": "linux-network-namespaces",
        "underlay": "routed-two-segment-ipv4-udp",
        "nat": "one-sided-snat",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
    }
    result["observations"]["directional_reachability"] = {
        "node_a_to_node_b_new_flow_blocked": True,
        "node_b_to_node_a_new_flow_allowed": True,
        "stateful_return_path_only": True,
    }
    result["observations"]["nat"] = {
        "mode": "one-sided-snat",
        "private_initiator": "node-b",
        "public_node_observed_translated_source": True,
        "private_source_address_not_retained": True,
    }
    result["limitations"] = ["One-sided SNAT only."]
    return result


def valid_direct_mtu_result():
    result = deepcopy(valid_result())
    result["schema_version"] = 2
    result["observations"]["above_effective_mtu"] = {
        "effective_ipv6_mtu": 1203,
        "boundary_icmp_payload_bytes": 1155,
        "above_boundary_icmp_payload_bytes": 1156,
        "above_boundary_ipv6_packet_bytes": 1204,
        "echo_reply_received": False,
        "icmpv6_type": 2,
        "icmpv6_code": 0,
        "reported_mtu": 1203,
        "post_ptb_boundary_probe_passed": True,
    }
    return result


def valid_managed_transit_result():
    result = deepcopy(valid_result())
    result["evidence_type"] = "fips-g2-linux-managed-transit"
    result["topology"] = {
        "node_count": 3,
        "namespace_count": 3,
        "authenticated_link_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "two-segment-line-ipv4-udp",
        "path_role": "managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
    }
    digest = "a" * 64
    result["observations"] = {
        "underlay_exclusion": {
            "endpoint_direct_ipv4_forwarding_disabled": True,
            "endpoint_direct_ipv4_probe_blocked": True,
        },
        "line_topology": {
            "control_connects_acknowledged": 2,
            "authenticated_peer_counts": [1, 2, 1],
            "authenticated_link_counts": [1, 2, 1],
            "estimated_mesh_size": 3,
            "endpoint_direct_peer_absent": True,
            "transport": "udp",
        },
        "identity_resolution": {
            "mechanism": "local-fips-dns-npub",
            "endpoint_remote_identities_registered": True,
            "public_discovery_used": False,
        },
        "nodes": [
            {
                "node": node,
                "role": "managed-transit" if node == "r" else "endpoint",
                "tun_state": "active",
                "tun_name": "fips0",
                "kernel_tun_mtu": 1280,
                "effective_ipv6_mtu": 1203,
            }
            for node in ("a", "r", "b")
        ],
        "mmp": [
            {
                "node": node,
                "link_ordinal": ordinal,
                "mode": "full",
                "loss_rate": 0.0,
                "etx": 1.0,
                "srtt_ms_observed": True,
            }
            for node, ordinal in (("a", 1), ("r", 1), ("r", 2), ("b", 1))
        ],
        "icmpv6": {
            "path": "endpoint-a-via-managed-transit-r-to-endpoint-b",
            "small_payload_bytes": 32,
            "effective_mtu_boundary_payload_bytes": 1155,
            "passed": True,
        },
        "payload_identity": {
            "protocol": "udp-over-ipv6-over-fips0-multihop",
            "records": [
                {"bytes": size, "sha256": digest, "exact_echo": True}
                for size in (1, 1024, 1155)
            ],
            "all_exact_echo": True,
        },
        "transit_forwarding": {
            "forwarded_packets": 10,
            "forwarded_bytes": 4096,
            "endpoint_fsp_session_counts": [1, 1],
            "transit_fsp_session_count": 0,
            "payload_opaque_to_transit_by_protocol_contract": True,
        },
        "disconnect": {
            "control_acknowledgements": 2,
            "peers_per_node_after": [0, 0, 0],
            "links_per_node_after": [0, 0, 0],
        },
    }
    result["limitations"] = ["Static managed transit only."]
    return result


def valid_multihop_mtu_result():
    result = deepcopy(valid_managed_transit_result())
    result["evidence_type"] = "fips-g2-linux-multihop-mtu"
    result["topology"] = {
        "node_count": 3,
        "namespace_count": 3,
        "authenticated_link_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "two-segment-line-ipv4-udp",
        "path_role": "managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu_per_node": [1280, 1280, 1280],
        "configured_udp_mtu_per_node": [1280, 1000, 1280],
        "bottleneck_node": "r",
    }
    result["observations"]["nodes"][1]["effective_ipv6_mtu"] = 923
    result["observations"]["icmpv6"]["effective_mtu_boundary_payload_bytes"] = 875
    result["observations"]["path_mtu"] = {
        "endpoint_effective_ipv6_mtu": 1203,
        "transit_transport_mtu": 1000,
        "learned_transport_path_mtu": 1000,
        "endpoint_session_path_mtus": [1000, 1000],
        "effective_ipv6_path_mtu": 923,
        "boundary_icmp_payload_bytes": 875,
        "above_boundary_icmp_payload_bytes": 876,
        "above_boundary_ipv6_packet_bytes": 924,
        "echo_reply_received": False,
        "icmpv6_type": 2,
        "icmpv6_code": 0,
        "reported_mtu": 923,
        "post_ptb_boundary_probe_passed": True,
    }
    for record, size in zip(
        result["observations"]["payload_identity"]["records"], (1, 512, 875)
    ):
        record["bytes"] = size
    result["limitations"] = ["One heterogeneous managed-transit MTU only."]
    return result


def valid_reactive_mtu_result():
    result = deepcopy(valid_multihop_mtu_result())
    result["evidence_type"] = "fips-g2-linux-reactive-mtu"
    result["topology"] = {
        "node_count": 3,
        "namespace_count": 3,
        "authenticated_link_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "two-segment-line-ipv4-udp",
        "path_role": "managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu_per_node": [1280, 1280, 1280],
        "initial_udp_mtu_per_node": [1280, 1280, 1280],
        "final_udp_mtu_per_node": [1280, 1000, 1280],
        "bottleneck_node": "r",
    }
    result["observations"]["nodes"][1]["effective_ipv6_mtu"] = 1203
    result["observations"]["initial_path_mtu"] = {
        "configured_transport_path_mtu": 1280,
        "endpoint_session_path_mtus": [1280, 1280],
        "coordinate_cache_path_mtu": 1280,
    }
    result["observations"]["transit_restart"] = {
        "configuration_application": "identity-preserving-process-restart",
        "transport_config_hot_reload_supported": False,
        "endpoint_daemons_restarted": False,
        "transit_identity_preserved": True,
        "transit_process_restarted": True,
        "endpoint_links_explicitly_withdrawn": False,
        "transit_reconnect_mode": "configured-auto-connect",
        "manual_link_reconnect_commands": 0,
        "endpoint_link_ids_before": [10, 20],
        "endpoint_link_ids_after": [11, 21],
        "restart_epoch_admission_floor_ms": 15000,
        "reconnect_elapsed_ms": 15100,
        "reconnect_budget_ms": 20000,
        "post_change_application_packets_before_trigger": 0,
        "source_coordinate_cache_path_mtu_before_trigger": 1280,
        "source_pmtu_snapshot_phase": "pre-restart-reactive-baseline",
        "transport_mtu_before": 1280,
        "transport_mtu_after": 1000,
        "endpoint_session_start_ms_before": [1000, 1001],
        "endpoint_session_start_ms_after": [1000, 1001],
    }
    result["observations"]["reactive_mtu"] = {
        "trigger_ipv6_packet_bytes": 1203,
        "trigger_transport": "udp",
        "trigger_count": 1,
        "session_path_mtu_before": 1280,
        "session_path_mtu_after": 1000,
        "coordinate_cache_path_mtu_after": 1000,
        "endpoint_mtu_exceeded_delta": 1,
        "endpoint_below_floor_delta": 0,
        "endpoint_uncorroborated_delta": 0,
        "transit_drop_packets_delta": 1,
        "transit_drop_bytes_delta": 1280,
        "convergence_elapsed_ms": 250,
        "convergence_budget_ms": 20000,
    }
    result["limitations"] = ["Identity-preserving transit restart only."]
    return result


def valid_lifecycle_result():
    result = deepcopy(valid_result())
    result["evidence_type"] = "fips-g2-linux-lifecycle"
    result["topology"] = {
        "node_count": 2,
        "isolation": "linux-network-namespaces",
        "underlay": "direct-veth-ipv4-udp",
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
        "identity_storage": "temporary-config-adjacent-key-files",
        "restarted_node": "b",
    }
    nodes = [
        {
            "node": node,
            "tun_state": "active",
            "tun_name": "fips0",
            "kernel_tun_mtu": 1280,
            "effective_ipv6_mtu": 1203,
            "persistent_identity": True,
        }
        for node in ("a", "b")
    ]
    mmp = [
        {
            "node": node,
            "mode": "full",
            "loss_rate": 0.0,
            "etx": 1.0,
            "srtt_ms_observed": True,
        }
        for node in ("a", "b")
    ]
    digest = "a" * 64

    def payload():
        return {
            "protocol": "udp-over-ipv6-over-fips0",
            "records": [
                {"bytes": size, "sha256": digest, "exact_echo": True}
                for size in (1, 1024, 1155)
            ],
            "all_exact_echo": True,
        }

    result["observations"] = {
        "nodes_before_failure": deepcopy(nodes),
        "initial_connection": {
            "configured_auto_connect_peers": 1,
            "manual_connect_commands": 0,
            "authenticated_peers_per_node": 1,
            "links_per_node": 1,
            "estimated_mesh_size": 2,
            "transport": "udp",
        },
        "initial_mmp": deepcopy(mmp),
        "initial_payload_identity": payload(),
        "initial_fsp_session_counts": [1, 1],
        "failure_injection": {
            "failed_node": "b",
            "signal": "SIGKILL",
            "graceful_disconnect_sent": False,
            "process_exit_observed": True,
        },
        "link_dead_detection": {
            "tick_interval_secs": 1,
            "heartbeat_interval_secs": 10,
            "link_dead_timeout_secs": 30,
            "detection_budget_secs": 60,
            "detection_elapsed_ms": 30250,
            "observer": "node-a",
            "peers_after": 0,
            "links_after": 0,
            "fsp_sessions_after": 0,
            "outage_probe_blocked": True,
        },
        "identity_continuity": {
            "persistent_identity_configured_per_node": [True, True],
            "private_key_file_mode": "0600",
            "public_key_file_mode": "0644",
            "restarted_node": "b",
            "public_identity_unchanged": True,
            "mesh_address_unchanged": True,
            "daemon_pid_changed": True,
            "identity_values_retained": False,
        },
        "automatic_reconnect": {
            "configured": True,
            "retry_base_interval_secs": 5,
            "retry_max_backoff_secs": 300,
            "manual_reconnect_commands": 0,
            "reconnect_budget_secs": 90,
            "reconnect_elapsed_ms": 6200,
            "authenticated_peers_per_node": 1,
            "links_per_node": 1,
            "estimated_mesh_size": 2,
        },
        "nodes_after_restart": deepcopy(nodes),
        "post_restart_mmp": deepcopy(mmp),
        "post_restart_icmpv6": {
            "effective_mtu_boundary_payload_bytes": 1155,
            "echo_requests": 2,
            "passed": True,
        },
        "post_restart_payload_identity": payload(),
        "post_restart_fsp_session_counts": [1, 1],
        "disconnect": {
            "control_acknowledged": True,
            "peers_per_node_after": 0,
            "links_per_node_after": 0,
            "fsp_sessions_per_node_after": 0,
        },
    }
    result["cleanup"] = {
        "daemons_stopped": True,
        "faulted_daemon_reaped": True,
        "namespaces_removed": True,
        "persistent_identity_directory_removed": True,
    }
    result["limitations"] = ["One direct hard-failure lifecycle only."]
    return result


def valid_alternate_route_result():
    result = deepcopy(valid_result())
    result["evidence_type"] = "fips-g2-linux-alternate-route"
    result["topology"] = {
        "node_count": 4,
        "namespace_count": 4,
        "authenticated_link_count": 4,
        "isolation": "linux-network-namespaces",
        "underlay": "four-segment-diamond-ipv4-udp",
        "path_role": "redundant-managed-fips-transit",
        "public_discovery": False,
        "nostr_relay": False,
        "tun_name": "fips0",
        "configured_tun_mtu": 1280,
        "configured_udp_mtu": 1280,
        "identity_storage": "temporary-config-adjacent-key-files",
        "root_assignment": "lowest-derived-node-address-to-endpoint-a",
        "path_cost_bias": "r2-b-20ms-one-way-netem-delay",
    }
    digest = "a" * 64

    def payload():
        return {
            "protocol": "udp-over-ipv6-over-fips0-multihop",
            "records": [
                {"bytes": size, "sha256": digest, "exact_echo": True}
                for size in (1, 1024, 1155)
            ],
            "all_exact_echo": True,
        }

    result["observations"] = {
        "underlay_exclusion": {
            "transit_ipv4_forwarding_disabled": [True, True],
            "endpoint_direct_ipv4_probe_blocked": True,
            "direct_endpoint_underlay_link_absent": True,
        },
        "nodes": [
            {
                "node": node,
                "role": role,
                "tun_state": "active",
                "tun_name": "fips0",
                "kernel_tun_mtu": 1280,
                "effective_ipv6_mtu": 1203,
                "persistent_identity": True,
            }
            for node, role in (
                ("a", "endpoint-root"),
                ("r1", "managed-transit"),
                ("r2", "managed-transit"),
                ("b", "endpoint-leaf"),
            )
        ],
        "initial_topology": {
            "configured_auto_connect_peers": 4,
            "manual_connect_commands": 0,
            "authenticated_peer_counts": [2, 2, 2, 2],
            "authenticated_link_counts": [2, 2, 2, 2],
            "root_role": "a",
            "tree_depths": [0, 1, 1, 2],
            "endpoint_b_parent_role": "r1",
            "alternate_transit_authenticated": True,
            "alternate_path_one_way_delay_ms": 20,
            "full_mmp_link_views": 8,
            "transport": "udp",
        },
        "identity_resolution": {
            "mechanism": "local-fips-dns-npub",
            "endpoint_remote_identities_registered": True,
            "public_discovery_used": False,
        },
        "initial_payload_identity": payload(),
        "initial_path_selection": {
            "active_transit": "r1",
            "alternate_transit": "r2",
            "endpoint_b_parent_was_active_transit": True,
            "active_forwarded_packets_delta": 6,
            "active_forwarded_bytes_delta": 4096,
            "alternate_forwarded_packets_delta": 2,
            "alternate_forwarded_bytes_delta": 1024,
            "transit_fsp_session_counts": [0, 0],
        },
        "failure_injection": {
            "failed_role": "r1",
            "signal": "SIGKILL",
            "graceful_disconnect_sent": False,
            "process_exit_observed": True,
            "underlay_interfaces_left_up": True,
            "outage_probe_blocked": True,
        },
        "automatic_reparenting": {
            "tick_interval_secs": 1,
            "heartbeat_interval_secs": 10,
            "link_dead_timeout_secs": 30,
            "reparent_budget_secs": 60,
            "reparent_elapsed_ms": 31_500,
            "old_parent_role": "r1",
            "new_parent_role": "r2",
            "root_unchanged": True,
            "tree_depth_unchanged": True,
            "declaration_sequence_increased": True,
            "parent_loss_counter_increased": True,
            "manual_route_or_connect_commands": 0,
            "remaining_peer_counts": {"a": 1, "alternate": 2, "b": 1},
            "remaining_link_counts": {"a": 1, "alternate": 2, "b": 1},
        },
        "fsp_session_recovery": {
            "target_control_poll_interval_ms": 250,
            "control_poll_count": 80,
            "established_through_reparent_control_polls": True,
            "original_session_start_unchanged_through_reparent": [True, True],
            "idle_timeout_secs": 90,
            "manual_session_reset_commands": 0,
            "automatic_session_reestablishment_observed": True,
            "session_start_changed_per_endpoint": [True, True],
            "endpoint_session_counts_after_recovery": [1, 1],
            "alternate_transit_fsp_session_count": 0,
            "identity_values_retained": False,
        },
        "post_failure_icmpv6": {
            "effective_mtu_boundary_payload_bytes": 1155,
            "echo_requests": 2,
            "passed": True,
        },
        "post_failure_payload_identity": payload(),
        "post_failure_path": {
            "forwarding_transit": "r2",
            "forwarded_packets_delta": 6,
            "forwarded_bytes_delta": 4096,
            "failed_transit_unavailable": True,
            "payload_recovery_budget_secs": 180,
            "payload_recovery_elapsed_ms": 95_000,
        },
    }
    result["cleanup"] = {
        "daemons_stopped": True,
        "faulted_daemon_reaped": True,
        "namespaces_removed": True,
        "persistent_identity_directory_removed": True,
    }
    result["limitations"] = ["One Linux UDP diamond only."]
    return result


class PayloadProbeTests(unittest.TestCase):
    def test_payload_is_deterministic_and_exact_length(self):
        first = deterministic_payload(1155)
        second = deterministic_payload(1155)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1155)
        self.assertNotEqual(first[:32], deterministic_payload(32))

    def test_rejects_invalid_payload_size(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 65507"):
            deterministic_payload(0)


class Icmpv6PtbProbeTests(unittest.TestCase):
    def test_parses_raw_icmpv6_packet_too_big(self):
        packet = bytes([2, 0, 0, 0]) + (1203).to_bytes(4, "big") + b"payload"
        self.assertEqual(
            parse_packet_too_big(packet),
            {"icmpv6_type": 2, "icmpv6_code": 0, "reported_mtu": 1203},
        )

    def test_parses_packet_too_big_with_ipv6_header(self):
        header = bytearray(40)
        header[0] = 0x60
        header[6] = 58
        packet = bytes(header) + bytes([2, 0, 0, 0]) + (1203).to_bytes(4, "big")
        self.assertEqual(parse_packet_too_big(packet)["reported_mtu"], 1203)

    def test_rejects_non_ptb_icmpv6(self):
        packet = bytes([128, 0, 0, 0]) + b"\0\0\0\0"
        self.assertIsNone(parse_packet_too_big(packet))


class FipsLinuxRunnerContractTests(unittest.TestCase):
    def test_config_uses_ephemeral_identity_and_expected_mtu(self):
        config = render_config(Path("/tmp/rimf/control.sock"), "10.203.0.1")
        self.assertIn("persistent: false", config)
        self.assertNotIn("nsec", config)
        self.assertIn('name: "fips0"', config)
        self.assertEqual(config.count("mtu: 1280"), 2)

    def test_config_can_enable_loopback_only_fips_dns(self):
        config = render_config(
            Path("/tmp/rimf/control.sock"), "10.203.0.1", dns_enabled=True
        )
        self.assertIn('dns:\n  enabled: true\n  bind_addr: "::1"\n  port: 5354', config)

    def test_config_can_freeze_a_smaller_udp_transport_mtu(self):
        config = render_config(
            Path("/tmp/rimf/control.sock"),
            "10.203.0.1",
            udp_mtu=1000,
        )
        self.assertIn("tun:\n  enabled: true\n  name: \"fips0\"\n  mtu: 1280", config)
        self.assertIn('bind_addr: "10.203.0.1:2121"\n    mtu: 1000', config)

    def test_accepts_actual_release_connect_acknowledgement_shape(self):
        peer = "npub1test"
        address = "10.203.0.2:2121"
        self.assertTrue(
            valid_connect_acknowledgement(
                {"npub": peer, "address": address, "transport": "udp"},
                peer,
                address,
            )
        )
        self.assertFalse(
            valid_connect_acknowledgement(
                {"connected": True, "npub": peer},
                peer,
                address,
            )
        )

    def test_mesh_size_waits_through_null_observation(self):
        self.assertFalse(
            mesh_size_converged(
                [{"estimated_mesh_size": None}, {"estimated_mesh_size": 2}]
            )
        )
        self.assertTrue(
            mesh_size_converged(
                [{"estimated_mesh_size": 2}, {"estimated_mesh_size": 2}]
            )
        )

    def test_accepts_complete_result(self):
        validate_fips_g2_linux_direct_result(valid_result())

    def test_accepts_complete_schema_v2_mtu_result(self):
        validate_fips_g2_linux_direct_result(valid_direct_mtu_result())

    def test_rejects_schema_v2_without_above_mtu_observation(self):
        result = valid_direct_mtu_result()
        del result["observations"]["above_effective_mtu"]
        with self.assertRaisesRegex(ContractError, "schema v2"):
            validate_fips_g2_linux_direct_result(result)

    def test_rejects_wrong_packet_too_big_mtu(self):
        result = valid_direct_mtu_result()
        result["observations"]["above_effective_mtu"]["reported_mtu"] = 1280
        with self.assertRaisesRegex(ContractError, "above_effective_mtu"):
            validate_fips_g2_linux_direct_result(result)

    def test_rejects_wrong_effective_mtu(self):
        result = deepcopy(valid_result())
        result["observations"]["nodes"][0]["effective_ipv6_mtu"] = 1280
        with self.assertRaisesRegex(ContractError, "effective_ipv6_mtu"):
            validate_fips_g2_linux_direct_result(result)

    def test_rejects_incomplete_teardown(self):
        result = deepcopy(valid_result())
        result["cleanup"]["namespaces_removed"] = False
        with self.assertRaisesRegex(ContractError, "namespaces_removed"):
            validate_fips_g2_linux_direct_result(result)

    def test_recognizes_translated_ipv4_peer_endpoint(self):
        view = {"peers": [{"transport_addr": "10.204.0.254:42123"}]}
        self.assertTrue(translated_peer_observed(view, "10.204.0.254"))
        self.assertFalse(translated_peer_observed(view, "10.205.0.2"))
        self.assertFalse(translated_peer_observed({"peers": []}, "10.204.0.254"))

    def test_accepts_complete_nat_result(self):
        validate_fips_g2_linux_nat_result(valid_nat_result())

    def test_rejects_nat_result_without_directional_boundary(self):
        result = valid_nat_result()
        result["observations"]["directional_reachability"][
            "node_a_to_node_b_new_flow_blocked"
        ] = False
        with self.assertRaisesRegex(ContractError, "directional_reachability"):
            validate_fips_g2_linux_nat_result(result)

    def test_rejects_nat_result_without_translated_peer_observation(self):
        result = valid_nat_result()
        result["observations"]["nat"]["public_node_observed_translated_source"] = False
        with self.assertRaisesRegex(ContractError, "observations.nat"):
            validate_fips_g2_linux_nat_result(result)

    def test_rejects_nat_result_with_raw_endpoint_extension(self):
        result = valid_nat_result()
        result["observations"]["nat"]["translated_endpoint"] = "10.204.0.254:2121"
        with self.assertRaisesRegex(ContractError, "observations.nat"):
            validate_fips_g2_linux_nat_result(result)

    def test_recognizes_exact_three_node_line_relationships(self):
        identities = ["npub1a", "npub1r", "npub1b"]
        views = [
            {"peers": [{"npub": "npub1r"}]},
            {"peers": [{"npub": "npub1b"}, {"npub": "npub1a"}]},
            {"peers": [{"npub": "npub1r"}]},
        ]
        self.assertTrue(line_peer_relationships(views, identities))
        views[0]["peers"].append({"npub": "npub1b"})
        self.assertFalse(line_peer_relationships(views, identities))

    def test_extracts_transit_forwarding_counters(self):
        self.assertEqual(
            forwarding_counters(
                {"forwarding": {"forwarded_packets": 9, "forwarded_bytes": 2048}}
            ),
            (9, 2048),
        )

    def test_accepts_complete_managed_transit_result(self):
        validate_fips_g2_linux_managed_transit_result(valid_managed_transit_result())

    def test_extracts_learned_multihop_path_mtu(self):
        identity = "npub1remote"
        self.assertEqual(
            session_path_mtu(
                {
                    "sessions": [
                        {
                            "npub": identity,
                            "state": "established",
                            "mmp": {"path_mtu": 1000},
                        }
                    ]
                },
                identity,
            ),
            1000,
        )
        self.assertEqual(
            coordinate_cache_path_mtu(
                {"entries": [{"ipv6_addr": "fd00::2", "path_mtu": 1000}]},
                "fd00::2",
            ),
            1000,
        )

    def test_accepts_complete_multihop_mtu_result(self):
        validate_fips_g2_linux_multihop_mtu_result(valid_multihop_mtu_result())

    def test_rejects_multihop_mtu_without_learned_bottleneck(self):
        result = valid_multihop_mtu_result()
        result["observations"]["path_mtu"]["learned_transport_path_mtu"] = 1280
        with self.assertRaisesRegex(ContractError, "path_mtu"):
            validate_fips_g2_linux_multihop_mtu_result(result)

    def test_rejects_multihop_mtu_with_wrong_ptb_value(self):
        result = valid_multihop_mtu_result()
        result["observations"]["path_mtu"]["reported_mtu"] = 1203
        with self.assertRaisesRegex(ContractError, "path_mtu"):
            validate_fips_g2_linux_multihop_mtu_result(result)

    def test_reactive_config_freezes_identity_and_tick_window(self):
        config = render_config(
            Path("/tmp/rimf/control.sock"),
            "0.0.0.0",
            dns_enabled=True,
            udp_mtu=1000,
            persistent_identity=True,
            tick_interval_secs=5,
            static_udp_peers=(("npub1test", "10.206.0.1:2121"),),
        )
        self.assertIn("persistent: true", config)
        self.assertIn("tick_interval_secs: 5", config)
        self.assertIn("mtu: 1000", config)
        self.assertIn('npub: "npub1test"', config)
        self.assertIn('addr: "10.206.0.1:2121"', config)
        self.assertIn("connect_policy: auto_connect", config)

    def test_extracts_reactive_mtu_counters(self):
        routing = {
            "error_signals": {
                "mtu_exceeded": 2,
                "mtu_exceeded_below_floor": 0,
                "mtu_exceeded_uncorroborated": 0,
            },
            "forwarding": {
                "drop_mtu_exceeded_packets": 3,
                "drop_mtu_exceeded_bytes": 3840,
            },
        }
        self.assertEqual(mtu_error_counters(routing), (2, 0, 0))
        self.assertEqual(mtu_drop_counters(routing), (3, 3840))

    def test_accepts_complete_reactive_mtu_result(self):
        validate_fips_g2_linux_reactive_mtu_result(valid_reactive_mtu_result())

    def test_rejects_reactive_mtu_without_transit_drop(self):
        result = valid_reactive_mtu_result()
        result["observations"]["reactive_mtu"]["transit_drop_packets_delta"] = 0
        with self.assertRaisesRegex(ContractError, "signal convergence"):
            validate_fips_g2_linux_reactive_mtu_result(result)

    def test_rejects_reactive_mtu_with_wrong_trigger_transport(self):
        result = valid_reactive_mtu_result()
        result["observations"]["reactive_mtu"]["trigger_transport"] = "icmpv6"
        with self.assertRaisesRegex(ContractError, "signal convergence"):
            validate_fips_g2_linux_reactive_mtu_result(result)

    def test_rejects_reactive_mtu_session_replacement(self):
        result = valid_reactive_mtu_result()
        result["observations"]["transit_restart"][
            "endpoint_session_start_ms_after"
        ][1] += 1
        with self.assertRaisesRegex(ContractError, "continuity"):
            validate_fips_g2_linux_reactive_mtu_result(result)

    def test_rejects_reactive_mtu_without_link_epoch_replacement(self):
        result = valid_reactive_mtu_result()
        result["observations"]["transit_restart"]["endpoint_link_ids_after"] = [
            10,
            21,
        ]
        with self.assertRaisesRegex(ContractError, "continuity"):
            validate_fips_g2_linux_reactive_mtu_result(result)

    def test_rejects_managed_transit_without_forwarding(self):
        result = valid_managed_transit_result()
        result["observations"]["transit_forwarding"]["forwarded_packets"] = 0
        with self.assertRaisesRegex(ContractError, "forwarded_packets"):
            validate_fips_g2_linux_managed_transit_result(result)

    def test_rejects_managed_transit_that_terminates_fsp(self):
        result = valid_managed_transit_result()
        result["observations"]["transit_forwarding"]["transit_fsp_session_count"] = 1
        with self.assertRaisesRegex(ContractError, "transit role"):
            validate_fips_g2_linux_managed_transit_result(result)

    def test_lifecycle_config_freezes_persistent_auto_reconnect_contract(self):
        config = render_lifecycle_config(
            Path("/tmp/rimf/control.sock"),
            "10.206.0.1",
            peer_npub="npub1test",
            peer_address="10.206.0.2",
        )
        self.assertIn("persistent: true", config)
        self.assertIn("link_dead_timeout_secs: 30", config)
        self.assertIn('connect_policy: "auto_connect"', config)
        self.assertIn("auto_reconnect: true", config)

    def test_lifecycle_timing_contract_is_bounded(self):
        self.assertTrue(lifecycle_timings_within_contract(30_250, 6_200))
        self.assertFalse(lifecycle_timings_within_contract(60_001, 6_200))
        self.assertFalse(lifecycle_timings_within_contract(30_250, 90_001))

    def test_accepts_complete_lifecycle_result(self):
        validate_fips_g2_linux_lifecycle_result(valid_lifecycle_result())

    def test_rejects_lifecycle_manual_reconnect(self):
        result = valid_lifecycle_result()
        result["observations"]["automatic_reconnect"]["manual_reconnect_commands"] = 1
        with self.assertRaisesRegex(ContractError, "automatic_reconnect"):
            validate_fips_g2_linux_lifecycle_result(result)

    def test_rejects_lifecycle_identity_change(self):
        result = valid_lifecycle_result()
        result["observations"]["identity_continuity"]["public_identity_unchanged"] = False
        with self.assertRaisesRegex(ContractError, "identity_continuity"):
            validate_fips_g2_linux_lifecycle_result(result)

    def test_rejects_lifecycle_incomplete_fault_cleanup(self):
        result = valid_lifecycle_result()
        result["cleanup"]["faulted_daemon_reaped"] = False
        with self.assertRaisesRegex(ContractError, "cleanup"):
            validate_fips_g2_linux_lifecycle_result(result)

    def test_derives_fips_node_addr_from_snapshot_npub(self):
        self.assertEqual(
            node_addr_from_npub(
                "npub1sx42mj99aql52aklsg70y2jmr95u7uz2p40k769aw46ppjv302kqkhmu5r"
            ),
            "1b4788b7ab7a436a611fc59fb1e34c6e",
        )
        with self.assertRaisesRegex(ValueError, "checksum"):
            node_addr_from_npub(
                "npub1sx42mj99aql52aklsg70y2jmr95u7uz2p40k769aw46ppjv302kqkhmu5q"
            )

    def test_recognizes_exact_four_node_diamond_relationships(self):
        identities = ["npub1a", "npub1r1", "npub1r2", "npub1b"]
        views = [
            {"peers": [{"npub": "npub1r1"}, {"npub": "npub1r2"}]},
            {"peers": [{"npub": "npub1a"}, {"npub": "npub1b"}]},
            {"peers": [{"npub": "npub1b"}, {"npub": "npub1a"}]},
            {"peers": [{"npub": "npub1r2"}, {"npub": "npub1r1"}]},
        ]
        self.assertTrue(diamond_peer_relationships(views, identities))
        views[3]["peers"] = [{"npub": "npub1r1"}]
        self.assertFalse(diamond_peer_relationships(views, identities))

    def test_alternate_route_config_freezes_redundant_auto_peers(self):
        config = render_alternate_route_config(
            Path("/tmp/rimf/control.sock"),
            dns_enabled=True,
            peers=[
                ("r1", "npub1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqc8247j", "10.0.0.1"),
                ("r2", "npub1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqc8247j", "10.0.0.2"),
            ],
        )
        self.assertEqual(config.count('connect_policy: "auto_connect"'), 2)
        self.assertEqual(config.count("auto_reconnect: true"), 2)
        self.assertIn("persistent: true", config)
        self.assertIn("link_dead_timeout_secs: 30", config)
        self.assertIn("idle_timeout_secs: 90", config)
        self.assertIn('bind_addr: "0.0.0.0:2121"', config)

    def test_alternate_route_timing_contract_is_bounded(self):
        self.assertTrue(alternate_route_timings_within_contract(31_500, 95_000))
        self.assertFalse(alternate_route_timings_within_contract(60_001, 61_000))
        self.assertFalse(alternate_route_timings_within_contract(31_500, 180_001))
        self.assertFalse(alternate_route_timings_within_contract(31_500, 31_000))

    def test_accepts_complete_alternate_route_result(self):
        validate_fips_g2_linux_alternate_route_result(valid_alternate_route_result())

    def test_rejects_alternate_route_with_negative_alternate_counter(self):
        result = valid_alternate_route_result()
        result["observations"]["initial_path_selection"][
            "alternate_forwarded_packets_delta"
        ] = -1
        with self.assertRaisesRegex(ContractError, "non-negative"):
            validate_fips_g2_linux_alternate_route_result(result)

    def test_rejects_alternate_route_manual_reconnect(self):
        result = valid_alternate_route_result()
        result["observations"]["automatic_reparenting"][
            "manual_route_or_connect_commands"
        ] = 1
        with self.assertRaisesRegex(ContractError, "automatic_reparenting"):
            validate_fips_g2_linux_alternate_route_result(result)

    def test_rejects_alternate_route_without_fsp_session_restart(self):
        result = valid_alternate_route_result()
        result["observations"]["fsp_session_recovery"][
            "session_start_changed_per_endpoint"
        ] = [True, False]
        with self.assertRaisesRegex(ContractError, "session_recovery"):
            validate_fips_g2_linux_alternate_route_result(result)


if __name__ == "__main__":
    unittest.main()
