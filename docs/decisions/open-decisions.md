# Open decisions

These questions block claims or later phases, but they do not block the bounded Phase 0 bootstrap.
Each must close through an accepted ADR or a predeclared experiment. An unknown value must not be
replaced with an implicit implementation default.

| ID | Decision | Blocks | Closure |
| --- | --- | --- | --- |
| OD-01 | Pilot contribution workflow and downstream interruption budget | G3 | Product input plus calibrated direct baseline |
| OD-03 | First Robotweax SRT crypto profile | G3 | Security/performance experiment and ADR |
| OD-04 | Conservative MTU and media-payload profile | G3 | Packet-budget qualification |
| OD-05 | Simpler secure-network comparison baseline | Go/Pivot | Architecture ADR |
| OD-06 | Private discovery and Nostr relay operation | Product pilot | Threat model and deployment ADR |
| OD-07 | Device credential, revocation, and offline policy | G3 security | Credential ADR and adversarial tests |
| OD-09 | Missing FIPS route/path events for a qualified advisor | G7 | WP1 inventory and upstream proposal |
| OD-10 | Generic capabilities proposed upstream | G8 | Upstream issue/design record |
| OD-11 | SRT-group topologies with proven independent fault domains | G5 | Topology experiment |
| OD-12 | Repository licensing, OEM, contribution signing, and CODEOWNERS | First external contribution | Owner decision and ADR |
| OD-13 | Software-only, appliance-near, or OEM-embedded pilot | Product pilot | Product/deployment ADR |
| OD-14 | Design partners and frozen goodput, CPU, failover, and operations gates | G3/product pilot | Product decision and gate update |
| OD-15 | Response to non-hitless FIPS alternate-route recovery | G6 | FIPS/SRT resilience comparison and ADR selecting improvement, bounded workaround, or pivot |
| OD-16 | Runtime FIPS peer/path mutation surface for reactive MTU qualification | G6 | ADR selecting an upstream daemon control operation, an in-place MTU update, an embedded-library baseline, or a pivot; then pass the frozen acceptance contract |

## Immediate order

OD-02 is closed by [ADR-0003](0003-fips-phase1-baseline.md) after the WP1 comparison. OD-08 is closed
by [ADR-0004](0004-srt-telemetry-adapter-boundary.md); G4 still requires retained cross-layer
data-quality and golden-incident evidence. OD-01, OD-03, OD-04, and OD-14 must close before G3 can
pass. OD-12 must close before an external contributor or distributable artifact is accepted. OD-15
must close before G6 can pass; the retained FIPS result proves route reparenting but not a usable
session or media continuity. OD-16 must close before a reactive path-MTU result can contribute to
G6; the current stock-daemon limitation and acceptance contract are documented in the
[reactive path-MTU capability-gap assessment](../qualification/fips-g2-reactive-mtu-gap-2026-08-30.md).
