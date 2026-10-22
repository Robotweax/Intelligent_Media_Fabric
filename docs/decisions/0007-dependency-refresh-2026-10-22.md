# ADR-0007: Refresh SRT, SRT Telemetry, FIPS and CI toolchain candidates

- Status: accepted
- Date: 2026-10-22
- Supersedes ADR-0006 for new dependency selections; its evidence policy is retained

## Decision

Pin the following immutable revisions for new Fabric experiments:

| Component | Selected revision | Replaces |
| --- | --- | --- |
| Robotweax SRT v0.2.9 | `a87779d9c3d831583d32b2f61cae5b81edb05537` | v0.2.6 `50cba37b` |
| Robotweax SRT Telemetry (main, 2026-10-22) | `2447548388a47aaac647bb2eafdc4f9e962f0baa` | `bf10da04` |
| FIPS v0.5.3 | `f4a5b4a8e61e340e6be7551608109a5c399f8353` | v0.5.1 `c5aeef39` |

All three are **requalification candidates**, not qualified releases, gate passages or a
production rollout. Both retained healthy G4 bundles (SRT 0.2.4 at `def14a7b`, SRT 0.2.6 at
`50cba37b`) stay evidence only for their own recorded revisions and are accepted by the
validator only when their original `result.json` matches the digest recorded in
`HISTORICAL_G4_BUNDLES`. A new run cannot present any historical pin as the active candidate.

Move the pinned GitHub Actions to their current majors at immutable commits:
`actions/checkout` v7.0.1, `actions/setup-python` v7.1.0, `actions/upload-artifact` v7.0.2
and `actions/cache` v6.1.0. The `ubuntu-24.04` runner, Rust 1.94.1 and the FIPS
`rust-toolchain.toml` digest are unchanged; the FIPS `Cargo.lock` digest moves to
`70b1e2a25c3d626f9b4c006ab46456075f1ffdde0c2fd1a7529752aaf21e5b8a`.

## Why these revisions and not others

**SRT v0.2.9, not v0.3.0.** The `v0.3.0` tag exists upstream but its own release notes and
changelog record it as an unpublished candidate whose shared-library ABI line moves from 0.2
to 0.3. v0.2.9 is the latest published release (2026-10-13). It keeps ABI line 0.2 and the
SRT 1.5.7 compatibility profile, preserves every prior C export, and adds only versioned
getters. Its content is relevant to Fabric: Backup-member cursor resumption, bounded
idle-expired channel retirement, default-off Standby RTT monitoring, accepted `SRTO_GROUPTYPE`,
and bounded listener handshake handoff. 0.2.7 and 0.2.8 between the pins corrected Live/File
loss reporting, moved the sender too-late-drop deadline to first transmission, added
default-off session authentication v2, and matched Haivision 1.5.7 Live NAK policy. None of
this is Fabric-over-FIPS evidence; each item that touches continuity or timing must be
re-measured. Select v0.3.0 only through a separate ADR once it is published and the
Telemetry adapter has been requalified against ABI line 0.3.

**SRT Telemetry main.** The pinned adapter is a pre-alpha dependency with no release tags.
The 95 commits since `bf10da04` add connection-group observation, Backup sender-authority and
Standby RTT observations, JSONL recording schema `1alpha2`, named SDK threads, peer-metadata
snapshots and documentation for SRT 0.2.9/0.3.0. Features that need SRT 0.3.0 symbols are
compile-time gated, so the head builds against v0.2.9 headers. The G4 workflow continues to
build the adapter against the pinned SRT and run its complete test suite before any capture.
ADR-0004's boundary is unchanged: Fabric consumes the versioned public C ABI and source
recordings only, and adds explicit correlation context without reinterpreting SRT fields.
Any recording-schema change surfaces in the Fabric adapter golden case, which must be
regenerated and reviewed, never relaxed.

**FIPS v0.5.3.** Published 2026-10-16. Relevant changes since v0.5.1: an established session
that loses its route now re-looks-up the destination instead of staying dark until the 90 s
idle timeout; a single forged or reflected `PathBroken` no longer deletes verified
coordinates; a node whose tree parent moves to a worse root switches at once; `show_links`
now reports real traffic counters; `show_peers.connectivity` can report `stale`; the
`discovery` control-socket metric family is deprecated in favour of `lookup` (the Fabric
alternate-route collector already prefers `lookup`); and `fips` refuses to start on an
empty configuration. The session re-lookup fix bears directly on the non-hitless
alternate-route observation behind OD-15, so that scenario must be rerun rather than
reinterpreted. `node.rekey.enabled: false` is deprecated and is not used by lab configs.

**Actions majors.** Each new major moves to the Node 24 runtime and ESM internals; every input
the workflows use (`repository`, `ref`, `token`, `path`, `persist-credentials`,
`python-version`, `name`, `if-no-files-found`, `retention-days`, `key`) exists unchanged.
`actions/checkout` v7 additionally refuses fork checkouts under `pull_request_target`; no
Fabric workflow uses that trigger.

## Requalification required before promotion

1. Rerun all eight FIPS G2 Linux workflows on v0.5.3 with unchanged acceptance budgets. A
   failed run must be retained under `qualification/failure-results`, not hidden by a rerun.
2. Build SRT v0.2.9 and Telemetry `24475483` together on Linux and pass the complete Telemetry
   suite, then repeat the healthy SRT-over-FIPS G4 capture and retain a new bundle. Do not edit
   the 0.2.4 or 0.2.6 bundles.
3. Rerun the alternate-route scenario before reclassifying OD-15; the v0.5.3 session re-lookup
   is a candidate explanation only after it is observed under the same topology.
4. G1, G3 and the faulted-diamond G4 plan keep their prerequisites from ADR-0006 and the gate
   registry. No gate status changes with this ADR.

## Local preliminary checks (2026-10-22)

See the [refresh assessment](../qualification/dependency-refresh-2026-10-22.md) for what was
and was not verified before the Linux workflows ran.

## Sources

- [Robotweax SRT v0.2.9 release](https://github.com/Robotweax/srt/releases/tag/v0.2.9)
- [SRT 0.2.9 release notes](https://github.com/Robotweax/srt/blob/v0.2.9/docs/release-notes-0.2.9.md)
- [SRT 0.3.0 candidate notes (unpublished)](https://github.com/Robotweax/srt/blob/v0.3.0/docs/release-notes-0.3.0.md)
- [SRT Telemetry pinned source](https://github.com/Robotweax/srt_telemetry/tree/2447548388a47aaac647bb2eafdc4f9e962f0baa)
- [FIPS v0.5.3 release](https://github.com/jmcorgan/fips/releases/tag/v0.5.3)
- [FIPS changelog at v0.5.3](https://github.com/jmcorgan/fips/blob/v0.5.3/CHANGELOG.md)
- [Prior Fabric refresh decision](0006-srt-026-baseline.md)
