# ADR-0009: Observe one SRT media stream through a faulted FIPS diamond

- Status: accepted
- Date: 2026-10-28
- Supersedes ADR-0008 for the SRT Telemetry selection; its SRT v0.3.1 pin, the FIPS and toolchain pins and the evidence policy are retained

## Context

The predeclared [faulted-diamond G4 plan](../qualification/g4-faulted-diamond-experiment-plan-2026-09-23.md)
requires the *same* faulted SRT stream to be recorded by SRT Telemetry and decoded by a
downstream process independent of both SRT peers. On 2026-10-28 no pinned program could
do that: the Telemetry incident peer only carried a numbered synthetic payload and failed
on the first missing message; Robotweax SRT's `srt_udp_bridge` example carries MPEG-TS but
is IPv4-only (`fips0` is IPv6) and records no Telemetry; and SRT socket handles are
process-local, so Telemetry can only record a socket in its own process. Separately, the
retained [v0.5.3 alternate-route result](../qualification/fips-g2-linux-alternate-route-v0.5.3-2026-10-22.md)
needs about 39 s to restore the path, while SRT's default peer-idle timeout is 5 s.

## Decision

1. **Media host.** Extend the Telemetry incident peer (srt_telemetry
   [#67](https://github.com/Robotweax/srt_telemetry/pull/67)) with an opaque UDP media relay
   (`--media-udp-input` on the caller, `--media-udp-output` on the listener,
   `START_MEDIA`/`STOP_MEDIA`) and `--peer-idle-timeout-ms`. SRT hosting and SRT semantics
   stay in Telemetry (ADR-0004); Fabric still consumes only its CLI, its recordings and the
   `1alpha1` JSONL contract. Pin SRT Telemetry at
   `1b12f8d7d75658cb7b7e00a0575fc77d965dbbec`, the commit that adds the relay; the incident
   peer's existing commands, outputs and recording are unchanged.
2. **SRT profile for the first faulted run.** Live mode with the default 120 ms latency and
   too-late-packet drop, `SRTO_PEERIDLETIMEO` 60 000 ms so one session can span the
   measured outage, receive timeout 500 ms. This is an experiment profile chosen by the
   owner on 2026-10-28, not a product setting; a 5 s default-profile variant is not part of
   this ADR.
3. **Route epochs inside one recording.** The SRT adapter context gains an optional
   `route_epoch_transitions` list (`route_epoch` +1 at a strictly later
   `from_monotonic_ns`). Each sample takes the epoch in force at its own sample time.
   This is explicit Fabric context, within ADR-0004's boundary; contexts without the field
   behave byte-for-byte as before and the golden case is unchanged. The delta of the first
   epoch-2 sample covers time before the marker; the experiment compares totals and
   intervals across the marker, never deltas as if they were one route.
4. **Independent downstream observation.** A Fabric collector process in `b`'s namespace
   receives the listener's UDP output and appends it to one file with bounded arrival
   statistics; after the run a separate FFmpeg process decodes it to `framehash` SHA-256,
   compared with the fixture's own decode by `assess-media-framehash`. The decode is
   offline, not a live player; the arrival timeline comes from the collector. FFmpeg is the
   Ubuntu 24.04 package, pinned by its exact version string
   (`ffmpeg version 6.1.1-3ubuntu5`, checked before the run) and recorded binary digest; a
   different version fails closed.
5. **Media fixture.** A deterministic 160 s `testsrc2` 320×180 at 25 fps, MPEG-2 GOP 25
   without B-frames, 600 kbit/s video in a 1 Mbit/s constant-rate transport stream
   (bit-exact flags, single thread): 4000 frames, sent as 1316-byte datagrams on an absolute
   schedule (datagram *i* at start + *i* × 10.528 ms). Two encodes on 2026-10-28 were
   byte-identical; each run still records the fixture digest.

## Consequences

The Telemetry change moves the healthy G4 pilot and the G1 baseline to a new pin, so both
are re-run at `1b12f8d7` and retained; the 2026-10-25 G4 and G1 bundles become
digest-locked history. Historical-bundle detection is now keyed on the whole recorded pin
set, because a Telemetry-only re-pin creates history at the active SRT commit. FIPS-only G2
evidence is unaffected.

The faulted result is ordering-only: each layer's change is an interval at its own
resolution (collector per datagram, SRT 500 ms, FIPS about 1 s) and overlapping intervals
are reported as unordered. No first divergent layer, cause, hitless claim, product
interruption budget or gate passage follows from it. OD-01 and OD-14 still block a
continuity threshold, and OD-15 still asks for the SRT-group comparison.

## Sources

- [srt_telemetry#67, incident peer media relay](https://github.com/Robotweax/srt_telemetry/pull/67)
- [srt_telemetry#66, fault-lab advice persistence](https://github.com/Robotweax/srt_telemetry/issues/66)
- [Faulted-diamond plan](../qualification/g4-faulted-diamond-experiment-plan-2026-09-23.md)
- [Prior refresh decision](0008-srt-031-refresh.md)
