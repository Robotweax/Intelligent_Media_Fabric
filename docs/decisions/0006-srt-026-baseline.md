# ADR-0006: Select Robotweax SRT 0.2.6 for new Fabric runs

- Status: accepted
- Date: 2026-09-27
- Supersedes ADR-0005 for new dependency selections; its FIPS and Telemetry pins are retained

## Decision

Pin Robotweax SRT release `v0.2.6` at
`50cba37bc89f423ee7c0a292c3c3eae71b5fc7f9` for new Fabric experiments.
Use the public C API and the namespaced shared library. Keep FIPS v0.5.1 at
`c5aeef39ef9442d9e5047331156df368ace40cbd` and SRT Telemetry at
`bf10da0431fdf23772210262755f745b62b6ff58`.

This is an immutable **requalification candidate**, not a G3/G4 gate passage or a
production rollout. New runs must build SRT and the pinned Telemetry adapter
together, verify their source revisions and record binary digests. The healthy
G4 pilot and all earlier retained results remain evidence only for their own
recorded revisions. The 2026-09-23 G4 result is accepted by the validator only
when its original result manifest has SHA-256
`ba417e4869910940939308203602a5643c24dc7ba834bea96e49ac5d9ba8092b`; a new
run cannot present the old SRT commit as the active candidate.

## Rationale and boundaries

The existing Fabric pin `def14a7b6d8a2ba1860677414e415fd86bbc953a`
declares SRT 0.2.4 and is an ancestor of the 0.2.6 release commit. The public C
headers and C export inventory do not change across this selected range; the
shared-library ABI line remains 0.2 and `srt_getversion()` still reports the
SRT 1.5.7 compatibility profile. The SRT wire format and default AES-CTR / opt-in
AES-GCM behavior are not intentionally changed. Source-tree C++ implementation
layouts do change, so direct C++ consumers must be rebuilt with matching headers.

0.2.6 adds bounded retry of transient UDP send backpressure, fairer channel work,
idle readiness, targeted epoll notifications, send/loss-list improvements and
separate payload storage. These are relevant to stream continuity, busy shared
listeners, CPU and RSS, but release qualification is not Fabric-over-FIPS
qualification. In particular, positive Live `MAXBW` now acts as an absolute
rate; the current G4 peer does not set it, but later profiles must test it.
Neither universal throughput/latency gains nor lower peak RSS are assumed.

## Requalification required before promotion

1. Run the pinned SRT Telemetry build and complete test suite against the new
   SRT headers and `librobotweax-srt.so` on Linux.
2. Repeat the healthy SRT-over-FIPS G4 capture with unchanged correctness,
   sample-count and cleanup requirements. Retain a new bundle with 0.2.6 source
   and binary provenance; do not edit the 0.2.4 bundle.
3. For G3, compare direct SRT and SRT-over-FIPS at the same 0.2.6 pin and
   unchanged offered load. Record payload identity, timing, CPU, RSS, wire
   overhead and queue behavior under idle, sustained load, transient backpressure
   and loss. Do not transfer performance claims from SRT's own release CI.
4. The planned faulted-diamond G4 experiment still needs its separate runner,
   route-epoch evidence and independent media decoder. A healthy pilot does not
   satisfy those requirements or pass G3/G4.

FIPS-only G2 evidence is unaffected by changing the SRT candidate. Existing
budgets and fail-closed rules remain unchanged.

## Preliminary implementation checks

On 2026-09-27, the v0.2.6 shared OpenSSL library and the pinned SRT Telemetry
consumer built together on macOS arm64. The complete Telemetry CTest suite passed
42/42 with local UDP socket access; the Fabric repository unit/contract suite and
retained-evidence validation also passed. The
[Linux healthy SRT-over-FIPS capture](../qualification/g4-live-capture-srt-026-2026-09-27.md)
then passed with exact application delivery and a retained bundle. These checks
establish build, adapter and one healthy-path integration only. They do not
replace the direct/FIPS performance comparison or faulted media experiment above.

## Sources

- [Robotweax SRT v0.2.6 release](https://github.com/Robotweax/srt/releases/tag/v0.2.6)
- [SRT v0.2.6 UDP backpressure contract](https://github.com/Robotweax/srt/blob/v0.2.6/docs/udp-backpressure.md)
- [SRT v0.2.6 payload storage contract](https://github.com/Robotweax/srt/blob/v0.2.6/docs/payload-storage.md)
- [Prior Fabric refresh decision](0005-srt-fips-requalification.md)
