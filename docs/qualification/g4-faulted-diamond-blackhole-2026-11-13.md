# G4 faulted diamond, silent transit blackhole variant — 2026-11-13

- Workflow: [G4 Faulted Diamond, run 43381166414](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43381166414), eight matrix jobs on separate runners, all first attempts
- Fabric runner revision: `d350bc9d` (branch `dev/g4-faulted-diamond-blackhole`, PR #18)
- Pins: SRT v0.3.2 `e45d0edd`, SRT Telemetry `7a6b8eff`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure` in seven jobs and `7.0.0-1014-aws` in the `fast-detection`, `default`, `coordinator-restart` job
- Contract: the [silent transit blackhole variant](g4-faulted-diamond-experiment-plan-2026-09-23.md#variant-silent-transit-blackhole-predeclared-2026-11-12), predeclared before this run; one change against the frozen profile

All eight jobs passed the pinned Telemetry suite (81 tests, none failed) and every stop rule,
and retained validated bundles.

| FIPS timers | SRT peer idle | Reconnect | Fault | Bundle | Result SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `fast-detection` | `extended` | `none` | `transit-blackhole` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-extended-none-transit-blackhole-43381166414/result.json) | `f656bfcb7f9e73d5d94c4d92df94bce05c2adfcaf51fd5b425f2d5f7f5186001` |
| `fast-detection` | `extended` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-extended-none-transit-sigkill-43381166414/result.json) | `3579c97822c0b72d6d17c63ba2d65aa0f5da42704daf377fb1123205587abbf9` |
| `g2-alternate-route` | `extended` | `none` | `transit-blackhole` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-extended-none-transit-blackhole-43381166414/result.json) | `5d04a264917538d739f4ae52db0e7db250ab80f1c9357bedd3d08e2f7b4a119a` |
| `g2-alternate-route` | `extended` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-extended-none-transit-sigkill-43381166414/result.json) | `a99ad4917216973b0c9faf8d09c34c9d4669252abd94ac0e79f2981d3a38c8b9` |
| `fast-detection` | `default` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-default-none-transit-sigkill-43381166414/result.json) | `9fca4fbd19388ec8de70515f386ac44b6d69a7d54956aed7f2c88ed3be5d4b36` |
| `fast-detection` | `default` | `coordinator-restart` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-fast-detection-default-coordinator-restart-transit-sigkill-43381166414/result.json) | `2c322f614e0570e458d427fc917305f27197f72fe720c7edc408d18470e572db` |
| `g2-alternate-route` | `default` | `none` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-default-none-transit-sigkill-43381166414/result.json) | `97a70e6b571abb72b298a1c2280164f93ae7d62dd1bba6029b5d690dc64fe9f0` |
| `g2-alternate-route` | `default` | `coordinator-restart` | `transit-sigkill` | [bundle](../../qualification/retained-bundles/2026-11-13-g4-faulted-diamond-g2-alternate-route-default-coordinator-restart-transit-sigkill-43381166414/result.json) | `4b573cbc7791e3ecc33ff2fe404b656dbe3f66181e029bdc8e4ddde004049ee3` |

## Blackhole beside kill

Times are milliseconds from the fault (`blackhole-start` or `sigkill-sent`), at each layer's
sampling resolution (collector per datagram, SRT 500 ms, FIPS about 1 s). All four jobs used the
60 s `extended` peer-idle timeout and no reconnect. Each column is one job on its own runner.

| Observation | 3 s, blackhole | 3 s, kill | 30 s, blackhole | 30 s, kill |
| --- | --- | --- | --- | --- |
| Faulted / alternate transit | `r2` / `r1` | `r2` / `r1` | `r2` / `r1` | `r2` / `r1` |
| Fault complete (fourth `tc` returned / exit observed) | 12 | 15 | 12 | 17 |
| Transit daemon running after the fault and at the end | yes | killed | yes | killed |
| Downstream media stops | 141 | 140 | 142 | 135 |
| SRT receiver stall | 492–992 | 492–992 | 492–992 | 492–992 |
| SRT sender loss or drop | 992–1,492 | 992–1,492 | 992–1,492 | 992–1,492 |
| FIPS link loss and reparent | 3,992–4,492 | 3,992–4,492 | 30,992–31,492 | 30,992–31,492 |
| SRT receiver resumes | 4,992–5,492 | 4,992–5,492 | 31,992–32,492 | 31,992–32,492 |
| Downstream media resumes | 5,322 | 5,184 | 32,340 | 32,331 |
| **Downstream gap** | **5,181** | **5,044** | **32,198** | **32,196** |
| SRT session survived | yes | yes | yes | yes |
| Datagrams delivered / sent | 17,254 / 17,729 | 17,269 / 17,729 | 14,260 / 17,729 | 14,260 / 17,729 |
| Frames missing (one contiguous run from 499) | 107 | 104 | 783 | 783 |
| Frames changed | 19 | 22 | 18 | 18 |
| Re-timed / unexpected frames | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Ordering resolved | yes | yes | yes | yes |

Packets dropped by the four blackhole qdiscs when the fixture ended:

| Qdisc | 3 s | 30 s |
| --- | --- | --- |
| transit toward `a` | 39 | 61 |
| transit toward `b` | 10 | 31 |
| `a` toward transit | 198 | 2,239 |
| `b` toward transit | 45 | 55 |
| Total | 292 | 2,386 |

## What this shows

At this sampling resolution the silent blackhole and the kill are indistinguishable. FIPS
reported link loss and the reparent in the same observation window under both timer profiles,
the SRT intervals are identical, and the downstream gaps differ by 137 ms with link-dead 3 s
and by 2 ms with 30 s, on separate runners. The plan predicted this.

It also bears on how FIPS detected the kill. A killed daemon's host can answer with ICMP
port-unreachable; a blackhole returns nothing. Detection took the same time in both cases, so
in this topology and FIPS revision the retained kill results do not depend on such replies.
The link-dead timer accounts for the detection time in both.

`a` dropped far more packets toward the transit with the 30 s timer than with 3 s
(2,239 against 198). That fits `a` continuing to send the stream to the dead transit until
its own link-dead timer expired, but the counters are read once at the end and time nothing.

The four other jobs repeat earlier combinations at this revision and agree with the
[default-peer-idle](g4-faulted-diamond-default-peer-idle-2026-11-12.md) and
[reconnect](g4-faulted-diamond-reconnect-2026-11-12.md) records:

| FIPS link-dead | Reconnect | Session survived | Downstream gap | Caller attempts | Detection delay |
| --- | --- | --- | --- | --- | --- |
| 3 s | `none` | no | not ended, 499 of 4,000 frames | — | — |
| 3 s | `coordinator-restart` | no | 6,252 | 1 | 984 |
| 30 s | `none` | no | not ended, 499 of 4,000 frames | — | — |
| 30 s | `coordinator-restart` | no | 32,894 | 2 (first failed) | 999 |

The surviving `fast-detection` kill session resumed at 5,184 ms. The five retained runs of
that combination now read 5,321, 4,363, 4,351, 5,414 and 5,184 ms.

Limits:
- One run per combination, one local clock domain. Ordering-only: no causal claim, no first
  divergent layer, no fault domain, nothing hitless. Differences of a few hundred milliseconds
  between jobs are within what separate runners and the 500 ms SRT sampling produce.
- A full, two-way `netem` blackhole on veth pairs is one kind of silent failure. Partial loss,
  one-way loss and a transit that forwards but corrupts are not tested.
- The blackhole took 12 ms to apply in both jobs; during that time the transit could still
  receive.
- The statement about ICMP is an inference from equal detection times. No packet capture was
  taken, so whether such replies were sent at all in the kill runs is not observed.
- 3 s is not a recommended FIPS setting (OD-01, OD-15).
- G4 stays `in-progress`.
