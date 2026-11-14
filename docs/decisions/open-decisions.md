# Open decisions

These questions block claims or later phases, but they do not block the bounded Phase 0 bootstrap.
Each must close through an accepted ADR or a predeclared experiment. An unknown value must not be
replaced with an implicit implementation default.

| ID | Decision | Blocks | Closure |
| --- | --- | --- | --- |
| OD-01 | Pilot contribution workflow (the interruption budget is set by [ADR-0012](0012-interruption-budget.md): hitless target, 6 s single-path floor) | G3 | Product input plus calibrated direct baseline |
| OD-03 | First Robotweax SRT crypto profile | G3 | Security/performance experiment and ADR |
| OD-04 | Conservative MTU and media-payload profile | G3 | Packet-budget qualification |
| OD-05 | Simpler secure-network comparison baseline | Go/Pivot | Architecture ADR |
| OD-06 | Private discovery and Nostr relay operation | Product pilot | Threat model and deployment ADR |
| OD-07 | Device credential, revocation, and offline policy | G3 security | Credential ADR and adversarial tests |
| OD-09 | Missing FIPS route/path events for a qualified advisor | G7 | WP1 inventory and upstream proposal |
| OD-10 | Generic capabilities proposed upstream | G8 | Upstream issue/design record |
| OD-11 | SRT-group topologies with proven independent fault domains | G5 | Topology experiment |
| OD-12 | OEM model, contribution signing, and CODEOWNERS (repository licensing closed by [ADR-0011](0011-mit-license-and-public-repository.md)) | First external contribution | Owner decision and ADR |
| OD-13 | Software-only, appliance-near, or OEM-embedded pilot | Product pilot | Product/deployment ADR |
| OD-14 | Design partners and frozen goodput, CPU, failover, and operations gates | G3/product pilot | Product decision and gate update |
| OD-16 | Runtime FIPS peer/path mutation surface for reactive MTU qualification | G6 | ADR selecting an upstream daemon control operation, an in-place MTU update, an embedded-library baseline, or a pivot; then pass the frozen acceptance contract |

## Immediate order

OD-02 is closed by [ADR-0003](0003-fips-phase1-baseline.md) after the WP1 comparison. OD-08 is closed
by [ADR-0004](0004-srt-telemetry-adapter-boundary.md). G4 is in progress with a synthetic negative
clock-boundary case and a [reviewed healthy live result](../qualification/g4-live-capture-2026-09-23.md). A faulted route
transition, independent downstream media observation, and first-divergent-layer evidence are still
required. OD-01, OD-03, OD-04, and OD-14 must close before G3 can pass. OD-12 must close before
an external contributor or distributable artifact is accepted. OD-15 is closed by
[ADR-0014](0014-continuity-by-srt-group.md): continuity across a path loss comes from an SRT group,
and FIPS reconvergence is judged as recovery against ADR-0012's 6 s floor. The group over FIPS rests
on a lab routing step until FIPS offers two identities or two paths per host; the capability request
belongs to OD-10, and OD-11 stays open. A
[draft of that request](upstream-request-fips-two-identities-per-host-2026-11-14.md) exists and has not
been sent.
OD-16 must close before a reactive path-MTU result can contribute to G6; the current stock-daemon
limitation and acceptance contract are documented in the
[reactive path-MTU capability-gap assessment](../qualification/fips-g2-reactive-mtu-gap-2026-08-30.md).
