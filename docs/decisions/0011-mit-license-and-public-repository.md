# ADR-0011: MIT license and public repository

- Status: accepted
- Date: 2026-11-13
- Closes the repository-licensing part of OD-12; the OEM model, contribution signing and CODEOWNERS stay open

## Decision

License this repository under the MIT License, copyright Robotweax GmbH and contributors, and
make it public. This is an explicit repository-owner decision of 2026-11-13, which
`LICENSE_POLICY.md` required together with this record.

## Scope

The license covers what the repository contains: the standard-library evidence harness, schemas,
scenarios, documentation, workflows and the retained evidence bundles.

It does not cover the components the harness builds and runs. None of them is vendored here
([ADR-0002](0002-external-pinned-dependencies.md)):

| Component | Visibility on 2026-11-13 | Effect |
| --- | --- | --- |
| Robotweax SRT | public, MIT | none |
| FIPS | public upstream | none |
| Robotweax SRT Telemetry | private | see below |
| SRT Knowledge Base (strategy source) | private | the strategy link in `docs/strategy/README.md` does not resolve for outside readers |

## Consequences

- The G1 and G4 experiment workflows check out SRT Telemetry with the repository secret
  `ROBOTWEAX_REPO_TOKEN`. GitHub does not pass secrets to pull requests from forks, so an
  outside contributor can run `make check` but cannot produce experiment evidence. Evidence
  runs stay with the repository owners until Telemetry is public or the workflows change.
- Retained bundles contain records produced by the private Telemetry incident peer, and the
  documentation describes its command protocol and recording format. Publishing them is part
  of this decision.
- The commit history, earlier pull requests and the logs and artifacts of earlier workflow
  runs become readable. A scan of the tree and history on 2026-11-13 found no credential, key
  or token; the token itself exists only as a repository secret.
- Nothing about gates, pins or evidence policy changes. The repository stays pre-alpha and
  makes no product, security, performance or continuity claim.
- The MIT license on this repository does not select a product, OEM or contribution-signing
  model. Those remain OD-12.
