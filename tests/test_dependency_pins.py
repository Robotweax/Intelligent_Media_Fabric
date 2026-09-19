from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from rimf_lab.fips_g2_linux import (
    EXPECTED_CARGO_LOCK_SHA256,
    EXPECTED_FIPS_COMMIT,
    EXPECTED_RUST_TOOLCHAIN_SHA256,
    QualificationError,
    _source_provenance,
    render_config,
)
from rimf_lab.fips_g2_linux_alternate_route import render_alternate_route_config
from rimf_lab.fips_g2_linux_delay_mmp import render_delay_mmp_config
from rimf_lab.fips_g2_linux_lifecycle import render_lifecycle_config
from rimf_lab.g4_srt_over_fips import EXPECTED_SRT_COMMIT, EXPECTED_TELEMETRY_COMMIT


ROOT = Path(__file__).resolve().parents[1]


class DependencyPinTests(unittest.TestCase):
    def test_manifest_matches_runner_pins(self):
        manifest = json.loads((ROOT / "dependency-pins/baselines.json").read_text())
        pins = {item["id"]: item["commit"] for item in manifest["dependencies"]}
        self.assertEqual(pins["robotweax-srt"], EXPECTED_SRT_COMMIT)
        self.assertEqual(pins["robotweax-srt-telemetry"], EXPECTED_TELEMETRY_COMMIT)
        self.assertEqual(pins["fips-release-candidate"], EXPECTED_FIPS_COMMIT)

    def test_all_live_workflows_match_runner_pins(self):
        workflows = list((ROOT / ".github/workflows").glob("fips-*.yml"))
        workflows.append(ROOT / ".github/workflows/g4-srt-over-fips-live.yml")
        self.assertEqual(len(workflows), 9)
        for workflow in workflows:
            with self.subTest(workflow=workflow.name):
                text = workflow.read_text()
                for key, value in (
                    ("FIPS_COMMIT", EXPECTED_FIPS_COMMIT),
                    ("FIPS_CARGO_LOCK_SHA256", EXPECTED_CARGO_LOCK_SHA256),
                    ("FIPS_RUST_TOOLCHAIN_SHA256", EXPECTED_RUST_TOOLCHAIN_SHA256),
                ):
                    self.assertRegex(text, rf"(?m)^  {key}: {re.escape(value)}$")
                self.assertIn("libclang-dev", text)
                self.assertNotIn("v0.4.2", text)
        live = workflows[-1].read_text()
        self.assertIn(f"SRT_COMMIT: {EXPECTED_SRT_COMMIT}", live)
        self.assertIn(f"TELEMETRY_COMMIT: {EXPECTED_TELEMETRY_COMMIT}", live)
        self.assertNotIn("/libsrt.so", live)
        self.assertIn("/librobotweax-srt.so", live)
        self.assertIn('ctest --test-dir "$TELEMETRY_BUILD" --output-on-failure', live)

    def test_old_source_cannot_qualify_new_baseline(self):
        with patch("rimf_lab.fips_g2_linux._run") as run:
            run.return_value.stdout = "487fa86f65794071e3b91313c298d4f09b98b7fe\n"
            with self.assertRaisesRegex(QualificationError, "baseline"):
                _source_provenance(ROOT)

    def test_configs_keep_native_api_and_rendezvous_disabled(self):
        configurations = [
            render_alternate_route_config(Path("/tmp/control.sock"), dns_enabled=False, peers=[]),
            render_config(Path("/tmp/control.sock"), "192.0.2.1"),
            render_delay_mmp_config(Path("/tmp/control.sock"), "192.0.2.1"),
            render_lifecycle_config(Path("/tmp/control.sock"), "192.0.2.1"),
        ]
        for config in configurations:
            self.assertIn("  native_api:\n    enabled: false", config)
            self.assertIn("  rendezvous:\n    nostr:\n      enabled: false\n    lan:\n      enabled: false", config)
            self.assertNotIn("  discovery:", config)
            self.assertIn('  name: "fips0"', config)

    def test_source_guard_rejects_dirty_tree_and_digest_mismatch(self):
        for dirty, digests, expected in (
            (" M Cargo.toml", [], "dirty"),
            ("", ["0" * 64, EXPECTED_RUST_TOOLCHAIN_SHA256], "Cargo.lock"),
            ("", [EXPECTED_CARGO_LOCK_SHA256, "0" * 64], "rust-toolchain"),
        ):
            with self.subTest(expected=expected):
                with patch("rimf_lab.fips_g2_linux._run") as run, patch(
                    "rimf_lab.fips_g2_linux.sha256_file", side_effect=digests
                ):
                    run.side_effect = [
                        subprocess.CompletedProcess([], 0, EXPECTED_FIPS_COMMIT),
                        subprocess.CompletedProcess([], 0, dirty),
                    ]
                    with self.assertRaisesRegex(QualificationError, expected):
                        _source_provenance(ROOT)

    def test_source_guard_accepts_exact_clean_candidate(self):
        with patch("rimf_lab.fips_g2_linux._run") as run, patch(
            "rimf_lab.fips_g2_linux.sha256_file",
            side_effect=[EXPECTED_CARGO_LOCK_SHA256, EXPECTED_RUST_TOOLCHAIN_SHA256],
        ):
            run.side_effect = [
                subprocess.CompletedProcess([], 0, EXPECTED_FIPS_COMMIT),
                subprocess.CompletedProcess([], 0, ""),
            ]
            self.assertEqual(_source_provenance(ROOT)["fips_commit"], EXPECTED_FIPS_COMMIT)
