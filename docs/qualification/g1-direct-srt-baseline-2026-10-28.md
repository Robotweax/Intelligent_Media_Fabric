# G1 direct-SRT baseline, third retained run, Telemetry `1b12f8d7` — 2026-10-28

- Workflow: [G1 Direct SRT Baseline, run 40743995008](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40743995008)
- Fabric runner revision: `43757965` (branch `dev/g4-faulted-diamond`)
- SRT v0.3.1 `57fcf51a`, SRT Telemetry `1b12f8d7d75658cb7b7e00a0575fc77d965dbbec`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure`; two isolated namespaces, direct IPv6 veth, MTU 1500, no FIPS
- Contract: [predeclared on 2026-10-22](g1-direct-srt-baseline-plan-2026-10-22.md), unchanged

The workflow passed the complete pinned Telemetry CTest suite (78 tests), ran the three
predeclared repetitions and retained the
[evidence bundle](../../qualification/retained-bundles/2026-10-28-g1-direct-srt-baseline-40743995008/result.json).
The result manifest SHA-256 is
`c27be270ebbd3b25946644e2f2d6338dc0676e679c557ab546e1c78b71632a75`.

All three repetitions delivered 240 messages exactly, with zero loss and zero
retransmissions. The receiver held every message at sample index 13. Ranges are
[min, max] over the repetitions and are recorded, not graded.

| Indicator | Range |
| --- | --- |
| Transfer confirmed after, ms | 1,334–1,335 |
| Max abs coordinator schedule error, ms | 0.073–0.093 |
| Sender / receiver CPU, ms | 20 / 20 |
| Sender peak RSS, KiB | 12,980–13,056 |
| Receiver peak RSS, KiB | 13,264–13,348 |

These indicators fall within the spread of the two earlier runs (see the
[2026-10-25 record](g1-direct-srt-baseline-2026-10-25.md)). This run used a different runner
kernel (`7.0.0` instead of `6.17.0`), so it is not a controlled comparison. The 2026-10-25
bundle is now digest-locked history.

G1 stays `in-progress`. Three retained runs now exist (SRT 0.3.0 and twice at 0.3.1).
Passing G1 is an owner decision over repeated runs once OD-01, OD-04 and OD-14 freeze what
the indicators are judged against.
