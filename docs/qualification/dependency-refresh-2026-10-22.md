# Dependency refresh assessment — 2026-10-22

Status: candidates selected by [ADR-0007](../decisions/0007-dependency-refresh-2026-10-22.md);
Linux requalification pending; no gate status changed.

This records what was checked before the Linux workflows ran on the new pins. It is not
SRT-over-FIPS evidence and does not supersede the retained results or bundles.

## Selected sources

| Component | Previous | Selected | Immutable commit |
| --- | --- | --- | --- |
| Robotweax SRT | v0.2.6 | v0.3.0 (tagged 2026-10-14) | `4ae6330d62f2b5030d96964bf3500283f32dd39c` |
| Robotweax SRT Telemetry | `bf10da04` | main, 2026-10-22 | `2447548388a47aaac647bb2eafdc4f9e962f0baa` |
| FIPS | v0.5.1 | v0.5.3 (published 2026-10-16) | `f4a5b4a8e61e340e6be7551608109a5c399f8353` |

FIPS `Cargo.lock` SHA-256: `70b1e2a25c3d626f9b4c006ab46456075f1ffdde0c2fd1a7529752aaf21e5b8a`.
`rust-toolchain.toml` SHA-256 unchanged: `6a95738ee0eea5867a071922541a1ccaac80c63ccba5c947eb78b6130e1b22d3`
(Rust 1.94.1). Both measured from the clean v0.5.3 checkout. All nine workflows, the runner
source guards and the versioned build-cache key (`fips-v0.5.3-rust-1.94.1-70b1e2a25c3d`) agree
with `dependency-pins/baselines.json`.

Note on v0.3.0: its in-tree release notes still read "candidate preparation; not published".
The owner confirmed on 2026-10-22 that this wording is stale and v0.3.0 is the latest release;
v0.2.9 was the working selection for part of this refresh and was replaced before merge.

GitHub Actions moved to immutable commits of their current majors (Node 24 runtime):
checkout `3d3c42e5` (v7.0.1), setup-python `6d4fd22b` (v7.1.0), upload-artifact
`cf430e03` (v7.0.2), cache `55cc8345` (v6.1.0). Every workflow input in use exists on the new
majors; no Fabric workflow uses `pull_request_target`.

## Upstream deltas examined

- **SRT 0.2.7 → 0.3.0**: ABI line moves to 0.3 at 0.3.0 (rebuild required; SRT API 1.5.7
  retained; every prior C export name kept in the frozen 0.3.0 snapshot). Changes touching continuity or timing: sender too-late-drop
  deadline measured from first transmission, Live DATA continuing one refresh period on a late
  key-rotation response, Haivision-matched Live NAK policy, Backup cursor resumption, bounded
  idle-channel retirement, bounded listener handshake handoff. None is Fabric evidence.
- **SRT Telemetry**: 95 commits. Group observation, Backup sender-authority, Standby RTT,
  recording schema `1alpha2` (embedding `jsonl=DIR` default only; the recorder export the
  incident peer uses still writes `1alpha1`), named threads, peer metadata. The 0.3.0-only
  paths (peer identity, listener extension policies) are now compiled in. The incident peer gained four optional flags
  (`--too-late-packet-drop`, `--message-ttl-ms`, `--receive-timeout-ms`,
  `--verify-message-sequence`); unchanged invocations keep the previous defaults (receive
  timeout 15 s, no TLPKTDROP override), and the workflow's `--help` sentinels still match.
- **FIPS 0.5.2 → 0.5.3**: session re-lookup after route loss, `PathBroken` quorum, immediate
  parent switch on worse-root move, TreeAnnounce resend, monotonic bloom debounce, real
  `show_links` counters, `stale` peer connectivity, `discovery` metric family deprecated for
  `lookup`, start refusal on an empty config, per-peer connected UDP sockets after address
  change or NAT traversal, heartbeat send failures not counted as delivered. The Fabric
  collectors already prefer `lookup` and do not read `connectivity`; lab configs are not empty
  and do not set `node.rekey.enabled`.

## Local verification (Linux x86_64, this workspace)

- Fabric: `make check` passed — 129 unit/contract tests, retained-evidence and repository
  validation. Both retained G4 bundles validate under the new digest-locked historical table;
  rewriting either bundle's manifest, recordings or provenance is rejected.
- SRT v0.3.0 built as the namespaced shared library (ABI 0.3) with the workflow's CMake flags
  (GCC 13.3, CMake 3.28, OpenSSL 3.0.13).
- Telemetry `24475483` configured against the v0.3.0 headers and `librobotweax-srt.so` with
  `ROBOTWEAX_SRT_TELEMETRY_RUNTIME_TEST_PROVIDER=robotweax-srt`, built, and its CTest suite ran
  (72 tests at this revision, up from 42 at `bf10da04`): **72/72 passed**, including the
  `public_srt_fault_lab` gate (14/14 scenarios, sender advice 10/10, receiver advice 8/8) and
  the lifecycle, recording-schema and incident-peer checks; the `--help` sentinels the G4
  workflow greps for are present. The JSONL recording test is skipped by the suite itself.
- An earlier pass of the same procedure against SRT v0.2.9 (the interim selection) built and
  scored 71/72: all 14 `public_srt_fault_lab` scenarios reached their expected verdicts, but the
  gate's sender-advice criterion scored 9/10 (`maxbw_too_low`, 10 wrong advice reads from 9.1 s)
  on this 2-vCPU container. That is a timing-sensitive health-engine gate under local load, not
  a build or ABI incompatibility; it is recorded, not carried forward.
- FIPS was not built locally; the workflows build it with the pinned toolchain.

| Local check | Outcome |
| --- | --- |
| Fabric unit/contract/validation | passed (129) |
| SRT v0.3.0 shared build | passed |
| Telemetry build against v0.3.0 (ABI 0.3) | passed |
| Telemetry CTest suite | 72/72 passed |

## Linux qualification

PENDING_WORKFLOWS

## Limits

Local builds establish compile and adapter-suite compatibility only. No FIPS runtime, no
`fips0` data plane, no SRT-over-FIPS capture and no faulted path was exercised here. Historical
retained results and bundles are unchanged and remain evidence only for their own revisions.
The v0.5.3 session re-lookup fix is a candidate explanation for the non-hitless alternate-route
recovery behind OD-15 only after it is observed under the same four-node topology; it must not
be assumed. Promotion of any candidate still requires the eight G2 workflows and a new healthy
G4 bundle, and neither passes G2, G3 or G4 on its own.
