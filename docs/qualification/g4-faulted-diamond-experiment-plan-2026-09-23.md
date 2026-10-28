# Proposed G4 faulted-diamond live experiment

Status: **predeclared design; executable since 2026-10-28** through the separate
`G4 Faulted Diamond` workflow, `rimf-lab run-g4-faulted-diamond` and the
`g4-faulted-diamond` result contract, with the execution profile frozen below and in
[ADR-0009](../decisions/0009-faulted-diamond-media-observation.md) before the first run.
The two-node healthy pilot, its workflow and its retained bundles are unchanged.

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

| Item | Value |
| --- | --- |
| Topology | Retained G2 alternate-route diamond: same FIPS timers, 20 ms one-way stimulus on r2–b, no a–b underlay, IPv4 forwarding off on both transits |
| Pins | SRT v0.3.1 `57fcf51a`, SRT Telemetry `1b12f8d7` (media relay), FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5` |
| Fixture | `testsrc2` 320×180, 25 fps, 160 s, MPEG-2 GOP 25 without B-frames, 600 kbit/s video in a 1 Mbit/s CBR transport stream, bit-exact: 4000 frames |
| Source | 1316-byte datagrams on an absolute schedule (10.528 ms), into the caller's relay on `a` |
| SRT | Live, default 120 ms latency, too-late drop on, peer idle 60 000 ms, receive timeout 500 ms |
| Downstream | Collector process on `b` (UDP from the listener's relay, arrival gaps ≥ 250 ms), offline FFmpeg `framehash` SHA-256 decode compared with the fixture's own decode |
| Sampling | SRT both endpoints every 500 ms; FIPS control state every 1 s, every 500 ms between the fault and the observed reparent |
| Fault | SIGKILL of the transit that is `b`'s observed tree parent, 20 s after the source starts; underlay left up |
| Route epoch 2 | Only when a FIPS observation shows `b` on the other transit with the G2 peer/link/tree conditions; evidence = that observation and the one before it |
| Stop rules | Reparent within 60 s and SRT delivery resumed within 120 s of the fault, at least 10 s of media after recovery; otherwise failed |
| Output | Ordering-only timeline (intervals in ms from the SIGKILL, unordered when they overlap), frame comparison, replayable adapters; `G4: not-passed`, no causal claim |
