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
| [0006](0006-srt-026-baseline.md) | accepted | Select SRT v0.2.6 for new Fabric runs; preserve FIPS and Telemetry pins |

The next required ADRs cover the pilot workflow and budget, Robotweax SRT crypto profile,
conservative MTU/payload profile, device credentials, contribution signing, CODEOWNERS, and product
licensing.
