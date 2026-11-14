# Proposal: response to non-hitless FIPS recovery (OD-15) — 2026-11-14

- Status: proposal for the repository owner. Question 1 of section 6 was decided on 2026-11-14 (answer A) and is recorded in [ADR-0014](0014-continuity-by-srt-group.md), which closes OD-15; question 2 was answered on 2026-11-14 with a [draft request](upstream-request-fips-two-identities-per-host-2026-11-14.md) that has not been sent; questions 3 and 4 are open. The proposal itself changes no gate and starts no run.

OD-15 asks for a FIPS/SRT resilience comparison and an ADR that selects **improvement**,
**bounded workaround** or **pivot**. The comparison now exists as retained evidence. This note
reads it and proposes the selection.

## 1. What the retained evidence says

One diamond, one stream (160 s MPEG-TS, 1 Mbit/s), one fault (the transit carrying the stream
is lost 20 s in), one independent downstream measurement. The single-session rows count every
retained faulted-diamond bundle, at SRT v0.3.1 and v0.3.2 and FIPS v0.5.3; the group rows are
at SRT v0.3.2, Telemetry `d03ca452` and, for stage 2, FIPS v0.5.3.

| Arrangement | Downstream gap | Frames missing of 4,000 | Runs | Record |
| --- | --- | --- | --- | --- |
| One session over FIPS, link-dead 30 s (stock), SRT peer idle 60 s | 31.2 to 32.5 s | 757 to 789 | 10 | [latest](../qualification/telemetry-d03ca452-requalification-2026-11-13.md) |
| One session over FIPS, link-dead 3 s, SRT peer idle 60 s | 4.2 to 5.3 s | 83 to 109 | 8 | same |
| One session over FIPS, both products at stock settings | media does not return | 3,501 | 8 | same |
| The same, session restarted by the coordinator | 6.3 to 6.4 s (link-dead 3 s) and 32.5 to 32.9 s (30 s) | 157 to 159 and 814 to 822 | 3 and 3 | same |
| SRT group, one member per transit, routed IPv6, no FIPS | none | 0 | 2 (one per mode) | [stage 1](../qualification/g5-srt-group-comparison-2026-11-14.md) |
| SRT group, one member per FIPS overlay | none | 0 | 2 (one per mode) | [stage 2](../qualification/g5-srt-group-over-fips-2026-11-14.md) |

Three things follow from the table and are not in dispute between the runs:

1. **FIPS recovery alone is never hitless.** The gap tracks the FIPS link-dead timer plus
   about 1 to 2 s. No timer can make it zero, because the loss has to be detected first.
2. **An SRT group over independent paths was hitless,** with and without FIPS underneath, in
   Broadcast and in Backup. In stage 2 FIPS reported the lost link after 31 to 32 s; the stream
   had continued on the other member the whole time.
3. **The combination with FIPS needs something FIPS v0.5.3 does not offer.** A FIPS node has
   one identity and one route to a peer. Stage 2 gave each endpoint two identities by running
   two daemons, which works only with a lab routing step: the lab removes the `fd00::/8`
   route FIPS installs and adds its own.

Against [ADR-0012](0012-interruption-budget.md): the hitless target is met only by the group
arrangements. The 6 s single-path floor is met only with link-dead 3 s and a raised SRT
peer-idle timeout, neither of which is a qualified setting.

## 2. The three answers OD-15 allows

**A. Bounded workaround: continuity comes from an SRT group; FIPS recovery is recovery.**
The stream's continuity across a transit failure is the group's job, with one member per
independent path. FIPS reconvergence stays what it is measured to be: it restores a path in
seconds to tens of seconds. This is what the architecture already says ("SRT connection groups
are the first resilience baseline"), now with retained numbers behind it.

**B. Improvement: make FIPS recovery itself meet the budget.** This would mean faster
detection in FIPS (the 3 s profile, or lower) and a way to switch routes without losing
packets. The retained runs put a floor under it: about 4 to 5 s at link-dead 3 s, with an
unmeasured false-reap risk on lossy or slow links. Hitless is out of reach for a detect-then-
switch design. It also depends on changes in a project this repository does not control.

**C. Pivot: stop using FIPS on the continuity path.** Run the group over plain IP paths, as
in stage 1, and use FIPS at most for reachability. Stage 1 shows this works in the lab. It
gives up what FIPS is here for: identity, encryption and reachability without addressable
endpoints.

## 3. Proposed selection

**Select A.** Record in ADR-0014:

1. **Continuity for the loss of one path is provided by an SRT connection group with one
   member per independent path.** A hitless claim is only ever made for a group arrangement.
2. **FIPS reconvergence is not a continuity mechanism.** A single session over FIPS is judged
   against ADR-0012's 6 s floor, not against the hitless target. G6 keeps that budget.
3. **The group over FIPS is demonstrated, not supported.** Until FIPS offers two usable
   identities or two usable paths per host, group-over-FIPS rests on the lab routing step and
   may be described only with that limit.
4. **No FIPS fork and no patch stack.** The missing capability is taken to the FIPS project
   as a request. A fork would need its own ADR and is not proposed.
5. **B is not pursued as the route to continuity.** Shorter FIPS timers remain worth
   qualifying for the single-path floor, as ADR-0012 already says; that is separate work.

Why A and not the others, in terms of the evidence: B cannot reach the target the owner set,
and C discards the reason for the project while A reaches the same result with FIPS in place.

## 4. What A leaves open, and proposed handling

| Open point | Proposed handling |
| --- | --- |
| **The FIPS gap.** Two forms would close it: an option that leaves the `fd00::/8` route to the operator, so two daemons can share a host; or one identity with two disjoint paths to a peer. | Write it up as a capability request and record it under OD-10 (generic capabilities proposed upstream). Opening an issue in the FIPS project is a public step and needs the owner's explicit go-ahead; this proposal does not take it. |
| **Two identities per endpoint.** In stage 2 the lab knew all four addresses. A product must learn and authorise a peer's second identity. | Belongs to OD-07 (device credentials). Note the requirement there; no experiment proposed yet. |
| **Broadcast or Backup.** Both were hitless. Broadcast sent the stream twice throughout. Backup sent it once, plus about 5 s on both members after the fault at SRT's defaults. | Leave the choice to the pilot profile (OD-01). Do not fix it in ADR-0014. |
| **OD-11, independent fault domains.** The lab's two paths are separate transits and links on one host. The architecture requires physical or administrative independence. | Keep OD-11 open. Lab topology shows the mechanism, not real independence. |
| **G5.** Two retained stages, one run per mode each. | Keep G5 `in-progress`. See section 5. |

## 5. What G5 would still need before it could pass

Proposed, for the owner to cut or extend. Each item is its own predeclared experiment.

1. **Repeats** of both stages, so each mode has more than one run.
2. **A member that comes back:** restore the blackholed path and observe the member rejoin,
   with no effect downstream.
3. **Partial and one-way loss on one member,** where the member is degraded but not dead. This
   is where Backup's switching rule is actually exercised.
4. **The higher pilot rate** (10 Mbit/s is proposed in the
   [budget proposal](proposal-pilot-budgets-2026-11-13.md) and not yet run).
5. **Loss of the surviving path's delay advantage:** both stages faulted the faster path.
   Faulting the slower one is the cheaper case and is still unobserved.

Not proposed for G5: endpoint failure. A group does not address it.

## 6. Decisions asked of the owner

1. Select A as in section 3, or B, or C?
2. Go-ahead to draft the FIPS capability request as a document in this repository (OD-10).
   Sending it upstream would be asked separately.
3. Keep OD-11 open as proposed, or treat the lab topology as sufficient?
4. Is the G5 list in section 5 the right scope, and which item comes first?

## Limits of this note

- Every number comes from one topology, one fault class, one stream rate and hosted runners
  of one type. The group rows are one run per mode and stage.
- "Hitless" is ADR-0012's definition: no missing and no changed frame at the downstream
  collector. It is not a statement about a live player.
- The comparison between the group and the single session is between different numbers of
  paths in use. It shows what redundancy buys, at the cost of a second path and, in Broadcast,
  twice the bytes.
- Stage 2 does not show that FIPS supports two daemons per host. It shows the opposite for
  v0.5.3, and what works once the lab steps around it.
- Nothing here is a verdict on FIPS. The retained FIPS behaviour matches its documented
  timers.
