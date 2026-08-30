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
| OD-08 | Shared telemetry primitives without widening the SRT provider contract | G4 | Adapter contract ADR |
| OD-09 | Missing FIPS route/path events for a qualified advisor | G7 | WP1 inventory and upstream proposal |
| OD-10 | Generic capabilities proposed upstream | G8 | Upstream issue/design record |
| OD-11 | SRT-group topologies with proven independent fault domains | G5 | Topology experiment |
| OD-12 | Repository licensing, OEM, contribution signing, and CODEOWNERS | First external contribution | Owner decision and ADR |
| OD-13 | Software-only, appliance-near, or OEM-embedded pilot | Product pilot | Product/deployment ADR |
| OD-14 | Design partners and frozen goodput, CPU, failover, and operations gates | G3/product pilot | Product decision and gate update |
| OD-15 | Response to non-hitless FIPS alternate-route recovery | G6 | FIPS/SRT resilience comparison and ADR selecting improvement, bounded workaround, or pivot |

## Immediate order

OD-02 is closed by [ADR-0003](0003-fips-phase1-baseline.md) after the WP1 comparison. OD-01, OD-03,
OD-04, and OD-14 must close before G3 can pass. OD-12 must close before an external contributor or
distributable artifact is accepted. OD-15 must close before G6 can pass; the retained FIPS result
proves route reparenting but not usable-session or media continuity.
