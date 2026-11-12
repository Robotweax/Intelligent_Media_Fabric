# Proposed G4 faulted-diamond live experiment

Status: **predeclared design; executable since 2026-10-28** through the separate
`G4 Faulted Diamond` workflow, `rimf-lab run-g4-faulted-diamond` and the
`g4-faulted-diamond` result contract, with the execution profile frozen below and in
[ADR-0009](../decisions/0009-faulted-diamond-media-observation.md) before the first run.
The two-node healthy pilot, its workflow and its retained bundles are unchanged.
The [first retained run](g4-faulted-diamond-2026-10-28.md) (40743995191) passed this
experiment on 2026-10-28 and a [repeat](g4-faulted-diamond-repeat-2026-10-28.md) (40748574042)
reproduced it; both are ordering-only and do not pass G4. The
[fast-detection variant](g4-faulted-diamond-fast-detection-2026-10-30.md) (41022516133) ran on
2026-10-30 alongside a same-revision baseline. Both profiles were
[repeated at SRT v0.3.2](g4-faulted-diamond-srt-032-2026-11-12.md) (43244304348) on 2026-11-12. The
[default-peer-idle variant](g4-faulted-diamond-default-peer-idle-2026-11-12.md) (43255432045) ran the
same day: the session ended under both FIPS timer profiles.

## Question and fixed setup

Can synchronized SRT, FIPS control-plane and independent downstream media
observations identify the first *observed* divergence during an automatic
FIPS transit failover, without mistaking timestamp order for cause?

- Pin the exact Fabric, Robotweax SRT, SRT Telemetry and FIPS revisions and
  binary hashes; use one Linux host and one boot-scoped monotonic clock domain.
- Use four isolated namespaces in the authenticated `a–r1–b` / `a–r2–b`
  diamond, with no direct `a–b` underlay and IPv4 forwarding disabled on both
  transits. SRT endpoints exist only on `a` and `b` over IPv6 `fips0`.
- Prove both transit links and a baseline exact SRT transfer before injection.
  Identify the active transit from `b`'s observed FIPS tree parent and confirm
  its forwarding counter increased. Do not assume `r1` or exclusive forwarding:
  the retained G2 runs saw counters increase on both transits.
- Kill the observed active FIPS daemon with `SIGKILL`, leave underlay
  interfaces up, and issue no manual route, connect or session-reset command.
  Record injection and process-exit monotonic times separately.

## Required observations

1. Collect bounded SRT Telemetry source recordings from both endpoints and
   adapt them without reinterpretation of source quality flags. Keep FIPS
   link-estimator, tree-parent, peer and forwarding observations in their own
   metric namespaces. Record process exit and interface state independently.
2. Start with route epoch 1. Emit an explicit transition marker only after a
   FIPS control-plane observation proves `b` changed parent to the other
   authenticated transit; observations after that marker use epoch 2. A
   timeout, missing parent or ambiguous transition produces unavailable
   evidence, not an inferred epoch change.
3. Use a downstream media decoder/collector in a process distinct from both
   SRT incident peers. It must report bounded frame sequence, decode result,
   presentation time and frame hash (not raw media) before and after injection.
   The current provider-linked application receiver is insufficient. Pin the
   decoder build and deterministic media fixture before execution.
4. Preserve source availability and clock-domain metadata for every event.
   Do not compare across epochs as if they were one route, or turn FIPS MMP
   loss into an SRT loss/retransmission metric.

## Evaluation and stop rules

The lab run may be reported as an **experiment success** only if the topology,
baseline delivery, fault injection, observed reparenting, two route epochs,
independent decoded-frame observations, replayable adapters, artifact hashes
and full cleanup are present. The G2 60-second reparent and 180-second payload
recovery limits are useful bounded lab stop conditions; they are not a frozen
product media-interruption budget. Missing observations or an exceeded bound
must produce a failed or insufficient-evidence result, never a G4 pass.

A first-divergent-layer hypothesis additionally needs an explicit mapping from
the first changed source observation to the independently observed downstream
effect, with any clock uncertainty and alternative explanations recorded.
Temporal ordering by itself cannot establish causality. No G3, G4, G5 or G6
gate passage, hitless-media claim, or automated control action is authorized by
this plan. OD-01 and OD-14 still block a product continuity threshold.

Implementation is blocked until the separate four-node SRT runner, independent
decoder/collector and fault-result contract exist and pass negative tests. The
next implementation should keep the healthy-pilot workflow and result schema
unchanged, and publish its own fail-closed artifact.

## Decoder-observation component

The Fabric `assess-media-framehash` command now compares bounded FFmpeg
[`framehash` SHA-256](https://ffmpeg.org/ffmpeg-formats.html#framehash) recordings
from a reference and a downstream decode. It reports missing, unexpected and
changed presentation timestamps, changed frame sizes and maximum consecutive
missing frames; it stores recording digests, not raw media. Duplicate PTS,
unsupported hash algorithms, multiple streams and incomparable time bases
fail closed. Its output always says `G4: not-passed` because frame comparison
alone cannot identify a cause.

The manually dispatchable, path-scoped PR `G4 Media Framehash Harness` workflow
checks this parser against real FFmpeg output from separate decode processes.
[Run 35876847330](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35876847330)
passed with 30/30 exact synthetic frames, no missing or changed frames, and an
explicit `G4: not-passed` conclusion. It uses the runner package only as a
**harness syntax check**: no Robotweax SRT, FIPS, route failure or independent
downstream network path is exercised. The pinned Robotweax SRT
[FFmpeg integration](https://github.com/Robotweax/srt/blob/def14a7b6d8a2ba1860677414e415fd86bbc953a/docs/ffmpeg-integration.md)
uses FFmpeg commit `3acec0a1af2dda0a0838689b8b8649e7deb080a0` in its CI,
but its minimal smoke profile copies the MPEG-2 bitstream rather than decoding
frames. A future Fabric live workflow must build and verify that pinned
provider/FFmpeg pair with an actual video decoder and feed the same faulted
SRT stream to the independent observer before this component can contribute
G4 evidence. For new runs, use the SRT v0.2.6 candidate selected by
[ADR-0006](../decisions/0006-srt-026-baseline.md); the linked 0.2.4 integration
and framehash workflow remain historical harness evidence only.

## Frozen execution profile (2026-10-28)

Set before the first run; a change is a new predeclaration, not a tuning of a result.

Revision 2026-10-28, after the first attempts: the datagram changed from seven TS packets
(1316 B) to six (1128 B). At 1316 B each SRT data packet exceeded the 1203-byte inner IPv6
MTU documented in the [SRT-over-FIPS profile](../protocols/srt-over-fips-profile-v0.md), so no
media was delivered and the runner stopped before the fault; the
[failed attempt is retained](../../qualification/failure-results/README.md). Nothing else changed.

Second revision 2026-10-28, after run 40740237463: both decodes add `-dts_delta_threshold
1000000`. With FFmpeg's default 10 s MPEG-TS discontinuity threshold, the 31 s outage was
re-based out of the timestamps, so every post-gap frame compared as changed (2745) and the
outage appeared as 756 frames missing at the end. The fixture contains no real
discontinuity, so disabling the correction measures the stream as sent; a run now fails
closed if an observed frame equals a reference frame at another timestamp. That run's
timeline is valid but it is superseded and not retained as a result. Nothing else changed.

| Item | Value |
| --- | --- |
| Topology | Retained G2 alternate-route diamond: same FIPS timers (profile `g2-alternate-route`; see the variant below), 20 ms one-way stimulus on r2–b, no a–b underlay, IPv4 forwarding off on both transits |
| Pins | SRT v0.3.2 `e45d0edd`, SRT Telemetry `7a6b8eff`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5` ([ADR-0010](../decisions/0010-srt-032-refresh.md), from 2026-11-12; the runs retained through 2026-10-30 used SRT v0.3.1 `57fcf51a` and Telemetry `1b12f8d7`) |
| Fixture | `testsrc2` 320×180, 25 fps, 160 s, MPEG-2 GOP 25 without B-frames, 600 kbit/s video in a 1 Mbit/s CBR transport stream, bit-exact: 4000 frames |
| Source | 1128-byte datagrams (six TS packets) on an absolute schedule (9.024 ms), into the caller's relay on `a`; must fit the fips0 clear SRT payload budget (reported inner IPv6 MTU − 64 B), checked before the run |
| SRT | Live, default 120 ms latency, too-late drop on, peer idle 60 000 ms, receive timeout 500 ms |
| Downstream | Collector process on `b` (UDP from the listener's relay, arrival gaps ≥ 250 ms), offline FFmpeg `framehash` SHA-256 decode (`-dts_delta_threshold 1000000`) compared with the fixture's own decode; fail closed on re-timed frames |
| Sampling | SRT both endpoints every 500 ms; FIPS control state every 1 s, every 500 ms between the fault and the observed reparent |
| Fault | SIGKILL of the transit that is `b`'s observed tree parent, 20 s after the source starts; underlay left up |
| Route epoch 2 | Only when a FIPS observation shows `b` on the other transit with the G2 peer/link/tree conditions; evidence = that observation and the one before it |
| Stop rules | Reparent within 60 s and SRT delivery resumed within 120 s of the fault, at least 10 s of media after recovery; otherwise failed |
| Output | Ordering-only timeline (intervals in ms from the SIGKILL, unordered when they overlap), frame comparison, replayable adapters; `G4: not-passed`, no causal claim |

## Variant: fast FIPS detection (predeclared 2026-10-30)

Set before any run of the variant, after the two retained runs of the profile above
([first](g4-faulted-diamond-2026-10-28.md), [repeat](g4-faulted-diamond-repeat-2026-10-28.md)).
Both showed FIPS link loss and reparent in the same 500 ms window about 31 s after the kill,
which matches the diamond's configured `link_dead_timeout_secs: 30` (heartbeat 10 s, tick
1 s, the FIPS v0.5.3 defaults). The variant asks one question: does the media outage track
the FIPS link-dead timer?

Exactly one thing changes. The FIPS liveness timers on all four nodes become heartbeat 1 s
and link-dead 3 s (tick stays 1 s). This is profile `fast-detection`. The baseline
profile is now named `g2-alternate-route`, and results recorded before the field existed
are read as that profile. Everything else in the frozen table above is unchanged, including
the 60 s SRT peer-idle timeout, the fault, its timing, the sampling and the stop rules. Each
workflow run executes both profiles side by side, so every variant run comes with a
same-revision baseline run.

FIPS v0.5.3 has no floor for `heartbeat_interval_secs`, and its own tests cover a 1 s
interval. Two couplings in the pinned source are recorded as known and not compensated:
- The msg1 replay damper (15 s) is documented as sitting below a 30 s link-dead timeout.
- FMP's liveness interval is a 10 s constant that does not follow the config.

Neither applies to a transit that stays dead for the rest of the run. A shorter link-dead
timeout can also reap a healthy but delayed link. The 20 ms stimulus on r2–b is far below
3 s. A reap before the fault would show up as an early route change, so from this
declaration on, both profiles fail closed if any FIPS observation before the kill shows `b`
on a parent other than the transit about to be killed.

What will be reported, with no budget or threshold attached: the same ordering-only
timeline and frame comparison, side by side with the same-revision baseline run. The
variant cannot pass G4 or set a FIPS product timer. Choosing production FIPS timers stays an
owner decision outside this experiment.

## Variant: default SRT peer idle (predeclared 2026-11-12)

Set before any run of the variant, after six retained runs of the profiles above. All six
used `SRTO_PEERIDLETIMEO` 60 000 ms, chosen only so that one session could span the outage.
With the `fast-detection` timers the downstream gap was 5.2 s at SRT v0.3.1 and 4.2 s at
v0.3.2 ([record](g4-faulted-diamond-srt-032-2026-11-12.md)), on either side of SRT's 5 s
default. The variant asks one question: does a session with the default peer-idle timeout
survive the outage, under each FIPS timer profile?

Exactly one thing changes. `SRTO_PEERIDLETIMEO` on both peers becomes 5 000 ms. This is
SRT peer-idle profile `default`; the 60 s setting is now named `extended`, and results
recorded before the name existed are read as `extended` from their recorded value. The
topology, fixture, source, fault, its timing, the sampling, the downstream decode and both
FIPS timer profiles are unchanged. Each workflow run executes all four combinations, so every
`default` run comes with same-revision `extended` runs.

One stop rule changes, for the `default` profile only. A session that ends is an outcome of
this experiment, so missing SRT recovery no longer fails the run when at least one endpoint
reports the ended session at media stop. Every other rule stands:
- reparenting must still be observed within 60 s of the fault;
- if delivery resumes, at least 10 s of media must follow it;
- if delivery does not resume and neither endpoint reports an ended session, the run fails;
- under `extended`, missing recovery within 120 s fails the run as before.

What an ended session looks like in the bundle, fixed here before the first run:
- `capture.srt_session_survived` is false and `capture.srt_delivery_resumed` says whether
  delivery came back before the end of the run. The validator checks both against the
  retained relay record and the recomputed timeline.
- The timeline gains `srt_session_end`: which endpoint reported the end, and each endpoint's
  last relayed message in ms from the SIGKILL. The relay stops at the first send or receive
  that reports the ended session, so the sender's value is a lower bound on when the sender
  saw the session end. The SRT samples carry no connection state, so no sampled interval
  for the end exists.
- When media never resumes, `media_downstream_stop` is the collector's last arrival and
  `media_downstream_resume` and `media_downstream_gap_ms` are null. No gap length is reported
  for an interruption that did not end.
- The frame comparison then shows every frame after the stop as missing. That count is the
  length of the fixture's remainder, not a recovery measurement.

Known before the run, and not compensated:
- The Telemetry incident peer does not reconnect. An ended session ends media for the rest
  of the run. This variant therefore measures survival only; the interruption an operator
  would see with a reconnecting application is a separate variant that needs a Telemetry
  change.
- On 2026-11-12 a local probe at the pinned revisions (Linux aarch64 container, one peer
  frozen with SIGSTOP) showed that a peer whose session ended can still be sampled, reports
  `connectionBroken` and writes its recording. That is what makes this variant runnable
  without a Telemetry change. It is a feasibility check, not evidence.
- With the 30 s link-dead profile the session is expected to end, because the outage is
  about six times the timeout. That combination is kept as the control for the new outcome,
  not as a question.
- A single `fast-detection` run cannot settle a result this close to the timeout. Whatever
  it shows is one observation of a boundary case.

What will be reported, with no budget or threshold attached: for each of the four
combinations, whether the session survived, whether delivery resumed, the ordering-only
timeline and the frame comparison. The variant cannot pass G4, cannot set an SRT or FIPS
product timer, and makes no causal claim. Whether the default profile is acceptable for a
product is an owner decision (OD-01, OD-15).
