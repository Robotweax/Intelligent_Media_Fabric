# G4 faulted diamond, coordinator-driven reconnect variant — 2026-11-12

- Workflow: [G4 Faulted Diamond, run 43280995407](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43280995407), six matrix jobs on separate runners, all first attempts
- Fabric runner revision: `e969897e` (branch `dev/g4-faulted-diamond-reconnect`, PR #17)
- Pins: SRT v0.3.2 `e45d0edd`, SRT Telemetry `7a6b8eff`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure` in five jobs and `7.0.0-1014-aws` in the `g2-alternate-route`, `default`, `none` job
- Contract: the [coordinator-driven reconnect variant](g4-faulted-diamond-experiment-plan-2026-09-23.md#variant-coordinator-driven-reconnect-predeclared-2026-11-12), predeclared before this run; one change against the `default` peer-idle profile

All six jobs passed the pinned Telemetry suite (81 tests, none failed) and every stop rule,
and retained validated bundles: 23 files where the session was restarted, 16 otherwise.

| FIPS timers | SRT peer idle | Reconnect | Bundle | Result SHA-256 |
| --- | --- | --- | --- | --- |
| `fast-detection` | `default` (5 s) | `coordinator-restart` | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-fast-detection-default-coordinator-restart-43280995407/result.json) | `b5250bc3c8052ed309be779f1b31ead6f327fd166e242489965bd25849e439e0` |
| `fast-detection` | `default` (5 s) | `none` | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-fast-detection-default-none-43280995407/result.json) | `5a660ba80a7e04c376b3d3844460e35bd6dc007393b97c12594529ef6ad58d9b` |
| `fast-detection` | `extended` (60 s) | `none` | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-fast-detection-extended-none-43280995407/result.json) | `bb70b3781d829810e44548363962cb2625c85434350e2a4ddc7993799e1ff92c` |
| `g2-alternate-route` | `default` (5 s) | `coordinator-restart` | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-g2-alternate-route-default-coordinator-restart-43280995407/result.json) | `a8666b99c388928ac29a5b4800c6e774330e740bf45d758b9a7c325afbd76c23` |
| `g2-alternate-route` | `default` (5 s) | `none` | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-g2-alternate-route-default-none-43280995407/result.json) | `56fe8fa5d159cb4fe05709ddbb4a29f8205bddabc4d766f58f40402ddcefd258` |
| `g2-alternate-route` | `extended` (60 s) | `none` | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-g2-alternate-route-extended-none-43280995407/result.json) | `44fe146bc4d9545f888fc77cdeaa71a5ae3f7e620f41042a7ad99f6d508faeab` |

## Side by side

Times are milliseconds from SIGKILL-sent, at each layer's sampling resolution (collector
per datagram, SRT 500 ms, FIPS about 1 s). "—" means the event was not observed or does not
apply. Each column is one job on its own runner.

| Observation | fast, restart | fast, default | fast, extended | 30 s, restart | 30 s, default | 30 s, extended |
| --- | --- | --- | --- | --- | --- | --- |
| Killed / alternate transit | `r1` / `r2` | `r1` / `r2` | `r1` / `r2` | `r2` / `r1` | `r2` / `r1` | `r2` / `r1` |
| Downstream media stops | 119 | 116 | 119 | 133 | 135 | 133 |
| FIPS link loss and reparent | 3,993–4,493 | 3,993–4,493 | 3,994–4,494 | 30,990–31,490 | 30,995–31,495 | 30,991–31,491 |
| First SRT session survived | no | no | yes | no | no | yes |
| Sender's last relayed message, first session | 5,015 | 5,012 | end of run | 5,010 | 5,012 | end of run |
| Session end inferred (sample interval) | 5,493–5,993 | — | — | 5,490–5,990 | — | — |
| Session end confirmed by the sender | 5,993 | — | — | 5,990 | — | — |
| Detection delay | 978 | — | — | 980 | — | — |
| Caller attempts | 1 | — | — | 2 | — | — |
| First attempt | 6,001–6,353, connected | — | — | 5,998–21,490, failed | — | — |
| Second attempt | — | — | — | 21,491–32,530, connected | — | — |
| Media relay restarted | 6,353 | — | — | 32,531 | — | — |
| SRT receiver resumes, first session | — | — | 4,994–5,494 | — | — | 31,991–32,491 |
| Second session first delivery | 6,493–6,993 | — | — | 32,990–33,490 | — | — |
| Downstream media resumes | 6,500 | — | 5,414 | 32,654 | — | 32,328 |
| **Downstream gap** | **6,381** | not ended | **5,295** | **32,521** | not ended | **32,195** |
| Datagrams delivered / sent | 17,025 / 17,729 | 2,211 / 17,729 | 17,246 / 17,729 | 14,124 / 17,729 | 2,212 / 17,729 | 14,260 / 17,729 |
| Frames observed | 3,841 | 499 | 3,891 | 3,186 | 499 | 3,217 |
| Frames missing (one contiguous run from 499) | 159 | 3,501 | 109 | 814 | 3,501 | 783 |
| Frames changed | 17 | 0 | 17 | 12 | 0 | 18 |
| Re-timed / unexpected frames | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| SRT samples per endpoint, first / second session | 54 / 274 | 328 / 0 | 327 / 0 | 54 / 221 | 328 / 0 | 328 / 0 |
| Ordering resolved | yes | yes | yes | yes | yes | yes |

The second session carried 14,814 messages (`fast-detection`) and 11,913 messages
(`g2-alternate-route`) with no send or output failure, and was still connected when the
fixture ended. The changed frames follow the gap up to the next I-frame, as in every
earlier run.

## What this shows

Restarting the session closed the outage under both FIPS timer profiles. The two jobs
without a restart repeated the [default-peer-idle result](g4-faulted-diamond-default-peer-idle-2026-11-12.md):
the session ended and 499 of 4000 frames arrived.

With link-dead at 3 s the gap was 6.38 s. The sender relayed its last message at 5.02 s; the
coordinator confirmed the end at 5.99 s, started one caller attempt at 6.00 s, was connected
at 6.35 s, and the collector saw media at 6.50 s. Of the 1.49 s between the sender's last
message and media, 0.98 s is the coordinator's own detection delay, which an application that
is told about the broken connection would not spend. The same-revision session that
survived with a 60 s peer-idle timeout had a 5.30 s gap, on a different runner.

With link-dead at 30 s the gap was 32.52 s, against 32.20 s for the surviving session. The
first caller attempt ran into the 15 s connect timeout while the path was still down, as the
plan predicted. The second was in progress when FIPS reparented at 31.0–31.5 s and connected
at 32.53 s. Here the outage is set by the FIPS timer in both cases; the restart added about
0.3 s over survival in this one pair of jobs.

The surviving `fast-detection` session resumed at 5,414 ms. The four retained
`fast-detection`, `extended` runs now read 5,321, 4,363, 4,351 and 5,414 ms, two on each side
of the 5 s default.

Limits:
- One run per combination, one fault type, one local clock domain. Ordering-only: no causal
  claim, no first divergent layer, no fault domain, nothing hitless. Differences of a few
  hundred milliseconds between jobs are within what separate runners and the 500 ms SRT
  sampling produce and are not ranked.
- The restart is done by the test coordinator, not by SRT or an application. Its detection
  delay is in the gap and is recorded, not removed. One attempt at a time with a 15 s connect
  timeout is what the pinned incident peer offers, not a product retry policy; with link-dead
  30 s a different cadence would not have shortened this outage, because the second attempt
  was already waiting when the path returned.
- The second session is a new SRT session on the same addresses and ports. Datagrams sent
  while no session existed are lost by design, and nothing is summed across the sessions.
- A local shakedown in an aarch64 container preceded this run and is disclosed in the plan.
  It is not evidence and is not retained.
- 3 s is not a recommended FIPS setting, and neither the peer-idle timeout nor the reconnect
  policy is a product choice made here. They are owner decisions (OD-01, OD-15).
- G4 stays `in-progress`.
