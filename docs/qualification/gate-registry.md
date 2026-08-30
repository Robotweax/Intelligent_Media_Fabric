# Gate registry

Statuses are `not-started`, `in-progress`, `passed`, `failed`, or `pivoted`. Only retained evidence
or an approved ADR can change a gate status.

| Gate | Status | Decision question | Minimum evidence |
| --- | --- | --- | --- |
| G0-A Contract Pack | in-progress | Are security- and measurement-critical choices explicit? | ADRs, pins, schemas, threat model, open-decision register |
| G0-B Harness Integrity | in-progress | Can the lab create reproducible, bounded, provenance-complete results? | CI, negative tests, scenario/result validation, harness smoke |
| G1 Direct SRT Baseline | not-started | Is the control correct and the harness non-distorting? | payload and timing validation, repeated direct runs |
| G2 FIPS Connectivity | in-progress | Does the selected FIPS baseline provide the documented connectivity and telemetry? | build provenance, Linux two-node TUN, NAT and managed-transit classes, direct and heterogeneous multihop MTU boundaries, direct-link lifecycle, bounded non-hitless alternate-route recovery, control-socket observations |
| G3 Transparent SRT over FIPS | not-started | Does SRT over `fips0` meet frozen correctness and overhead budgets? | direct/FIPS scorecard, mandatory correctness, CPU/wire/timing evidence |
| G4 Unified Observation | not-started | Can correlation identify the first divergent layer and fault domain? | route epochs, data-quality cases, retained golden incidents |
| G5 SRT Group Resilience | not-started | What continuity can existing SRT groups provide across real fault domains? | broadcast/backup scorecard, downstream media gap |
| G6 FIPS Reconvergence | not-started | Can a running stream survive route change within budget? | route event, socket continuity, downstream timing, MTU transition |
| G7 Route Advisor | not-started | Are recommendations stable, explainable, and better than raw metrics? | deterministic replay, confidence, hysteresis, no mutation |
| G8 Route Control | not-started | Is FIPS control superior enough to justify upstream work or a patch stack? | SRT-group comparison, no flapping, fork/upstream ADR |
| G9 Generic Multipath | not-started | Does cross-protocol value justify FIPS-near multipath? | ordering, crypto, congestion, recovery, and resource qualification |

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
