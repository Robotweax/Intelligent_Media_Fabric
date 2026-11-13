# Proposal: pilot workflow and budgets (OD-01, OD-14) — 2026-11-13

- Status: proposal for the repository owner. Question 2 of section 5 was decided on 2026-11-13 and is recorded in [ADR-0012](0012-interruption-budget.md); questions 1, 3 and 4 are open. The proposal itself freezes no budget and changes no gate.
- Closes nothing by itself. OD-01 and OD-14 close through an ADR that records the owner's choices.

OD-01 asks for a pilot contribution workflow and a downstream interruption budget. OD-14 asks
for design partners and frozen goodput, CPU, failover and operations gates. Until they are
set, every retained number is recorded without a verdict and G1 and G3 cannot be judged.

This note separates what the retained evidence can already answer from what it cannot, and
proposes values where there is a basis for one. Every proposed value is marked as such.

## 1. Pilot workflow (OD-01)

Proposed: one live contribution feed from one sender to one receiver.

| Property | Proposed value | Basis |
| --- | --- | --- |
| Stream | MPEG-TS over SRT live mode, constant bitrate, one program | what every retained faulted run carries |
| Datagram | 1128 bytes (6 TS packets) clear; 5 TS packets (940 bytes) with AES-GCM | the 1139-byte clear and 1123-byte GCM payload budgets over `fips0`; 7 TS packets (1316 bytes) do not fit |
| Qualification rates | 1 Mbit/s (existing fixture) and one higher rate, proposed 10 Mbit/s | 1 Mbit/s is retained; 10 Mbit/s is a common contribution rate and is not yet run |
| Topology | two endpoints, two transits, one alternate path | the retained diamond |
| Direction | one-way media, no return channel | retained |

The 1316-byte point matters outside the lab: most SRT senders default to 1316-byte payloads.
A pilot sender must be configured for a smaller payload, or the path fragments. That is
OD-04's subject and is stated here only because the workflow depends on it.

## 2. Downstream interruption budget (OD-01)

This is the value the retained evidence speaks to most directly. The fault is the loss of
the active transit (process kill or silent blackhole, which behaved alike). All gaps are
measured at an independent downstream collector, one run per job on hosted runners.

| Configuration | Retained downstream gaps | Runs |
| --- | --- | --- |
| FIPS link-dead 30 s (stock), SRT peer idle 60 s | 32.2, 31.2, 31.2, 32.2, 32.5, 32.2, 32.2, 32.2 s | 8 |
| FIPS link-dead 30 s (stock), SRT peer idle 5 s (stock), no restart | media does not return | 3 |
| FIPS link-dead 30 s (stock), SRT peer idle 5 s (stock), session restarted | 32.5, 32.9 s | 2 |
| FIPS link-dead 3 s, SRT peer idle 60 s | 5.2, 4.2, 4.2, 5.3, 5.2, 5.0 s | 6 |
| FIPS link-dead 3 s, SRT peer idle 5 s (stock), no restart | media does not return | 3 |
| FIPS link-dead 3 s, SRT peer idle 5 s (stock), session restarted | 6.4, 6.3 s | 2 |

What a candidate budget would make of these:

| Candidate budget | Verdict on retained evidence | What meeting it would take |
| --- | --- | --- |
| Hitless: no missing frame | not met by any run | cannot come from FIPS reconvergence alone at any tested timer; needs redundant paths, which is the SRT-group question (G5, OD-15) |
| 1 s | not met by any run | as above; the smallest retained gap is 4.2 s |
| 6 s, session kept | met in 6 of 6 runs, by 0.7 s at worst | FIPS link-dead 3 s, which is not a qualified setting, and an SRT peer-idle timeout above the 5 s default |
| 10 s, session may restart | met in 8 of 8 runs at link-dead 3 s | FIPS link-dead 3 s and either a raised peer-idle timeout or an application that reconnects |
| 35 s, recovery without an operator | met in 10 of 10 runs that kept or restarted the session | stock FIPS timers; either a raised peer-idle timeout or an application that reconnects |
| any budget, both products at stock settings, no reconnect | not met: media does not return | — |

Proposed: set two numbers, not one.

1. **Target: hitless for a single transit failure.** This is what live contribution is
   normally held to. The evidence says a single SRT session over FIPS cannot meet it, so
   adopting it commits the project to the SRT-group comparison (OD-15) as the next
   experiment, and makes G5 the gate that carries the continuity claim.
2. **Floor for a single path: 6 s with the session kept.** This is the best the retained
   single-path configuration does. It would make link-dead 3 s a setting that has to be
   qualified on lossy and slow links before any claim, since its false-reap risk is unmeasured.

The alternative is to accept 35 s as "recovers unattended" and stop there. It needs no FIPS
change, and it is not a broadcast continuity claim.

Whatever is chosen, the last row stands as a product requirement of its own: with both
products at their defaults a transit failure ends the stream. Either the SRT peer-idle
timeout is part of the pilot profile, or the pilot application must reconnect.

## 3. Steady-state gates (OD-14)

No direct-versus-FIPS scorecard is retained yet. The G1 control and the healthy G4 pilot carry
240 messages in about 1.3 s; that is too small to set goodput or CPU limits from. So the
proposal here is a form and an order, with candidate values that a calibration run must confirm.

| Gate | Proposed rule | Candidate value | Status of the basis |
| --- | --- | --- | --- |
| Correctness | mandatory, no budget | every frame identical downstream on a clean path; zero unrecovered loss | retained for 1 Mbit/s before the fault in every faulted run |
| Goodput | sustain the pilot rates with correctness intact | 1 and 10 Mbit/s for 160 s | 1 Mbit/s retained; 10 Mbit/s not run |
| Wire overhead | bytes on the underlay per media byte, against direct SRT | at most 15 % above direct | arithmetic only: 77 bytes of FIPS overhead on a 1192-byte inner packet is 6.5 %; not measured |
| CPU | per endpoint and per transit, against direct SRT at the same rate | to be set from calibration | unmeasured; the 10 ms tick resolution of the current counter is too coarse for the short run |
| Added latency | SRT RTT over `fips0` against direct | to be set from calibration | unmeasured |
| Failover | the interruption budget of section 2 | — | — |
| Operations | recovery without operator action; every fault visible in retained telemetry | qualitative | met in the retained restart and survival runs for one fault class |

Proposed order: freeze the workload and the correctness rule now; run one predeclared
calibration scorecard (direct and FIPS, 1 and 10 Mbit/s, 160 s, not graded); then freeze the
CPU, overhead and latency numbers from it in the closing ADR. This follows OD-01's own closure
rule, "product input plus calibrated direct baseline". Setting those three numbers before the
calibration would be a guess.

## 4. Design partners (OD-14)

Not proposed here. Naming partners is the owner's decision and does not belong in a public
repository until they agree.

## 5. Decisions asked of the owner

1. Is the pilot workflow of section 1 right, including 10 Mbit/s as the second rate?
2. Interruption budget: hitless target with a 6 s single-path floor, or 35 s unattended recovery?
3. For the pilot profile: raised SRT peer-idle timeout, a reconnecting application, or both?
4. Go-ahead for the calibration scorecard, so the remaining numbers can be frozen from data.

## Limits of this note

- All gaps come from one topology, one fault class with two mechanisms, one runner type and
  a 1 Mbit/s stream. The counts above are small.
- Verdicts in section 2 are what a budget would say about existing runs. They are not gate
  results; no gate changes until an ADR freezes a budget and a predeclared run is judged by it.
- The wire-overhead figure is arithmetic, not a measurement.
