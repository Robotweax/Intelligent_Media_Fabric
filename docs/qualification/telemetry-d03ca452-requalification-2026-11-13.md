# Requalification at SRT Telemetry `d03ca452` — 2026-11-13

- Decision: [ADR-0013](../decisions/0013-telemetry-group-mode-pin.md) moved SRT Telemetry from `7a6b8eff` to `d03ca452` (incident-peer group mode and its test fix). SRT v0.3.2 `e45d0edd` and FIPS v0.5.3 `f4a5b4a8` are unchanged.
- Fabric runner revision: `859160d4` (branch `dev/telemetry-group-mode-pin`, PR #22)
- Runs, all first attempts, no job rerun:
  [G1 43402399643](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43402399643),
  [healthy pilot 43402398402](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43402398402) (dispatched on the branch) and
  [faulted diamond 43402399663](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43402399663) (eight matrix jobs on separate runners)
- Platform: Linux x86_64, kernel `7.0.0-1017-azure` in nine jobs and `7.0.0-1014-aws` in the `fast-detection`, `extended`, `transit-blackhole` job
- Contracts: unchanged. No experiment here uses the group mode.

All ten jobs passed the pinned Telemetry CTest suite: 82 tests, none failed, none skipped. The
suite has one test more than at `7a6b8eff`, the incident-peer group test; it passed in every
job. All ten bundles validate and are retained. Earlier runs at the first candidate
`21dc05b9` are described in ADR-0013 and are not retained.

The numbers below stand beside the results at `7a6b8eff`. They are recorded, not graded.

## G1 direct-SRT baseline

[Bundle](../../qualification/retained-bundles/2026-11-13-g1-direct-srt-baseline-43402399643/result.json),
result SHA-256 `71f456e180b947a2b598ffb376e1664819ed002940cf70abd346af1b983f47ce`.
Three repetitions, each 240 messages delivered exactly, zero loss and zero retransmissions;
the receiver held every message at sample index 13. Ranges are [min, max] over the
repetitions. The comparison column is the
[2026-11-12 run](g1-direct-srt-baseline-2026-11-12.md) on the same runner kernel.

| Indicator | `d03ca452` | `7a6b8eff` |
| --- | --- | --- |
| Transfer confirmed after, ms | 1,331 | 1,333–1,335 |
| Max abs coordinator schedule error, ms | 0.069–0.078 | 0.085–0.114 |
| Sender CPU, ms | 10 | 20 |
| Receiver CPU, ms | 0–10 | 10–20 |
| Sender peak RSS, KiB | 13,084–13,188 | 12,912–12,968 |
| Receiver peak RSS, KiB | 13,356–13,416 | 13,196–13,324 |
| Sender RTT maximum, s | 0.1 | 0.1 |

CPU is counted in 10 ms ticks. Peak RSS of the incident peer is about 120 to 280 KiB higher
on the sender and 30 to 220 KiB higher on the receiver. The peer binary grew by the group
mode, which would fit, but this is one run of three repetitions per pin and no budget is
frozen; the difference is not attributed. This is the fifth retained G1 run. G1 stays
`in-progress`.

## Healthy SRT over FIPS pilot

[13-file bundle](../../qualification/retained-bundles/2026-11-13-g4-srt-over-fips-live-43402398402/result.json),
result SHA-256 `b94d1944878404ac9758defecfde67de44f6588c938cd20090489e2da06ace28`.
All 240 messages of 1024 bytes delivered exactly; 14 SRT samples per endpoint and 14 FIPS
observations; `srt-before-peer` ordering for SRT/FIPS and SRT/media; complete cleanup. This
is the same outcome as the [2026-11-12 run](g4-live-capture-srt-032-2026-11-12.md). It records
`G3: not-passed` and `G4: not-passed`; the limits of that record apply unchanged.

## Faulted diamond, eight combinations

| FIPS timers | SRT peer idle | Reconnect | Fault | Bundle | Result SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `fast-detection` | `extended` | `none` | `transit-blackhole` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-extended-none-transit-blackhole-43402399663/result.json) | `5cd19dde032744c1e641ad4749e8ccd94164b6bdb836ec27a7f15397072f9e50` |
| `fast-detection` | `extended` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-extended-none-transit-sigkill-43402399663/result.json) | `3b1d6bea16cf44ccf17f51b37df08eae956fdbd04e5bdd6018ff8d14a8c453f0` |
| `g2-alternate-route` | `extended` | `none` | `transit-blackhole` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-extended-none-transit-blackhole-43402399663/result.json) | `b797a5c7a37349ddc0b92a4bc67b8e43a5173af30c28e9ddaffa864b94ccd13e` |
| `g2-alternate-route` | `extended` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-extended-none-transit-sigkill-43402399663/result.json) | `ff1e5dcf6d2b4da5df809910e1ebedc2115b3fbc15e4b4954d2d03eb5e453f04` |
| `fast-detection` | `default` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-default-none-transit-sigkill-43402399663/result.json) | `a7bb6d53ca10b8092d37b9ea932448b278bf1246aea25ad55cb168d4a73061e6` |
| `fast-detection` | `default` | `coordinator-restart` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-default-coordinator-restart-transit-sigkill-43402399663/result.json) | `0a73eb6e20e1465e363fec80c1edc4e64313c293204271863951a76f129816d0` |
| `g2-alternate-route` | `default` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-default-none-transit-sigkill-43402399663/result.json) | `aefdfc179385acbe2fbb62e4a6a7f7b20e6015bccbbe346ded42741e804deed3` |
| `g2-alternate-route` | `default` | `coordinator-restart` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-default-coordinator-restart-transit-sigkill-43402399663/result.json) | `a15d31c50aa19f5454b3874333d38457c7a76786230197894065ee408bd3463b` |

Times are milliseconds from the fault, at each layer's sampling resolution (collector per
datagram, SRT 500 ms, FIPS about 1 s). Each column is one job on its own runner. In every job
the faulted transit was `r2` and the alternate `r1`, ordering was resolved, and no frame was
re-timed or unexpected.

Sessions kept alive by the 60 s `extended` peer-idle timeout, no reconnect:

| Observation | 3 s, blackhole | 3 s, kill | 30 s, blackhole | 30 s, kill |
| --- | --- | --- | --- | --- |
| Fault complete (fourth `tc` returned / exit observed) | 7 | 32 | 11 | 15 |
| Downstream media stops | 141 | 132 | 140 | 140 |
| SRT receiver stall | 495–995 | 494–994 | 492–992 | 494–994 |
| SRT sender loss or drop | 995–1,495 | 994–1,494 | 992–1,492 | 994–1,494 |
| FIPS link loss and reparent | 3,995–4,495 | 3,994–4,494 | 30,993–31,493 | 30,994–31,494 |
| SRT receiver resumes | 4,995–5,495 | 4,994–5,494 | 31,992–32,492 | 31,994–32,494 |
| Downstream media resumes | 5,292 | 5,348 | 32,346 | 32,337 |
| **Downstream gap** | **5,151** | **5,216** | **32,206** | **32,197** |
| Downstream gap at `7a6b8eff` ([run 43381166414](g4-faulted-diamond-blackhole-2026-11-13.md)) | 5,181 | 5,044 | 32,198 | 32,196 |
| SRT session survived | yes | yes | yes | yes |
| Datagrams delivered / sent | 17,257 / 17,729 | 17,250 / 17,729 | 14,259 / 17,729 | 14,260 / 17,729 |
| Frames missing (one contiguous run) | 106 | 108 | 783 | 783 |
| Frames changed | 20 | 18 | 18 | 18 |

SRT's default 5 s peer-idle timeout:

| FIPS link-dead | Reconnect | Session survived | Downstream gap | At `7a6b8eff` | Caller attempts | Detection delay | Frames missing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3 s | `none` | no | not ended, 499 of 4,000 frames | same | — | — | 3,501 |
| 3 s | `coordinator-restart` | no | 6,261 | 6,252 | 1 | 978 | 157 |
| 30 s | `none` | no | not ended, 499 of 4,000 frames | same | — | — | 3,501 |
| 30 s | `coordinator-restart` | no | 32,530 | 32,894 | 2 (first failed) | 985 | 814 |

## What this shows

Every combination behaves at `d03ca452` as it did at `7a6b8eff`. The FIPS and SRT
observation windows are the same, the sessions survive or end in the same combinations, and
the downstream gaps differ by 1 to 364 ms between the pins. That is inside the spread already
recorded between runs at one revision. Nothing is attributed to the pin change.

The six retained runs of the surviving `fast-detection` kill combination now read 5,321,
4,363, 4,351, 5,414, 5,184 and 5,216 ms.

Limits:
- One run per combination, one local clock domain. Ordering-only: no causal claim, no first
  divergent layer, no fault domain, nothing hitless.
- These runs show that the experiments which do not use the group mode still behave as
  before. They say nothing about the group mode itself beyond its own test passing ten times.
- Ten passes of the group test do not demonstrate that the port race fixed in
  Robotweax/srt_telemetry#76 is gone; it had failed once in ten jobs at `21dc05b9`.
- 3 s is not a recommended FIPS setting (OD-01, OD-15).
- The bundles at Telemetry `7a6b8eff` are digest-locked history for that revision. No gate
  status changes: G1 and G4 stay `in-progress`.
