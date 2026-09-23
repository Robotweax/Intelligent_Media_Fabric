# Gate registry

Statuses are `not-started`, `in-progress`, `passed`, `failed`, or `pivoted`. Only retained evidence
or an approved ADR can change a gate status.

| Gate | Status | Decision question | Minimum evidence |
| --- | --- | --- | --- |
| G0-A Contract Pack | in-progress | Are security- and measurement-critical choices explicit? | ADRs, pins, schemas, threat model, open-decision register |
| G0-B Harness Integrity | in-progress | Can the lab create reproducible, bounded, provenance-complete results? | CI, negative tests, scenario/result validation, harness smoke |
| G1 Direct SRT Baseline | not-started | Is the control correct and the harness non-distorting? | payload and timing validation, repeated direct runs |
| G2 FIPS Connectivity | in-progress | Does the selected FIPS baseline provide the documented connectivity and telemetry? | build provenance, Linux two-node TUN, NAT and managed-transit classes, direct and heterogeneous multihop MTU boundaries, direct-link lifecycle, bounded non-hitless alternate-route recovery, fixed-delay and fixed-loss MMP responses, control-socket observations |
| G3 Transparent SRT over FIPS | not-started | Does SRT over `fips0` meet frozen correctness and overhead budgets? | direct/FIPS scorecard, mandatory correctness, CPU/wire/timing evidence |
| G4 Unified Observation | in-progress | Can correlation identify the first divergent layer and fault domain? | accepted SRT adapter contract, route epochs, data-quality cases, retained cross-layer golden incidents |
| G5 SRT Group Resilience | not-started | What continuity can existing SRT groups provide across real fault domains? | broadcast/backup scorecard, downstream media gap |
| G6 FIPS Reconvergence | not-started | Can a running stream survive route change within budget? | route event, socket continuity, downstream timing, MTU transition |
| G7 Route Advisor | not-started | Are recommendations stable, explainable, and better than raw metrics? | deterministic replay, confidence, hysteresis, no mutation |
| G8 Route Control | not-started | Is FIPS control superior enough to justify upstream work or a patch stack? | SRT-group comparison, no flapping, fork/upstream ADR |
| G9 Generic Multipath | not-started | Does cross-protocol value justify FIPS-near multipath? | ordering, crypto, congestion, recovery, and resource qualification |

The 2026-09-19 refresh selects FIPS v0.5.1 and a new immutable SRT main snapshot for
[requalification](dependency-refresh-2026-09-19.md). Gate statuses remain unchanged; historical
v0.4.2 evidence is not automatically evidence for v0.5.1.

One [FIPS v0.5.1 four-node alternate-route experiment](fips-g2-linux-alternate-route-v0.5.1-2026-09-23.md)
passed on 2026-09-23 after correcting a fixed-parent harness assumption. This is
retained G2 evidence but does not alone pass G2 or establish hitless recovery.

The historical stock FIPS `v0.4.2` assessment could not place the reactive-MTU experiment into its required
state without route/session disruption or prior proactive MTU discovery. This is recorded as a
[capability gap](fips-g2-reactive-mtu-gap-2026-08-30.md), not a failed gate: G2 remains
`in-progress`, and no G6 claim has started. That capability gap has not yet been reassessed on v0.5.1.

G4 has a deterministic SRT adapter fixture, a paired synthetic clock-domain boundary case,
and one [healthy live SRT-over-FIPS pilot](g4-live-capture-2026-09-23.md). The analyzer correctly
returns `insufficient-evidence` for distinct `local-only` clocks. No faulted live cross-layer
incident, first-divergent-layer, or fault-domain claim exists yet; see the
[G4 data-quality foundation](g4-unified-observation-data-quality-2026-08-30.md).
The next [faulted-diamond experiment plan](g4-faulted-diamond-experiment-plan-2026-09-23.md)
is predeclared but not yet executable or qualifying evidence; it requires a
separate four-node runner and independent downstream decoder.

## Mandatory correctness rules

Every applicable experiment must prove:

- byte- or frame-exact payload identity;
- authorized device, tenant, service, and stream decisions;
- bounded memory and queues;
- explicit errors instead of silent downgrade;
- complete immutable provenance;
- explicit unavailability for absent measurements;
- a new route epoch for each route transition; and
- downstream validation before success.

Performance, failover, and operational thresholds are deliberately not frozen in this initial
commit. They require the pilot workflow, hardware class, design partner, and control-run calibration.
