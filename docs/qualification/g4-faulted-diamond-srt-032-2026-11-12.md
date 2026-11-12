# G4 faulted diamond at SRT v0.3.2, both timer profiles — 2026-11-12

- Workflow: [G4 Faulted Diamond, run 43244304348](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43244304348), two matrix jobs on separate runners
- Fabric runner revision: `c5052b1e` (branch `dev/srt-032-refresh`, PR #14)
- Pins: SRT v0.3.2 `e45d0edd`, SRT Telemetry `7a6b8eff`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`
- Platform: Linux x86_64; kernel `7.0.0-1017-azure` (`g2-alternate-route`) and `7.0.0-1014-aws` (`fast-detection`)
- Contract: the [frozen profile and its fast-detection variant](g4-faulted-diamond-experiment-plan-2026-09-23.md), unchanged; only the pins moved ([ADR-0010](../decisions/0010-srt-032-refresh.md))

Both jobs were first attempts. Both passed the pinned Telemetry suite (81 tests, none
failed, none skipped) and every stop rule, and retained validated 16-file bundles:

| Profile | Bundle | Result SHA-256 |
| --- | --- | --- |
| `g2-alternate-route` (heartbeat 10 s, link-dead 30 s) | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-g2-alternate-route-43244304348/result.json) | `574e7f6ab94fe6a1564c039029f68399f2ad4677aee490ee10c336076464fef7` |
| `fast-detection` (heartbeat 1 s, link-dead 3 s) | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-fast-detection-43244304348/result.json) | `f680d61bf1ed382dcf362b5863c3340c030ee491847320881ba59cd270260d58` |

## Side by side with the 0.3.1 runs

Times are milliseconds from SIGKILL-sent, at each layer's sampling resolution (collector
per datagram, SRT 500 ms, FIPS about 1 s). The 0.3.1 columns are the
[2026-10-30 run 41022516133](g4-faulted-diamond-fast-detection-2026-10-30.md) at SRT v0.3.1
and Telemetry `1b12f8d7`.

| Observation | `g2-alternate-route` 0.3.2 | `g2-alternate-route` 0.3.1 | `fast-detection` 0.3.2 | `fast-detection` 0.3.1 |
| --- | --- | --- | --- | --- |
| Killed / alternate transit | `r2` / `r1` | `r2` / `r1` | `r2` / `r1` | `r2` / `r1` |
| Downstream media stops | 133 | 145 | 134 | 140 |
| SRT receiver stall | 490–990 | 494–994 | 495–995 | 494–994 |
| SRT sender loss or drop | 990–1,490 | 994–1,494 | 995–1,495 | 994–1,494 |
| FIPS link loss and reparent | 30,991–31,491 | 30,994–31,494 | 3,995–4,495 | 3,994–4,494 |
| SRT receiver resumes | 31,990–32,490 | 30,994–31,494 | 3,995–4,495 | 4,994–5,494 |
| Downstream media resumes | 32,339 | 31,333 | 4,363 | 5,321 |
| Downstream gap | 32,206 | 31,188 | 4,229 | 5,181 |
| Datagrams delivered / sent | 14,259 / 17,729 | 14,371 / 17,729 | 17,359 / 17,729 | 17,253 / 17,729 |
| Frames missing (one contiguous run) | 783 (499–1281) | 757 (500–1256) | 84 (499–582) | 108 (499–606) |
| Frames changed | 18 (1282–1299) | 19 (499, 1257–1274) | 17 (583–599) | 18 (607–624) |
| Re-timed / unexpected frames | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| SRT session survived | yes | yes | yes | yes |
| FIPS observations / SRT samples per endpoint | 195 / 327 | 196 / 328 | 169 / 328 | 169 / 328 |

## What this shows

The behaviour at SRT v0.3.2 and Telemetry `7a6b8eff` is the behaviour retained at the old
pins. FIPS reported link loss and reparent in the same 500 ms windows as before (about
31 s and about 4 s after the kill), one SRT session spanned both route epochs, the outage
was one contiguous run of missing frames followed by P-frames decoded without their
reference up to the next I-frame (1300 and 600), and every other frame matched the
fixture's own decode bit-for-bit.

The downstream gap differs by about 1 s from the 2026-10-30 run in both profiles, in
opposite directions: 1.0 s longer with `g2-alternate-route`, 1.0 s shorter with
`fast-detection`. That is the spread already present at one revision: the three 0.3.1 runs
of the 30 s profile gave 32.2 s, 31.2 s and 31.2 s
([first](g4-faulted-diamond-2026-10-28.md), [repeat](g4-faulted-diamond-repeat-2026-10-28.md),
2026-10-30 baseline). In all six retained runs media resumed inside the FIPS reparent
window or at most about 0.85 s after it closed. No difference here is attributed to the
SRT 0.3.2 TSBPD change or to the Telemetry delta-engine refactor, and nothing here shows
that either had no effect: one run per profile cannot separate them from that spread.

Limits:
- One run per profile, one fault type, one local clock domain. The result is ordering-only:
  no causal claim, no first divergent layer, no fault domain, nothing hitless.
- The two jobs ran on runners with different kernels.
- The 60 s SRT peer-idle timeout is still the experiment setting. The 4.2 s gap with fast
  detection is below SRT's 5 s default where the 0.3.1 run was just above it; whether a
  default-profile session survives is still untested, and the two runs straddle that default.
- 3 s is not a recommended FIPS setting; see the limits in the 2026-10-30 record.
- G4 stays `in-progress`.
