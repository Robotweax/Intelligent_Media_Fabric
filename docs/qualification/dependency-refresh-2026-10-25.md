# Dependency refresh assessment — 2026-10-25 (SRT 0.3.1)

Status: candidates selected by [ADR-0008](../decisions/0008-srt-031-refresh.md);
PENDING_STATUS

## Selected sources

| Component | Previous | Selected | Immutable commit |
| --- | --- | --- | --- |
| Robotweax SRT | v0.3.0 `4ae6330d` | v0.3.1 (tagged 2026-10-25) | `57fcf51a31ec2eecf4189d63c2f998ff1e8daaa1` |
| Robotweax SRT Telemetry | `24475483` | main, 2026-10-25 | `1a018dfdc89a964b03159aebc155d39bca524384` |
| FIPS | v0.5.3 | unchanged | `f4a5b4a8e61e340e6be7551608109a5c399f8353` |

The G4 and G1 workflows and the runner source guards agree with `dependency-pins/baselines.json`.
The eight FIPS G2 workflows do not reference SRT and are unchanged. The CI toolchain pins from
ADR-0007 are unchanged.

## Upstream deltas examined

- **SRT 0.3.0 → 0.3.1**: ABI line 0.3 and SRT API 1.5.7 retained; 84 exports preserved plus one
  additive (`robotweax_srt_connect_group_acquire`). CONNECTED now published only after
  transport-runtime installation; bounded rejected-message lookup, linger ownership and
  payload-pool growth; named library workers; default-off compiled congestion-controller and
  packet-filter bindings (private interfaces, not enabled by Fabric); per-member
  `SRTO_GROUPMINSTABLETIMEO`. The incident peer's unchanged invocation continues to use the
  OpenSSL/AES-CTR default with no new options.
- **SRT Telemetry**: five commits. Recording schema `1alpha3` for the embedding library's
  paired-session export; the SDK `export_jsonl` used by the incident peer still writes
  `1alpha1`, so the Fabric adapter and golden case are unchanged. A documentation commit
  records that 0.3.1 leaves the statistics clock unchanged. The incident peer source is
  untouched since `24475483`.

## Local verification (Linux x86_64, this workspace)

| Local check | Outcome |
| --- | --- |
| Fabric unit/contract/validation | passed (146 tests); both 0.3.0 bundles validate as digest-locked history |
| SRT v0.3.1 shared build | PENDING_BUILD |
| Telemetry `1a018dfd` build against v0.3.1 (ABI 0.3) | PENDING_BUILD |
| Telemetry CTest suite | PENDING_CTEST |

## Linux qualification

PENDING_WORKFLOWS

## Limits

Local builds establish compile and adapter-suite compatibility only. The 0.3.0 G4 and G1
bundles remain evidence only for 0.3.0; nothing here reruns FIPS-only G2 evidence. The CONNECTED
timing change is a candidate explanation for any difference in the first sample's counters
between the 0.3.0 and 0.3.1 runs and must be observed, not assumed. No gate status changes.
