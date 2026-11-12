# ADR-0010: Select Robotweax SRT 0.3.2 and Telemetry `7a6b8eff`

- Status: accepted
- Date: 2026-11-12
- Supersedes ADR-0008 for the SRT selection and ADR-0009 for the SRT Telemetry selection; the FIPS and toolchain pins, the evidence policy and ADR-0009's experiment decisions are retained

## Decision

Pin Robotweax SRT release `v0.3.2` at `e45d0edd346e5c427d85e4c3b1ac605c81a23397` and
SRT Telemetry main at `7a6b8eff65c686ccafa36a0adace148a8b87d3ca` (2026-10-30) for new Fabric
experiments. Keep FIPS v0.5.3 at `f4a5b4a8e61e340e6be7551608109a5c399f8353`, still the latest
FIPS release on 2026-11-12, and the ADR-0007 CI toolchain pins.

Both are **requalification candidates**. Every retained bundle at SRT v0.3.1 and Telemetry
`1b12f8d7` stays evidence only for those revisions: the 2026-10-28 healthy G4 pilot, the
2026-10-28 G1 run and the four faulted-diamond bundles (first run, repeat, fast-detection
variant and its same-revision baseline). The faulted-diamond validator gains the digest table
the G4 and G1 validators already have (`HISTORICAL_G4_FAULTED_DIAMOND_BUNDLES`): a bundle is
checked against old pins only when its result manifest matches a recorded digest, so a new run
cannot present a historical pin as the active candidate.

## Why these revisions

**SRT v0.3.2** (released 2026-11-05, 69 commits since 0.3.1) keeps shared-library ABI line 0.3
and SRT API 1.5.7. The exported-symbol list is identical to 0.3.1 (85 C exports); `srt.h` only
gains new option values, the `ROBOTWEAX_SRT_GTYPE_MULTICAST` group type and one statistics
struct. Fabric enables none of the new features (experimental multicast dispatch, opt-in
ARQ-first FEC, tail probe). Two changes apply to every connection and are therefore relevant
to Fabric evidence:

- TSBPD drift correction now uses valid measured RTT instead of treating the initial RTT
  default as a measurement. This can change receiver timing in live mode, which is the mode of
  the faulted diamond. It must be observed, not assumed.
- Listeners reserve accept capacity before provisional socket allocation and admission
  callbacks. Fabric experiments use one caller per listener, so no effect is expected.

**SRT Telemetry `7a6b8eff`** is 18 commits after `1b12f8d7` (merged to main as `6702dfee`),
all from 2026-10-28 to 2026-10-30, before SRT 0.3.2 existed. Telemetry has not itself been
qualified against 0.3.2; the local build in the
[refresh assessment](../qualification/dependency-refresh-2026-11-12.md) is the first evidence.
The changes: the delta engine moved onto a shared counter kernel with a counter-trace baseline
test; additive source-identity and observer fields in the JSON snapshot and HTTP history;
a recording write now fails when its directory sync fails; an experimental remote numeric
input. The incident peer source is untouched and the SDK `export_jsonl` it calls still
writes `1alpha1`, so the Fabric adapter contract and golden case are unchanged. The delta
engine refactor is the change most able to alter Fabric observations and is the reason the
healthy pilot and the G1 baseline are repeated before any further faulted run is interpreted.

## Requalification required before promotion

1. Build SRT v0.3.2 and Telemetry `7a6b8eff` together on Linux, pass the complete Telemetry
   suite, and repeat the healthy SRT-over-FIPS G4 capture on FIPS v0.5.3. Retain a new bundle.
2. Repeat the G1 direct-SRT baseline at the new pins and retain it. Tabulate its indicators
   beside the 2026-10-28 run without grading them: no budget is frozen (OD-01, OD-04, OD-14).
3. The faulted-diamond profile of ADR-0009 is unchanged; only the pin row of its plan moves.
   A faulted-diamond run at the new pins is a repeat of the predeclared profile at a new
   revision. It is not comparable with the 0.3.1 runs as if nothing changed: the TSBPD and
   delta-engine changes above sit between them.
4. FIPS-only G2 evidence is unaffected and is not rerun. No gate status changes.

## Requalification outcome (2026-11-12)

Items 1 to 3 completed the same day, each on its first attempt; see the
[refresh assessment](../qualification/dependency-refresh-2026-11-12.md). The G1 run, the healthy
pilot and both faulted-diamond profiles passed and are retained. No gate status changed.

## Sources

- [Robotweax SRT v0.3.2 release](https://github.com/Robotweax/srt/releases/tag/v0.3.2)
- [SRT 0.3.2 release notes](https://github.com/Robotweax/srt/blob/v0.3.2/docs/release-notes-0.3.2.md)
- [SRT Telemetry pinned source](https://github.com/Robotweax/srt_telemetry/tree/7a6b8eff65c686ccafa36a0adace148a8b87d3ca)
- [Prior decisions](0008-srt-031-refresh.md), [ADR-0009](0009-faulted-diamond-media-observation.md)
