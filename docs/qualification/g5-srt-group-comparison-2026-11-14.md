# G5 SRT-group comparison, stage 1, first retained run — 2026-11-14

- Workflow: [G5 SRT Group, run 43567524615](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43567524615), two matrix jobs on separate runners, both first attempts, neither rerun
- Fabric runner revision: `79d825e9` (branch `dev/g5-srt-group-comparison`, PR #23)
- Pins: SRT v0.3.2 `e45d0edd`, SRT Telemetry `d03ca452`, FFmpeg `6.1.1-3ubuntu5`. No FIPS.
- Platform: Linux x86_64, kernel `7.0.0-1017-azure` in both jobs
- Contract: [stage 1 plan](g5-srt-group-comparison-plan-2026-11-13.md), predeclared on 2026-11-13 before any run and unchanged since the corrections it discloses

Both jobs passed the pinned Telemetry suite (82 tests, none failed, none skipped) and all six
stop rules, and retained validated 22-file bundles.

| Group mode | Bundle | Result SHA-256 |
| --- | --- | --- |
| `broadcast` | [bundle](../../qualification/retained-bundles/2026-11-14-g5-srt-group-broadcast-43567524615/result.json) | `a78d5edac1c6638bd053e1815ca857371534cc4dd760459bb292fb5180a1c01b` |
| `backup` | [bundle](../../qualification/retained-bundles/2026-11-14-g5-srt-group-backup-43567524615/result.json) | `151f269b383e883541137656ea8927aef56043b76496485d14082de6eaecbb63` |

## Result

Times are milliseconds from `blackhole-start`, at each layer's resolution (collector per
datagram, group and member samples every 500 ms). Each column is one job on its own runner.
Member 0 runs over `r1`, the blackholed transit; member 1 over `r2`.

| Observation | Broadcast | Backup |
| --- | --- | --- |
| Blackhole applied (fourth `tc` returned) | 10 | 9 |
| Members before the fault (0 / 1) | running / running | running / idle |
| Listener's member 0 receives nothing more | 500–1,000 | 500–1,000 |
| Member 1 first carries media | from the start | 0–500 |
| Member 0 no longer usable, caller | 4,500–5,000 | 5,000–5,500 |
| Member 0 no longer usable, listener | 5,000–5,500 | 5,000–5,500 |
| Group connected to the end, both endpoints | yes | yes |
| Downstream gaps above 250 ms | none | none |
| Longest interval between collected datagrams over the whole run | 9.9 | 9.8 |
| Datagrams delivered / sent | 17,729 / 17,729 | 17,729 / 17,729 |
| Frames missing / changed / unexpected, of 4,000 | 0 / 0 / 0 | 0 / 0 / 0 |
| **Hitless by ADR-0012's definition** | **yes** | **yes** |

The source paces one datagram every 9.024 ms, so the longest collector interval in both jobs
is one pacing interval.

Wire cost, from each caller member's own SRT counters:

| | Broadcast | Backup |
| --- | --- | --- |
| Member 0 packets sent (until it was removed) | 2,710 | 2,765 |
| Member 1 packets sent | 17,729 | 15,518 |
| Sum / stream packets | 20,439 / 17,729 | 18,283 / 17,729 |
| Packets sent on both members | 2,710 | 554 |
| Retransmitted packets, group counter | 0 | 0 |

Packets dropped by the four blackhole qdiscs when the fixture ended: 1,553 in each job
(`a` toward `r1` 997 and 996, `b` toward `r1` 555 and 557, `r1`'s own two ends together 1 and 0).

## Beside the single-session results over FIPS

The same stream, fault timing and downstream measurement; the single-session columns are the
retained blackhole runs at the same pins
([record](telemetry-d03ca452-requalification-2026-11-13.md)). Ungraded.

| | Group, Broadcast | Group, Backup | One session over FIPS, link-dead 3 s | One session over FIPS, link-dead 30 s |
| --- | --- | --- | --- | --- |
| Underlay | routed IPv6, no FIPS | routed IPv6, no FIPS | FIPS v0.5.3 | FIPS v0.5.3 |
| Downstream gap, ms | none | none | 5,151 | 32,206 |
| Frames missing | 0 | 0 | 106 | 783 |
| Frames changed | 0 | 0 | 20 | 18 |
| Session or group kept | yes | yes | yes (peer idle 60 s) | yes (peer idle 60 s) |

## What this shows

With two members on separate transits, the silent loss of the transit carrying the stream
left no trace downstream in either mode: every datagram arrived, every frame matched, and
the collector saw no interval longer than one pacing step. These are the first retained runs
that meet ADR-0012's hitless target for one transit failure.

In Backup, the standby member was running in the first 500 ms sample after the fault and
both members stayed running until member 0 was removed about 5 s later. 554 packets were
sent on both members, about 5 s of the stream. Until the dead member is removed, Backup at
SRT's defaults therefore costs what Broadcast costs. The retained samples show the states and
counters; why SRT kept the dead member that long is not examined here, though it coincides
with the 5 s default peer-idle timeout.

Broadcast sent the stream twice for the 20 s before the fault and until member 0 was
removed, 2,710 packets on both members, then once.

The prediction in the plan held for Broadcast and, for Backup, on its better side: no gap.

Limits:
- **This is not a FIPS result.** The groups ran on plain routed IPv6 with a 1500-byte link
  MTU. Nothing here shows a group working over FIPS, over two FIPS routes, or within the
  `fips0` packet budget. That is stage 2, which is neither designed in detail nor
  predeclared.
- The comparison table sets two different underlays side by side. It shows what the group
  mechanism does when each member has an independent path. It does not show that FIPS could
  provide two such paths.
- One run per mode, one host, one clock, one kernel. The two paths are independent for this
  fault only.
- One fault class: a full, two-way blackhole of one transit. Partial loss, one-way loss, a
  slow member and the loss of an endpoint are not tested. Nothing was restored, so a member
  rejoining is not tested either.
- Ordering-only: no causal claim.
- Each result records `G5: not-passed`. With retained runs G5 moves from `not-started` to
  `in-progress`, as the plan states. Passing G5 and closing OD-15 or OD-11 are owner
  decisions; whether stage 1 alone may close OD-15 is still open.
