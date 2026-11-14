# G5 SRT-group comparison, stage 2: group over two FIPS overlays, first retained run — 2026-11-14

- Workflow: [G5 SRT Group over FIPS, run 43574559867](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43574559867), two matrix jobs on separate runners, both first attempts, neither rerun
- Fabric runner revision: `915c8a55` (branch `dev/g5-srt-group-over-fips`, PR #24)
- Pins: SRT v0.3.2 `e45d0edd`, SRT Telemetry `d03ca452`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`. All binaries unmodified.
- Platform: Linux x86_64, kernel `7.0.0-1017-azure` in both jobs
- Contract: [stage 2 plan](g5-srt-group-over-fips-plan-2026-11-14.md), predeclared on 2026-11-14 before any run

Both jobs passed the pinned Telemetry suite (82 tests, none failed, none skipped) and every
stop rule, and retained validated 23-file bundles.

| Group mode | Bundle | Result SHA-256 |
| --- | --- | --- |
| `broadcast` | [bundle](../../qualification/retained-bundles/2026-11-14-g5-srt-group-fips-broadcast-43574559867/result.json) | `708575a28f8698ea6d4c530423485fbd408457723ed96a5a77ba8385c1309cbc` |
| `backup` | [bundle](../../qualification/retained-bundles/2026-11-14-g5-srt-group-fips-backup-43574559867/result.json) | `986b356ea03d98b98ef5165910dacd7d092fb4d1e13e6078d1027d36c62b7500` |

## Setup as run

Six FIPS daemons formed two separate overlays on the diamond: overlay 1 through `r1`, overlay 2
through `r2`. Each endpoint ran two daemons with separate identities and TUN devices. The lab
removed the `fd00::/8` route each endpoint daemon installed and routed each remote overlay
address to the matching TUN. Before the stream started, each overlay was the three intended
nodes, an address of one overlay did not reach the other, `a` did not reach `b` over the
underlay, and all four endpoint daemons reported an effective IPv6 MTU of 1203, which leaves
1139 bytes for the 1128-byte media datagram.

## Result

Times are milliseconds from `blackhole-start`, at each layer's resolution (collector per
datagram, group and member samples every 500 ms, FIPS control state about every 1 s). Each
column is one job on its own runner. Member 0 runs over overlay 1, the blackholed one.

| Observation | Broadcast | Backup |
| --- | --- | --- |
| Blackhole applied (fourth `tc` returned) | 12 | 10 |
| Members before the fault (0 / 1) | running / running | running / idle |
| Listener's member 0 receives nothing more | 500–1,000 | 499–999 |
| Member 1 first carries media | from the start | in the first sample after the fault (by 499) |
| Member 0 no longer usable, caller | 4,500–5,000 | 4,499–4,999 |
| Member 0 no longer usable, listener | 5,000–5,500 | 4,999–5,499 |
| FIPS reports overlay 1's link lost, on `a` and on `b` | 31,000–32,000 | 31,000–32,000 |
| Overlay 2 intact in every FIPS observation | yes (163) | yes (162) |
| Group connected to the end, both endpoints | yes | yes |
| Downstream gaps above 250 ms | none | none |
| Longest interval between collected datagrams over the whole run | 9.7 | 9.3 |
| Datagrams delivered / sent | 17,729 / 17,729 | 17,729 / 17,729 |
| Frames missing / changed / unexpected, of 4,000 | 0 / 0 / 0 | 0 / 0 / 0 |
| **Hitless by ADR-0012's definition** | **yes** | **yes** |

The source paces one datagram every 9.024 ms, so the longest collector interval is one pacing
interval in both jobs.

Wire cost, from each caller member's own SRT counters:

| | Broadcast | Backup |
| --- | --- | --- |
| Member 0 packets sent (until it was removed) | 2,764 | 2,764 |
| Member 1 packets sent | 17,729 | 15,519 |
| Sum / stream packets | 20,493 / 17,729 | 18,283 / 17,729 |
| Packets sent on both members | 2,764 | 554 |

These are SRT packets. The FIPS bytes around them are not counted here.

Packets dropped by the four blackhole qdiscs when the fixture ended: 1,762 in Broadcast and
1,815 in Backup (`a` toward `r1` 1,045 and 1,059, `b` toward `r1` 621 and 653, `r1` toward
`a` 63 and 65, `r1` toward `b` 33 and 38).

## The three cases side by side

The same diamond, stream, fault timing and downstream measurement, all at the same pins.
Ungraded.

| | Group over two FIPS overlays (this run) | Group on routed IPv6, no FIPS ([stage 1](g5-srt-group-comparison-2026-11-14.md)) | One session over FIPS, link-dead 3 s | One session over FIPS, link-dead 30 s |
| --- | --- | --- | --- | --- |
| Downstream gap, ms | none in both modes | none in both modes | 5,151 | 32,206 |
| Frames missing | 0 | 0 | 106 | 783 |
| Frames changed | 0 | 0 | 20 | 18 |
| FIPS link-dead timer | 30 s | — | 3 s | 30 s |
| Packets on both members, Broadcast / Backup | 2,764 / 554 | 2,710 / 554 | — | — |

The single-session columns are the blackhole runs in the
[requalification record](telemetry-d03ca452-requalification-2026-11-13.md).

## What this shows

An SRT group with one member per FIPS overlay was hitless in both modes when one overlay's
transit was silently blackholed. Every datagram arrived, every frame matched, and the
collector saw no interval longer than one pacing step. This is the first retained run in
which a stream over FIPS meets ADR-0012's target for one transit failure.

The group behaved over FIPS as it did on plain IPv6 in stage 1: the same member states, the
dead member removed after about 5 s, and in Backup the same 554 packets sent on both members
until then.

FIPS reported the lost link 31 to 32 s after the fault, as its 30 s link-dead timer implies.
The stream had continued on the other member for the whole of that time. In this arrangement
the FIPS detection time did not decide continuity; with one session it was the gap.

The other overlay was intact in every FIPS observation, so the blackhole stayed inside one
overlay.

The contract's prediction held in both modes.

## Also run, not retained

The PR touched a stage 1 source file, so the stage 1 workflow ran again
([run 43574559719](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43574559719)).
Both jobs passed and were hitless, and their bundles validate. They repeat a retained
combination at a revision that changed no stage 1 behaviour and are not retained.

## Limits

- **The endpoint routing is a lab workaround.** FIPS v0.5.3 does not support two daemons in
  one namespace; the second daemon's TUN fails because both install `fd00::/8`. The lab
  removed that route and added host routes. This result shows what the combination does once
  two identities per host work. It does not show that FIPS supports it, and no FIPS change is
  proposed here.
- **Two identities per endpoint.** How an application learns and authorises a peer's second
  identity is not addressed. Here the lab knew all four addresses.
- **Each overlay has exactly one route.** FIPS reconvergence is not exercised. Whether one
  FIPS identity with two usable paths could do the same is a different question.
- **One run per mode,** one host, one kernel, one clock. Four of the six daemons share two
  namespaces. The overlays are separate fault domains for this fault only.
- One fault class: a full, two-way blackhole of one transit. Partial loss, one-way loss, a
  slow member, a killed daemon and the loss of an endpoint are not tested. Nothing was
  restored, so a member rejoining is not tested.
- Ordering-only: no causal claim.
- Each result records `G5: not-passed`. G5 stays `in-progress`. Passing G5 and closing OD-15
  or OD-11 are owner decisions.
