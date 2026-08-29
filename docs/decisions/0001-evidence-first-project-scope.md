# ADR-0001: Evidence-first project scope

- Status: accepted
- Date: 2026-08-29

## Context

The product vision spans identity, secure reachability, media transport, telemetry, resilience,
operations, and future path control. FIPS does not currently provide the generic, controllable
end-to-end multipath behavior assumed by the original concept. Robotweax SRT already provides
reliability, FEC, telemetry, and connection-group primitives that need to be measured first.

## Decision

Authorize Phase 0A, Phase 0B, and experiments required to reach the Phase 1 decision gate.

The first product code is preceded by explicit contracts. The first executable code is an evidence
harness, not a production agent. Claims require retained, provenance-complete results. Work proceeds
through separate gates for transparent SRT over FIPS, unified observation, SRT-group resilience,
FIPS route intelligence, and only then generic multipath research.

## Consequences

- A dashboard or control plane is not a valid first milestone.
- Socket survival alone cannot satisfy the media-continuity gate.
- Failed data-plane economics may pivot the project to FIPS identity and reachability with SRT-group
  resilience.
- A stopped data-plane hypothesis may still leave valuable telemetry and operations assets.
- Unapproved thresholds are recorded as open gates rather than invented targets.
