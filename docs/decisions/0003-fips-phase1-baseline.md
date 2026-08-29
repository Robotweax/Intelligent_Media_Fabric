# ADR-0003: FIPS Phase 1 baseline

- Status: accepted
- Date: 2026-08-29
- Closes: OD-02

## Context

ADR-0002 pinned a maintenance release and a development revision of FIPS for an evidence-based WP1
comparison. Phase 1 needs a stable transparent IP data plane through `fips0`; it does not need to
adopt an experimental application-facing transport API.

The candidates were checked out at clean, immutable revisions and built with their shared pinned
Rust 1.94.1 toolchain and locked dependency graphs. Source contracts, registered control commands,
build artifacts, full test suites, and a bounded release-candidate runtime smoke were assessed. The
retained evidence and scope boundaries are recorded in the
[WP1 assessment](../qualification/fips-wp1-assessment-2026-08-29.md).

## Decision

Use FIPS `v0.4.2` at commit `487fa86f65794071e3b91313c298d4f09b98b7fe` as the primary Phase 1
transparent-`fips0` baseline.

Keep the development candidate at commit `6b6d2a8df9fb6c6d5c2d1ba9e17e7bd0347dae73` pinned only for
observation and probe research. Do not use its experimental native API as the Phase 1 data plane,
and do not take a production dependency on its development-only control commands.

This decision selects a baseline; it does not pass G2. Linux TUN forwarding, NAT traversal, MTU
behavior, FSP traffic, and control observations still require the predeclared qualification matrix.

## Rationale

- The release candidate produced a clean locked release build and one complete passing test run:
  1,646 passed, zero failed, and six ignored.
- A two-daemon UDP loopback smoke established an authenticated link, exposed MMP observations, and
  acknowledged a clean disconnect through the supported control boundary.
- The development revision is a broad change set rather than a focused telemetry patch. Its first
  full test attempt had one intermittent native-API test failure; an isolated rerun and a second full
  run passed.
- The development native API is explicitly experimental and disabled by default. It does not
  provide acknowledgement, retransmission, ordering, or flow control, and its documented platform
  boundary is ambiguous.
- Neither candidate exposes the route pinning, route-selection mutation, disjoint-path selection, or
  multipath mutation needed for later active route control. Selecting development would not close
  that gap.

## Consequences

- Phase 1 configuration, scenarios, and evidence must name the exact release commit and artifact
  digests, not only the tag.
- FIPS remains an external daemon. No source vendoring, private linkage, or long-lived fork is
  authorized by this ADR.
- Control-socket collection remains observation-only. `connect` and `disconnect` are permitted in
  bounded qualification setup and teardown, not as production route policy.
- Development-only probes may inform an upstream proposal, but their results must remain segregated
  from the release data-plane qualification.
- Reconsider the baseline only after a new pinned release, a release-blocking defect, failed Linux
  qualification, or an accepted ADR with replacement evidence.

## Evidence

- [WP1 assessment report](../qualification/fips-wp1-assessment-2026-08-29.md)
- [Retained machine-readable assessment](../../qualification/retained-results/2026-08-29-fips-source-build-assessment-macos-arm64.json)
