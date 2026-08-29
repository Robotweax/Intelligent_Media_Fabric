# Contributing

This is a private Robotweax repository. Contribution rights are limited to explicitly authorized
contributors.

## Before changing code

1. Confirm that the work belongs to the currently authorized phase in `README.md`.
2. Link the change to a gate, experiment, issue, or Architecture Decision Record.
3. Do not introduce moving dependency references, vendored third-party code, or private SRT APIs.
4. Update machine-readable contracts before relying on a new field or status.
5. Identify whether the change creates security, privacy, wire, compatibility, or retention impact.

## Change requirements

- Keep commits focused and reviewable.
- Run `make check` before submitting a change.
- Add tests for executable behavior and negative cases.
- Record exact revisions, build profiles, topology, hardware, and fault plans in evidence.
- Treat unavailable measurements as unavailable; never synthesize zero or success.
- Keep secrets and customer media out of fixtures and logs.
- Mark harness-only output so it cannot be mistaken for product evidence.

## Decisions

Use an ADR when a change selects an architectural boundary, dependency integration mode, security
model, stable schema, fork policy, public contract, or product gate. ADRs live in `docs/decisions/`.

The contribution-signing and DCO policy is not yet selected. Until it is, repository owners must
approve every merge and preserve authorship metadata.

## Third-party changes

Prefer upstream contributions for generic FIPS capabilities. A Robotweax patch stack requires an
approved ADR covering its size, ownership, rebase cadence, security updates, and exit condition.
