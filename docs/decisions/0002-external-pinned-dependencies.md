# ADR-0002: External pinned dependencies

- Status: accepted
- Date: 2026-08-29

## Context

FIPS is actively developed and its protocol and APIs are not stable. Robotweax SRT and SRT Telemetry
have different public-contract and maturity boundaries. Vendoring or privately linking them in the
first commit would couple the new project to implementation details before the integration evidence
exists.

## Decision

Keep FIPS, Robotweax SRT, and Robotweax SRT Telemetry external. Identify every build by repository,
full commit, profile, toolchain, and patch digest. Phase 1 uses `fips0` and public Robotweax SRT
interfaces. FIPS control-socket and SRT Telemetry adapters remain separate components.

Use both the pinned FIPS maintenance release and the pinned development assessment as distinct WP1
candidates until an experiment and ADR select the Phase 1 baseline.

## Consequences

- No git submodule, floating branch, package `latest`, or copied third-party source is accepted.
- Evidence must distinguish FIPS release and development candidates.
- Generic upstream capabilities should be proposed upstream first.
- A fork requires a patch budget, owner, rebase cadence, security-update gate, and exit condition.
