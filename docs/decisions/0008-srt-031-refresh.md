# ADR-0008: Select Robotweax SRT 0.3.1 and the matching Telemetry revision

- Status: superseded by ADR-0009 for the SRT Telemetry selection; SRT v0.3.1 and evidence policy retained
- Date: 2026-10-25
- Supersedes ADR-0007 for the SRT and Telemetry selections; its FIPS and toolchain pins and its evidence policy are retained

## Decision

Pin Robotweax SRT release `v0.3.1` at `57fcf51a31ec2eecf4189d63c2f998ff1e8daaa1` and
SRT Telemetry main at `1a018dfdc89a964b03159aebc155d39bca524384` (2026-10-25, the commit
that integrates 0.3.1) for new Fabric experiments. Keep FIPS v0.5.3 at
`f4a5b4a8e61e340e6be7551608109a5c399f8353` and the ADR-0007 CI toolchain pins.

Both are **requalification candidates**. The three retained healthy G4 bundles (SRT 0.2.4,
0.2.6 and 0.3.0) and the retained G1 bundle (SRT 0.3.0) stay evidence only for their own
recorded revisions, accepted by the validators solely when their original result manifests
match the digests in `HISTORICAL_G4_BUNDLES` and the new `HISTORICAL_G1_BUNDLES`. A new run
cannot present a historical pin as the active candidate.

## Why these revisions

**SRT v0.3.1** (tagged 2026-10-25) integrates main since 0.3.0 and keeps shared-library ABI
line 0.3 and SRT API 1.5.7; the 84 published 0.3.0 C exports and layouts are preserved and
`robotweax_srt_connect_group_acquire` is the 85th additive export, so the pinned Telemetry
adapter rebuilds without source change. Relevant to Fabric: CONNECTED is now published only
after transport-runtime installation (so an incident peer that samples immediately after
CONNECTED sees an installed transport), bounded rejected-message lookup and linger
ownership, reduced sparse payload-pool growth with named library workers, default-off
compiled congestion-controller and packet-filter bindings (not enabled by Fabric; the
provider interfaces are private), and per-member `SRTO_GROUPMINSTABLETIMEO` for Backup
groups. None of this is Fabric-over-FIPS evidence; the CONNECTED change in particular can
shift the first sample's counters and must be observed, not assumed.

**SRT Telemetry `1a018dfd`**: five commits since `24475483`: recording schema `1alpha3`
(pairs both ends of a session; used by the embedding library's `jsonl=DIR` export, while the
SDK `export_jsonl` the incident peer calls still writes `1alpha1`, so the Fabric adapter
contract is unchanged) and a documentation commit recording that 0.3.1 leaves the statistics
clock unchanged and that CONNECTED now follows runtime installation. No public header the
adapter uses changed semantics; `srt_telemetry.h` gained the `1alpha3` pairing types only.

## Requalification required before promotion

1. Build SRT v0.3.1 and Telemetry `1a018dfd` together on Linux, pass the complete Telemetry
   suite, and repeat the healthy SRT-over-FIPS G4 capture on FIPS v0.5.3. Retain a new bundle;
   do not edit the 0.3.0 bundle.
2. Repeat the G1 direct-SRT baseline at the new pin and retain it. Compare its recorded
   indicators with the 0.3.0 run in the dated record without grading them: no budget is
   frozen (OD-01, OD-04, OD-14).
3. FIPS-only G2 evidence is unaffected by the SRT change and is not rerun for this ADR.
4. G3 and the faulted-diamond G4 plan keep their prerequisites. No gate status changes.

## Requalification outcome (2026-10-25)

Items 1 and 2 completed the same day; see the
[refresh assessment](../qualification/dependency-refresh-2026-10-25.md). No gate status changed.

## Sources

- [Robotweax SRT v0.3.1 release](https://github.com/Robotweax/srt/releases/tag/v0.3.1)
- [SRT 0.3.1 release notes](https://github.com/Robotweax/srt/blob/v0.3.1/docs/release-notes-0.3.1.md)
- [SRT Telemetry pinned source](https://github.com/Robotweax/srt_telemetry/tree/1a018dfdc89a964b03159aebc155d39bca524384)
- [Prior Fabric refresh decision](0007-dependency-refresh-2026-10-22.md)
