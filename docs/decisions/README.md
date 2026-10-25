# Architecture Decision Records

ADRs use four states: `proposed`, `accepted`, `superseded`, and `rejected`. An accepted ADR records
the current engineering decision, not a public product promise.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-evidence-first-project-scope.md) | accepted | Begin with contracts and retained evidence |
| [0002](0002-external-pinned-dependencies.md) | accepted | Integrate external pinned dependencies first |
| [0003](0003-fips-phase1-baseline.md) | superseded | Historical FIPS v0.4.2 baseline; evidence remains revision-bound |
| [0004](0004-srt-telemetry-adapter-boundary.md) | accepted | Keep SRT semantics in SRT Telemetry and add only explicit Fabric context |
| [0005](0005-srt-fips-requalification.md) | superseded | Historical SRT main and FIPS v0.5.1 refresh |
| [0006](0006-srt-026-baseline.md) | superseded | Historical SRT v0.2.6 selection; its evidence policy is retained |
| [0007](0007-dependency-refresh-2026-10-22.md) | superseded | Historical SRT v0.3.0 and Telemetry `24475483` selection; FIPS v0.5.3, Actions pins and evidence policy retained |
| [0008](0008-srt-031-refresh.md) | accepted | Select SRT v0.3.1 and Telemetry `1a018dfd` as requalification candidates |

The next required ADRs cover the pilot workflow and budget, Robotweax SRT crypto profile,
conservative MTU/payload profile, device credentials, contribution signing, CODEOWNERS, and product
licensing.
