# ADR-0012: Downstream interruption budget for a single transit failure

- Status: accepted
- Date: 2026-11-13
- Closes the interruption-budget part of OD-01. The pilot workflow, the steady-state gates and design partners (rest of OD-01, OD-14) stay open.

## Decision

The repository owner chose, on 2026-11-13, from the
[budget proposal](proposal-pilot-budgets-2026-11-13.md):

1. **Target: hitless.** The loss of one transit must not remove or change a single
   downstream frame.
2. **Floor for a single path: 6 s with the SRT session kept.** A single SRT session over one
   FIPS route must have downstream media back within 6 s of the fault, without a new session.

Both are measured as the faulted-diamond experiment measures them: at an independent
downstream collector, with the frame comparison against the fixture's own decode.

## What the retained evidence says against these numbers

This is a reading of existing runs, not a gate result. No run was predeclared against a budget.

- **Target:** no retained run meets it. The smallest retained gap is 4.2 s. A single session
  over FIPS reconvergence cannot meet it at any tested timer.
- **Floor:** the six retained runs with FIPS link-dead 3 s and a 60 s SRT peer-idle timeout
  had gaps of 4.2 to 5.3 s. The eight runs at the stock 30 s link-dead timer had 31.2 to
  32.5 s and do not meet it. With SRT's default 5 s peer-idle timeout the session ended in
  all six runs, so the floor is not met there either, restart or not.

## Consequences

- The continuity claim moves to redundant paths. The SRT-group comparison that OD-15 asks for
  is the next experiment, and G5 is the gate that can carry a hitless result. Its
  [design](../qualification/srt-group-comparison-design-2026-11-13.md) is drafted separately.
- The floor depends on two settings that are not qualified. FIPS link-dead 3 s has an
  unmeasured false-reap risk on lossy and slow links; it must be qualified there before the
  floor can be claimed. An SRT peer-idle timeout above the 5 s default becomes part of any
  single-path pilot profile.
- G6 ("can a running stream survive a route change within budget") now has a budget: 6 s.
  G6 stays `not-started`; this ADR starts no gate and passes none.
- Future faulted runs may be predeclared against these numbers. Retained runs stay ungraded.
