# G1 direct-SRT baseline — second retained run, SRT v0.3.1 — 2026-10-25

- Workflow: [G1 Direct SRT Baseline, run 40189973066](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40189973066)
- Fabric runner revision: `eeca6b40` (branch `dev/srt-031-refresh`)
- SRT v0.3.1: `57fcf51a31ec2eecf4189d63c2f998ff1e8daaa1`
- SRT Telemetry: `1a018dfdc89a964b03159aebc155d39bca524384`
- Platform: Linux x86_64, kernel `6.17.0-1022-azure`; two isolated namespaces, direct IPv6 veth, MTU 1500, no FIPS
- Contract: [predeclared on 2026-10-22](g1-direct-srt-baseline-plan-2026-10-22.md), unchanged

The workflow built the pinned sources, passed the complete Telemetry test suite (73 tests at
this revision), then ran three repetitions of the G4 workload directly over the veth and
retained the
[28-file evidence bundle](../../qualification/retained-bundles/2026-10-25-g1-direct-srt-baseline-40189973066/result.json);
the result manifest SHA-256 is
`98b352713b76c99a709067c17066a8b5949e048be81e4c896627e0e11acfd85c`. An identical run on
the branch's first commit ([40189211598](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40189211598))
also passed 3/3 and is cited below for the indicators only; it is not retained.

## Observed, and compared with the 0.3.0 run

Both runs delivered 240 messages exactly in every repetition with zero loss, zero
retransmissions and 261,120 wire bytes each way; the receiver held every message at the
post-transfer sample (index 13); no sampling interval was missed. Ranges are [min, max]
over three repetitions. Nothing here is graded; the budgets are not frozen.

| Indicator | 0.3.0 (run 39806840201) | 0.3.1 (run 40189973066) | 0.3.1 (run 40189211598, not retained) |
| --- | --- | --- | --- |
| Transfer confirmed after, ms | 1,335–1,337 | 1,335–1,338 | 1,331 |
| Max abs coordinator schedule error, ms | 0.085–0.093 | 0.094–0.146 | 0.062–0.066 |
| Sender SRT RTT estimate at settle, ms | 2.086–2.087 | 2.089–2.093 | 2.062–2.065 |
| Sender CPU, ms | 20 | 20–30 | 10 |
| Receiver CPU, ms | 10–20 | 20 | 10 |
| Sender peak RSS, KiB | 12,608–12,724 | 12,988–12,996 | 13,084–13,208 |
| Receiver peak RSS, KiB | 12,936–12,984 | 13,264–13,300 | 13,376–13,464 |

Peak RSS is consistently about 300–500 KiB higher at 0.3.1 on both endpoints across all six
repetitions; CPU values sit at the 10 ms procfs tick resolution and vary as much between the
two 0.3.1 runs as between versions, so they say nothing. The 0.3.1 release notes claim reduced
sparse payload-pool growth and named library workers; this workload (240 messages, ~1.3 s)
is too small to show either, and the RSS delta is recorded, not explained.

The CONNECTED-after-runtime-installation change in 0.3.1 produced no visible difference in
the pre-transfer sample: both versions report zero counters at sample 0.

## What this does and does not establish

Two retained G1 runs now exist on different SRT pins, both exact and loss-free with the same
workload and harness. G1 stays `in-progress`: passing it is an owner decision over repeated
runs once OD-01, OD-04 and OD-14 freeze what the recorded indicators are judged against.
This is not a 0.3.0/0.3.1 performance claim, not a direct/FIPS comparison and not a G3
scorecard.
