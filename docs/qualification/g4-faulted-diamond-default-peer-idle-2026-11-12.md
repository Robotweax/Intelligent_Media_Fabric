# G4 faulted diamond, default SRT peer-idle variant — 2026-11-12

- Workflow: [G4 Faulted Diamond, run 43255432045](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43255432045), four matrix jobs on separate runners, all first attempts
- Fabric runner revision: `8e22ba84` (branch `dev/g4-faulted-diamond-default-peer-idle`, PR #16)
- Pins: SRT v0.3.2 `e45d0edd`, SRT Telemetry `7a6b8eff`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure` (all four jobs)
- Contract: the [default-peer-idle variant](g4-faulted-diamond-experiment-plan-2026-09-23.md#variant-default-srt-peer-idle-predeclared-2026-11-12), predeclared before this run; one change against the frozen profile

All four jobs passed the pinned Telemetry suite (81 tests, none failed, none skipped) and
every stop rule, and retained validated 16-file bundles:

| FIPS timers | SRT peer idle | Bundle | Result SHA-256 |
| --- | --- | --- | --- |
| `fast-detection` | `default` (5 s) | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-fast-detection-default-43255432045/result.json) | `f867810526e3cfd35defa7022639c28facf68ce73b6c59ea2f4d7215e36e45fd` |
| `fast-detection` | `extended` (60 s) | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-fast-detection-extended-43255432045/result.json) | `4892dc9b441fae3bad0ff59df7974bf72cecf53c01471d2d1c03d6ce87552975` |
| `g2-alternate-route` | `default` (5 s) | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-g2-alternate-route-default-43255432045/result.json) | `14870bff776f6ffd7460e5760a9b16512f64f20366503131b2c483e3042acb80` |
| `g2-alternate-route` | `extended` (60 s) | [bundle](../../qualification/retained-bundles/2026-11-12-g4-faulted-diamond-g2-alternate-route-extended-43255432045/result.json) | `84a559ac6bcd6cec5e075bfdfb944940e4a5e121fa5212ca7ab8035b8b041ab4` |

## Side by side

Times are milliseconds from SIGKILL-sent, at each layer's sampling resolution (collector
per datagram, SRT 500 ms, FIPS about 1 s). "—" means the event was not observed.

| Observation | `fast-detection`, `default` | `fast-detection`, `extended` | `g2-alternate-route`, `default` | `g2-alternate-route`, `extended` |
| --- | --- | --- | --- | --- |
| Killed / alternate transit | `r2` / `r1` | `r2` / `r1` | `r2` / `r1` | `r1` / `r2` |
| Downstream media stops | 132 | 137 | 133 | 113 |
| SRT receiver stall | 493–993 | 491–991 | 492–992 | −7–493 |
| SRT sender loss or drop | 993–1,493 | 991–1,491 | 992–1,492 | 993–1,493 |
| FIPS link loss and reparent | 3,993–4,493 | 3,991–4,491 | 30,993–31,493 | 30,994–31,494 |
| **SRT session survived** | **no** | yes | **no** | yes |
| Sender's last relayed message | 5,018 | end of run | 5,010 | end of run |
| Receiver's last relayed message | 132 | end of run | 133 | end of run |
| SRT receiver resumes | — | 3,991–4,491 | — | 32,493–32,993 |
| Downstream media resumes | — | 4,351 | — | 32,579 |
| Downstream gap | not ended | 4,214 | not ended | 32,466 |
| Datagrams delivered / sent | 2,211 / 17,729 | 17,361 / 17,729 | 2,210 / 17,729 | 14,235 / 17,729 |
| Frames observed | 499 (0–498) | 3,917 | 499 (0–498) | 3,211 |
| Frames missing | 3,501 (499–3999) | 83 (500–582) | 3,501 (499–3999) | 789 (499–1287) |
| Frames changed | 0 | 18 (499, 583–599) | 0 | 12 (1288–1299) |
| Re-timed / unexpected frames | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Ordering resolved | yes | yes | yes | no |

In the `g2-alternate-route`, `extended` job the observed active transit was `r1`, where the
other three jobs and all earlier retained runs had `r2`. The runner kills whichever transit
`b` uses, so this is within the contract; the alternate path then is the one with the 20 ms
stimulus on r2–b. Its SRT receiver stall interval starts 7 ms before the kill because the
last sample without a stall was taken just before it, which leaves the ordering unresolved.

## What this shows

With the default 5 s peer-idle timeout the SRT session did not survive the outage under
either FIPS timer profile. Both endpoints reported an ended session, delivery never resumed,
and the downstream stream stopped for the rest of the run: 499 of 4000 frames arrived, none
of them changed. The sender relayed its last message 5.0 s after the kill in both jobs, which
bounds from below when the sender saw the session end. The receiver's relay record does not
time its end; its last message is the last datagram before the outage.

The 30 s profile behaved as predicted in the plan: the outage is about six times the timeout.

The `fast-detection` result is the informative one, and it is a single observation of a
boundary case. FIPS reported the reparent 4.0–4.5 s after the kill, before the session ended
at about 5.0 s, and in the same-revision `extended` job media was flowing again at 4.35 s.
This run does not show when the path carried SRT packets again in the `default` job itself:
with no surviving session there is no resume to observe. In the three retained
`fast-detection`, `extended` runs media resumed at 5,321 ms
([SRT v0.3.1](g4-faulted-diamond-fast-detection-2026-10-30.md)), 4,363 ms
([SRT v0.3.2](g4-faulted-diamond-srt-032-2026-11-12.md)) and 4,351 ms (this run), on both
sides of 5.0 s. So this run is consistent with either explanation: the path came back too
late in this job, or it came back in time and the session ended anyway. Nothing here
distinguishes them, and no cause is claimed.

What it does establish is narrower: with link-dead at 3 s, a default-profile session cannot
be relied on to survive this fault. One run ended, and in the `extended` runs media was
back at most about 0.65 s before the 5 s mark and once after it.

Limits:
- One run per combination, one fault type, one local clock domain. Ordering-only: no causal
  claim, no first divergent layer, no fault domain, nothing hitless.
- The incident peer does not reconnect. The missing-frame counts for the `default` jobs are
  the remainder of the fixture, not an interruption an operator would see. A reconnecting
  application would recover in some time this experiment does not measure.
- The SRT samples carry no connection state, so the session end is bounded only by the
  sender's last relayed message.
- 3 s is not a recommended FIPS setting, and 5 s versus 60 s is not a product choice made
  here. Both are owner decisions (OD-01, OD-15).
- G4 stays `in-progress`.
