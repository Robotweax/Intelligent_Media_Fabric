from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from rimf_lab.contracts import ContractError, validate_fips_g2_linux_direct_result
from rimf_lab.fips_g2_linux import (
    mesh_size_converged,
    render_config,
    valid_connect_acknowledgement,
)
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


class FipsLinuxRunnerContractTests(unittest.TestCase):
    def test_config_uses_ephemeral_identity_and_expected_mtu(self):
        config = render_config(Path("/tmp/rimf/control.sock"), "10.203.0.1")
        self.assertIn("persistent: false", config)
        self.assertNotIn("nsec", config)
        self.assertIn('name: "fips0"', config)
        self.assertEqual(config.count("mtu: 1280"), 2)

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


if __name__ == "__main__":
    unittest.main()
