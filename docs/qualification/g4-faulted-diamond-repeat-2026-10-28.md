# G4 faulted diamond, second retained run (repeat) — 2026-10-28

- Workflow: [G4 Faulted Diamond, run 40748574042](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40748574042)
- Fabric runner revision: `e4bd9963` (branch `dev/g4-faulted-diamond`, PR #12). Runner, tests, schemas, workflows and pins are byte-identical to `43757965`; only documentation and retained evidence differ.
- Pins, profile and contract: identical to the [first retained run](g4-faulted-diamond-2026-10-28.md)
- Platform: Linux x86_64, kernel `6.17.0-1022-azure` (first run: `7.0.0-1017-azure`)

The run passed the pinned Telemetry suite and the experiment's stop rules, and retained the
[16-file bundle](../../qualification/retained-bundles/2026-10-28-g4-faulted-diamond-40748574042/result.json).
The result manifest SHA-256 is
`0b290b2462f0ef2634304b07a590c9ee0fb3363e80005b292b11186329786019`. Repository validation
replays and recomputes it in the same way as the first run.

## Compared with the first run

Times are milliseconds from SIGKILL-sent, at each layer's sampling resolution.

| Observation | Run 40743995191 | Run 40748574042 |
| --- | --- | --- |
| Killed / alternate transit | `r2` / `r1` | `r2` / `r1` |
| Killed daemon exit observed | 16 | 7 |
| Downstream media stops | 143 | 147 |
| SRT receiver stall | 490–990 | 493–993 |
| SRT sender loss or drop | 990–1490 | 993–1493 |
| FIPS link loss and reparent | 30,991–31,491 | 30,993–31,493 |
| SRT receiver resumes | 31,990–32,490 | 30,993–31,493 |
| Downstream media resumes | 32,298 | 31,345 |
| Downstream gap | 32,155 | 31,198 |
| Datagrams delivered / sent | 14,264 / 17,729 | 14,370 / 17,729 |
| Frames missing (one contiguous run) | 782 (499–1280) | 758 (499–1256) |
| Frames concealed until next I-frame | 19 (1281–1299) | 18 (1257–1274) |
| Re-timed / unexpected frames | 0 / 0 | 0 / 0 |
| SRT session survived | yes | yes |

Every other frame matched the fixture's own decode bit-for-bit in both runs. Neither run
missed an SRT sampling interval (327 samples per endpoint), and both made 195 FIPS
observations and cleaned up completely.

## What the two runs show together

The FIPS side is the stable term. Link loss and reparent were first observed in the same
500 ms window, about 31 s after the kill, in both runs; that is the pinned FIPS timers
detecting the dead transit. The roughly 1 s difference in the downstream gap is after
that window: in the repeat, SRT delivery was already back in the same sample in which FIPS
showed the reparent; in the first run it came two 500 ms samples (about 1 s) later. Two runs cannot say
how that post-reparent term is distributed.

Limits are unchanged. This is ordering-only evidence on one local clock domain with one
fault type and an experiment-only 60 s peer-idle timeout. No causal, first-divergent-layer,
fault-domain or hitless claim follows, and G4 stays `in-progress`.
