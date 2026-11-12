# Dependency refresh assessment — 2026-11-12 (SRT 0.3.2)

Status: candidates selected by [ADR-0010](../decisions/0010-srt-032-refresh.md); local build
and Telemetry suite passed; the Linux G1 and G4 runs at the new pins are **pending**. No gate
status changed.

## Selected sources

| Component | Previous | Selected | Immutable commit |
| --- | --- | --- | --- |
| Robotweax SRT | v0.3.1 `57fcf51a` | v0.3.2 (released 2026-11-05) | `e45d0edd346e5c427d85e4c3b1ac605c81a23397` |
| Robotweax SRT Telemetry | `1b12f8d7` | main, 2026-10-30 | `7a6b8eff65c686ccafa36a0adace148a8b87d3ca` |
| FIPS | v0.5.3 | unchanged (still the latest release) | `f4a5b4a8e61e340e6be7551608109a5c399f8353` |

The G1, healthy G4 and faulted-diamond workflows and the runner source guards agree with
`dependency-pins/baselines.json`. The eight FIPS G2 workflows do not reference SRT and are
unchanged. The CI toolchain pins from ADR-0007 are unchanged.

## Upstream deltas examined

- **SRT 0.3.1 → 0.3.2** (69 commits): ABI line 0.3 and SRT API 1.5.7 retained. The exported-symbol
  lists `cmake/abi/robotweax-srt-0.3.1.txt` and `-0.3.2.txt` are identical (85 exports). `srt.h`
  gains option values `0x01000010` to `0x01000017`, `ROBOTWEAX_SRT_GTYPE_MULTICAST` and
  `ROBOTWEAX_SRT_MCAST_STATS_V1`; nothing existing changed. New features (experimental multicast
  dispatch, ARQ-first FEC, tail probe) are opt-in and not enabled by Fabric. Two changes apply to
  every connection: TSBPD drift correction uses valid measured RTT only, and listeners reserve
  accept capacity before provisional allocation.
- **SRT Telemetry `1b12f8d7` → `7a6b8eff`** (18 commits, 2026-10-28 to 2026-10-30): delta engine
  moved onto a shared counter kernel (`sdk/src/delta_engine.cpp` −283 lines, with a counter-trace
  baseline test); additive connection-identity and observer fields in the JSON snapshot and HTTP
  history; a recording write fails when its directory sync fails; experimental remote numeric
  input. No file of the incident peer changed; under `adapters/public_srt` only the embedding
  library and its test did. The suite grows from 76 to 79 tests.
- Telemetry has no commit after the SRT 0.3.2 release, so upstream has not qualified this
  combination. The local build below is the first check of it.

## Local verification (Linux aarch64 container, 2026-11-12)

Ubuntu 24.04 container on an Apple-silicon host, with the workflow's package set and CMake
options: GCC 13.3.0, CMake 3.28.3, OpenSSL 3.0.13. This is not the CI architecture (x86-64).

| Local check | Outcome |
| --- | --- |
| Fabric unit/contract/validation (`make check`, macOS, Python 3.14) | passed (163 tests); every bundle at the old pins validates as digest-locked history |
| SRT v0.3.2 shared build | passed (`librobotweax-srt.so.0.3.2`) |
| Telemetry `7a6b8eff` build against v0.3.2 | passed |
| Telemetry `7a6b8eff` CTest suite | 79 tests: 75 passed, 4 skipped, 0 failed; `public_srt_fault_lab` passed |
| Telemetry `1b12f8d7` (old pin) against v0.3.2, for comparison | 76 tests: 72 passed, 4 skipped, 0 failed |
| Incident peer `--help` sentinels at `7a6b8eff` | `--bind-address IP`, `--message-bytes 1..1316`, `--media-udp-input`, `--media-udp-output`, `--peer-idle-timeout-ms` present |

The four skipped tests are the same in both revisions (`standby_schema_test`, `peer_schema_test`,
`recording_schema_test`, `remote_draft_schema`); the reason was not investigated. The workflows
install the same packages, so the same skips are expected there.

## Linux qualification

| Scenario | Run | Outcome |
| --- | --- | --- |
| G1 direct-SRT baseline | pending | — |
| Healthy SRT over FIPS (G4 live capture) | pending | — |
| Faulted diamond, unchanged ADR-0009 profile at the new pins | pending | — |

FIPS-only G2 scenarios are not rerun: FIPS is unchanged.

## Limits

Local builds establish compile and Telemetry-suite compatibility on aarch64 only. No Fabric
experiment has run at the new pins, so there is no retained evidence for them yet. The bundles
at SRT v0.3.1 and Telemetry `1b12f8d7` remain evidence only for those revisions. The TSBPD
drift change and the delta-engine refactor are candidate explanations for any difference
between a 0.3.1 run and a 0.3.2 run and must be observed, not assumed. No gate status changes.
