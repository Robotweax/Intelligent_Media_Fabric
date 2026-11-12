# G1 direct-SRT baseline, fourth retained run, SRT v0.3.2 — 2026-11-12

- Workflow: [G1 Direct SRT Baseline, run 43244304465](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43244304465)
- Fabric runner revision: `c5052b1e` (branch `dev/srt-032-refresh`, PR #14)
- SRT v0.3.2 `e45d0edd`, SRT Telemetry `7a6b8eff65c686ccafa36a0adace148a8b87d3ca`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure`; two isolated namespaces, direct IPv6 veth, MTU 1500, no FIPS
- Contract: [predeclared on 2026-10-22](g1-direct-srt-baseline-plan-2026-10-22.md), unchanged

[ADR-0010](../decisions/0010-srt-032-refresh.md) moved SRT to v0.3.2 and Telemetry to
`7a6b8eff`. The workflow passed the complete pinned Telemetry CTest suite (81 tests, none
failed, none skipped), ran the three predeclared repetitions and retained the
[evidence bundle](../../qualification/retained-bundles/2026-11-12-g1-direct-srt-baseline-43244304465/result.json).
The result manifest SHA-256 is
`788587d1ef902e6dd75748398fefc0429bbb9eba24a820452cd3575743dc3816`.

All three repetitions delivered 240 messages exactly, with zero loss and zero
retransmissions. The receiver held every message at sample index 13. Ranges are
[min, max] over the repetitions and are recorded, not graded. The 2026-10-28 column is the
[previous run](g1-direct-srt-baseline-2026-10-28.md) at SRT v0.3.1 and Telemetry `1b12f8d7`,
on the same runner kernel.

| Indicator | 2026-11-12 (0.3.2) | 2026-10-28 (0.3.1) |
| --- | --- | --- |
| Transfer confirmed after, ms | 1,333–1,335 | 1,334–1,335 |
| Max abs coordinator schedule error, ms | 0.085–0.114 | 0.073–0.093 |
| Sender CPU, ms | 20 | 20 |
| Receiver CPU, ms | 10–20 | 20 |
| Sender peak RSS, KiB | 12,912–12,968 | 12,980–13,056 |
| Receiver peak RSS, KiB | 13,196–13,324 | 13,264–13,348 |
| Sender RTT maximum, s | 0.1 | 0.1 |

CPU is counted in 10 ms ticks, so 10 against 20 ms is one tick. Peak RSS is about 70 KiB
lower on the sender and 20 to 70 KiB lower on the receiver. These are three repetitions on
one hosted runner each, without a frozen budget; no difference here is attributed to the
SRT or Telemetry change. The 2026-10-28 bundle is now digest-locked history.

G1 stays `in-progress`. Four retained runs now exist (SRT 0.3.0, twice at 0.3.1, and
0.3.2). Passing G1 is an owner decision over repeated runs once OD-01, OD-04 and OD-14
freeze what the indicators are judged against.
