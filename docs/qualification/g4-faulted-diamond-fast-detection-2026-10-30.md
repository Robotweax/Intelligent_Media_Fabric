# G4 faulted diamond, fast FIPS detection variant — 2026-10-30

- Workflow: [G4 Faulted Diamond, run 41022516133](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/41022516133), two matrix jobs on separate runners
- Fabric runner revision: `8eb133a` (branch `dev/g4-faulted-diamond-fast-detection`, PR #13)
- Pins: SRT v0.3.1 `57fcf51a`, SRT Telemetry `1b12f8d7`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure` (both jobs)
- Contract: the [fast-detection variant](g4-faulted-diamond-experiment-plan-2026-09-23.md#variant-fast-fips-detection-predeclared-2026-10-30), predeclared before this run; one change against the frozen profile

Both jobs passed the pinned Telemetry suite and every stop rule, and retained validated
16-file bundles:

| Profile | Bundle | Result SHA-256 |
| --- | --- | --- |
| `fast-detection` (heartbeat 1 s, link-dead 3 s) | [bundle](../../qualification/retained-bundles/2026-10-30-g4-faulted-diamond-fast-detection-41022516133/result.json) | `80474d3cc8456e8a0a8572b2b9227da4c944d7310ec10b30877c18f1b5ab7c13` |
| `g2-alternate-route` (heartbeat 10 s, link-dead 30 s) | [bundle](../../qualification/retained-bundles/2026-10-30-g4-faulted-diamond-g2-alternate-route-41022516133/result.json) | `e51fbf6733cb27b618436a319e41f710e6da6b6f62c23f4ea30f0c352d3bcb43` |

No FIPS observation before the kill showed `b` on another parent; that check is new in this
revision and applies to both profiles.

## Side by side

Times are milliseconds from SIGKILL-sent, at each layer's sampling resolution. The
baseline column is the same-revision run. The two earlier retained baseline runs fall in
the same windows ([first](g4-faulted-diamond-2026-10-28.md),
[repeat](g4-faulted-diamond-repeat-2026-10-28.md)).

| Observation | `fast-detection` | `g2-alternate-route` |
| --- | --- | --- |
| Killed / alternate transit | `r2` / `r1` | `r2` / `r1` |
| Downstream media stops | 140 | 145 |
| SRT receiver stall | 494–994 | 494–994 |
| SRT sender loss or drop | 994–1494 | 994–1494 |
| FIPS link loss and reparent | 3,994–4,494 | 30,994–31,494 |
| SRT receiver resumes | 4,994–5,494 | 30,994–31,494 |
| Downstream media resumes | 5,321 | 31,333 |
| Downstream gap | 5,181 | 31,188 |
| Datagrams delivered / sent | 17,253 / 17,729 | 14,371 / 17,729 |
| Frames missing (one contiguous run) | 108 (499–606) | 757 (500–1256) |
| Frames changed | 18 (607–624) | 19 (499, 1257–1274) |
| Re-timed / unexpected frames | 0 / 0 | 0 / 0 |
| SRT session survived | yes | yes |
| FIPS observations / SRT samples per endpoint | 169 / 328 | 196 / 328 |

The changed frames after the gap are P-frames decoded without their reference, up to the
next I-frame (625 and 1275). In the baseline run, frame 499 also decoded from a partially
received frame just before the outage. Every other frame matched the fixture's own decode
bit-for-bit in both jobs.

## What this shows

The media outage tracks the FIPS link-dead timer. With link-dead at 3 s, FIPS reported
link loss and reparent 4.0–4.5 s after the kill, and the downstream gap was 5.2 s. With
30 s it was 31.0–31.5 s and 31.2 s, as in all three baseline runs. In both profiles the
part after the reparent window is about 1 s or less: the SRT receiver resumed within
the next 500 ms sample or two, and in all four runs the collector saw media again inside
the reparent window or at most 0.83 s after it closed. SRT, the relay and the collector added nothing measurable that depends on the
timer.

Limits:
- This is one variant run on one local clock domain with one fault type. The result is
  ordering-only: no causal claim, no first divergent layer, no fault domain, and nothing
  hitless.
- The 60 s SRT peer-idle timeout is still the experiment setting. The 5.2 s gap is just
  above SRT's 5 s default, and whether a default-profile session would survive is not
  tested here.
- 3 s is not a recommended FIPS setting. Its false-reap risk on lossy or slow links, its
  heartbeat cost, and the two source couplings named in the plan are not measured.
  Choosing production timers is an owner decision.
- G4 stays `in-progress`.
