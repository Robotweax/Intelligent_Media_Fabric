# Documentation index

- [Agent handoff for a new machine](../HANDOFF.md)

## Architecture and decisions

- [Strategy source and synchronization](strategy/README.md)
- [Architecture overview](architecture/overview.md)
- [ADR index](decisions/README.md)
- [Open decisions](decisions/open-decisions.md)
- [ADR-0001: Evidence-first project scope](decisions/0001-evidence-first-project-scope.md)
- [ADR-0002: External pinned dependencies](decisions/0002-external-pinned-dependencies.md)
- [ADR-0003: FIPS Phase 1 baseline](decisions/0003-fips-phase1-baseline.md)
- [ADR-0004: SRT Telemetry adapter boundary](decisions/0004-srt-telemetry-adapter-boundary.md)
- [ADR-0005: Historical SRT/FIPS refresh](decisions/0005-srt-fips-requalification.md)
- [ADR-0006: SRT 0.2.6 baseline](decisions/0006-srt-026-baseline.md)

## Security and protocols

- [Threat model](security/threat-model.md)
- [Device authorization draft](security/device-authorization-draft.md)
- [Review: SRT session authentication and ACP1 against the device-authorization draft](security/acp1-device-authorization-review-2026-11-12.md)
- [SRT-over-FIPS profile v0](protocols/srt-over-fips-profile-v0.md)

## Qualification

- [Evidence Lab](qualification/evidence-lab.md)
- [Gate registry](qualification/gate-registry.md)
- [FIPS WP1 assessment](qualification/fips-wp1-assessment-2026-08-29.md)
- [FIPS G2 Linux direct qualification](qualification/fips-g2-linux-direct-2026-08-29.md)
- [FIPS G2 Linux effective-MTU boundary qualification](qualification/fips-g2-linux-mtu-boundary-2026-08-30.md)
- [FIPS G2 Linux one-sided NAT qualification](qualification/fips-g2-linux-nat-2026-08-29.md)
- [FIPS G2 Linux managed-transit qualification](qualification/fips-g2-linux-managed-transit-2026-08-30.md)
- [FIPS G2 Linux lifecycle qualification](qualification/fips-g2-linux-lifecycle-2026-08-30.md)
- [FIPS G2 Linux alternate-route qualification](qualification/fips-g2-linux-alternate-route-2026-08-30.md)
- [FIPS G2 Linux heterogeneous multihop-MTU qualification](qualification/fips-g2-linux-multihop-mtu-2026-08-30.md)
- [FIPS G2 Linux fixed-delay MMP qualification](qualification/fips-g2-linux-delay-mmp-2026-08-30.md)
- [G4 unified-observation data-quality foundation](qualification/g4-unified-observation-data-quality-2026-08-30.md)
- [FIPS G2 reactive path-MTU capability gap](qualification/fips-g2-reactive-mtu-gap-2026-08-30.md)
- [Healthy SRT v0.2.6 over FIPS live capture](qualification/g4-live-capture-srt-026-2026-09-27.md)
- [Dependency refresh assessment 2026-10-22](qualification/dependency-refresh-2026-10-22.md)
- [FIPS v0.5.3 alternate-route qualification](qualification/fips-g2-linux-alternate-route-v0.5.3-2026-10-22.md)
- [Healthy SRT v0.3.0 over FIPS v0.5.3 live capture](qualification/g4-live-capture-srt-030-2026-10-22.md)
- [G1 direct-SRT baseline predeclared contract](qualification/g1-direct-srt-baseline-plan-2026-10-22.md)
- [G1 direct-SRT baseline, first retained run](qualification/g1-direct-srt-baseline-2026-10-22.md)
- [Dependency refresh assessment 2026-10-25 (SRT 0.3.1)](qualification/dependency-refresh-2026-10-25.md)
- [G1 direct-SRT baseline, second retained run (SRT v0.3.1)](qualification/g1-direct-srt-baseline-2026-10-25.md)
- [Healthy SRT v0.3.1 over FIPS v0.5.3 live capture](qualification/g4-live-capture-srt-031-2026-10-25.md)
- [G4 faulted-diamond experiment, first retained run](qualification/g4-faulted-diamond-2026-10-28.md)
- [G4 faulted-diamond experiment, repeat](qualification/g4-faulted-diamond-repeat-2026-10-28.md)
- [G4 faulted-diamond fast-FIPS-detection variant](qualification/g4-faulted-diamond-fast-detection-2026-10-30.md)
- [Healthy live capture at Telemetry 1b12f8d7](qualification/g4-live-capture-telemetry-1b12f8d7-2026-10-28.md)
- [G1 direct-SRT baseline, third retained run (Telemetry 1b12f8d7)](qualification/g1-direct-srt-baseline-2026-10-28.md)
- [Dependency refresh assessment 2026-11-12 (SRT 0.3.2)](qualification/dependency-refresh-2026-11-12.md)
- [G1 direct-SRT baseline, fourth retained run (SRT v0.3.2)](qualification/g1-direct-srt-baseline-2026-11-12.md)
- [Healthy SRT v0.3.2 over FIPS v0.5.3 live capture](qualification/g4-live-capture-srt-032-2026-11-12.md)
- [G4 faulted diamond at SRT v0.3.2, both timer profiles](qualification/g4-faulted-diamond-srt-032-2026-11-12.md)

Documents in this repository are pre-alpha engineering contracts unless explicitly marked otherwise.
The internal strategy in the SRT Knowledge Base is the decision context; public Robotweax SRT
documentation remains authoritative for released SRT behavior.
