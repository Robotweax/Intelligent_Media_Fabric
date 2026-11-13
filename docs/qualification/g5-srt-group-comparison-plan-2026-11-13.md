# G5 SRT-group comparison, stage 1 — predeclared experiment contract

Status: predeclared on 2026-11-13, before any run. No retained run yet.

Implements stage 1 of the [design draft](srt-group-comparison-design-2026-11-13.md) for OD-15
and OD-11. [ADR-0012](../decisions/0012-interruption-budget.md) sets a hitless target for the
loss of one transit; no single SRT session over FIPS met it. This experiment measures what an
SRT connection group gives on the same diamond, with the same stream, fault and downstream
measurement, when each member has its own transit.

## Question

When one of two group members loses its path completely and silently, what does the
independent downstream collector see: which frames are missing or changed, and how long is
any gap?

## Fixed setup

| Element | Value |
| --- | --- |
| Pins | Robotweax SRT v0.3.2 `e45d0edd`, SRT Telemetry `21dc05b9` ([ADR-0013](../decisions/0013-telemetry-group-mode-pin.md)), FFmpeg `6.1.1-3ubuntu5`. No FIPS. |
| Topology | Four Linux namespaces `a`, `r1`, `r2`, `b` and the diamond's four veth links, link MTU 1500. No FIPS daemon runs. `r1` and `r2` forward IPv6 in the kernel. |
| Addresses | One IPv6 /64 per link. Static routes on `a` and `b` send each far-side link prefix through the transit on that side, so `a`–`r1`–`b` and `a`–`r2`–`b` are separate paths with no route between them. |
| Path stimulus | 20 ms one-way delay on both ends of `r2`–`b`, as in the faulted diamond. The `r1` path is the faster one. |
| SRT | One group from `a` (caller) to `b` (listener), live mode, message API. Member 0 runs over `r1` with weight 20, member 1 over `r2` with weight 10. SRT's defaults otherwise: peer idle 5 s, group stability timeout unset. The listener binds the wildcard address. |
| Group mode | `broadcast` or `backup`, one per job. In Backup, the higher weight makes the `r1` member the active one. |
| Stream | The faulted diamond's fixture, unchanged: 160 s MPEG-TS, 4000 frames, 1128-byte datagrams, 1 Mbit/s, paced by the independent source into the caller's UDP input; the listener's UDP output feeds the independent collector; decode and frame comparison as in the faulted diamond. |
| Fault | `transit-blackhole` of `r1`, 20 s after the source starts: `netem loss 100%` on the four veth ends of `r1`'s two links, `r1`'s own first. Nothing is restored. In both modes this removes the path that carries the stream first. |
| Sampling | Every 500 ms on one coordinator clock: one group sample per endpoint, with each member's state and its own SRT sample. |

## Stop rules

A run fails when one of these does not hold:
1. Both members connect, and member `i` on the caller is member `i` on the listener by address.
2. Before the fault, media reaches the collector; in Broadcast both members carry it, in
   Backup member 0 carries it and member 1 is idle.
3. All four blackholed interfaces are up after the fault, and their qdiscs together report at
   least one dropped packet when the fixture ends.
4. Within 2 s of the fault the listener's member 0 receives nothing more.
5. The group stays connected to the end of the fixture on both endpoints.
6. No complete sampling interval is missed; teardown is complete.

A gap, missing frames or changed frames do not fail a run. They are the result.

## What is recorded and reported

No threshold is attached except ADR-0012's definition, which is applied and reported, not
enforced: a run is **hitless** when no frame is missing and no frame is changed.

- Frame comparison: missing, changed, unexpected and re-timed frames.
- Every downstream gap above the collector's 250 ms threshold after the fault, and the longest.
- For member 0 on each endpoint: the sample interval in which it stopped being usable
  (state no longer running or idle, or removed).
- In Backup: the sample interval in which member 1 first carried media.
- Per member: unique and total wire bytes sent, so the cost of Broadcast is visible.
- The blackhole's application spread and drop counters.

The comparison is with the retained single-session blackhole and kill results over FIPS
([blackhole](g4-faulted-diamond-blackhole-2026-11-13.md)), side by side, ungraded.

## Bundle

`result.json` and 21 files: `fault-events.jsonl`, `group-members.json`, `group-samples.jsonl`,
for each endpoint and member the Telemetry recording, adapter context and byte-replayable
observations (12 files), `media-source.json`, `media-collector.json`, `media-relay.json`,
`reference.framehash`, `observed.framehash` and `frame-assessment.json`. The validator
recomputes the frame assessment and the timeline from these files and replays the adapter.

## Known before the run, and not compensated

- **This is not a FIPS experiment.** It measures SRT groups on plain routed IPv6. It gives
  the baseline the architecture asks for; it does not show a group working over FIPS. That
  is stage 2.
- **Path MTU differs.** The links carry 1500 bytes where `fips0` carries 1203. The media
  datagram is the same 1128 bytes, so SRT packets are the same size, but nothing here
  exercises the FIPS packet budget.
- **Independence is topological.** Two veth paths on one host share a kernel, a clock and a
  CPU. Separate transits and links are separate fault domains for this fault only.
- **Broadcast doubles the wire bytes** before the fault. A hitless Broadcast result is a
  result at that cost.
- **Prediction, not a requirement:** Broadcast is expected to be hitless. For Backup the
  switch time is not known for the pinned SRT; a short gap or none is expected, since a
  loopback check of the incident peer showed the standby carrying media within one 500 ms
  sample. That check used a different fault mechanism and is not evidence.
- The endpoints are single points of failure and are not faulted. One fault class, full and
  two-way; partial or one-way loss on a member is a different experiment.

## Gate effect

A passing run records `G5: not-passed`. Retained runs make G5 `in-progress`. Passing G5 and
closing OD-15 are owner decisions; whether stage 1 alone may close OD-15 is still open.
