# Robotweax Intelligent Media Fabric

Robotweax Intelligent Media Fabric is an evidence-gated research and product project for
professional contribution-media networking. It investigates how Robotweax SRT can use FIPS
(Free Internetworking Peering System) for identity, discovery, NAT traversal, secure mesh
connectivity, and network telemetry without weakening SRT's reliability and timing contracts.

This repository is private and pre-alpha. It does not define a released product, API, ABI, wire
protocol, security property, performance target, SLA, or delivery commitment.

## Current authorization

The repository is authorized for Phase 0A and Phase 0B work:

- contract, architecture, and threat-model definition;
- immutable dependency and toolchain pins;
- a reproducible evidence-lab foundation;
- direct-SRT control measurements;
- FIPS connectivity assessment; and
- machine-readable qualification results.

It is not yet authorized for a long-lived FIPS fork, generic multipath, production route mutation,
a global relay service, dynamic encoder control, or ML-based decisions.

## Layer ownership

```text
FIPS
    identity + discovery + NAT + secure mesh + telemetry

Robotweax SRT
    media reliability + timing + FEC + connection groups

Robotweax SRT Telemetry
    SRT field semantics + deltas + quality + raw evidence

Robotweax Intelligent Media Fabric
    authorization + correlation + path intelligence
    + resilience policy + operations
```

The first technical question is deliberately narrower than the eventual product vision:

> Can a realistic Robotweax SRT stream run transparently over a pinned FIPS data plane within a
> predeclared correctness, MTU, CPU, timing, and continuity budget?

## Repository map

```text
dependency-pins/       Immutable external baselines
docs/                  Architecture, decisions, security, protocols, and qualification
qualification/         Experiment scenarios, golden contract cases, and retained results
schema/                Telemetry, policy, and qualification contracts
src/rimf_lab/           Standard-library evidence harness
tests/                 Harness and contract tests
```

Start with [the documentation index](docs/README.md), the
[architecture overview](docs/architecture/overview.md), and the
[gate registry](docs/qualification/gate-registry.md).
For continuation on another machine, start with the [agent handoff](HANDOFF.md).

## Local checks

New experiments pin SRT v0.3.1, SRT Telemetry `1b12f8d7` and FIPS v0.5.3 as
**requalification candidates**, not as already qualified releases. See
[ADR-0009](docs/decisions/0009-faulted-diamond-media-observation.md), [ADR-0008](docs/decisions/0008-srt-031-refresh.md), [ADR-0007](docs/decisions/0007-dependency-refresh-2026-10-22.md)
and the [refresh assessment](docs/qualification/dependency-refresh-2026-10-22.md).

Python 3.11 or newer is the only requirement for the initial harness.

```bash
make check
make smoke
```

`make smoke` qualifies only the evidence harness. It is not SRT-over-FIPS evidence. Real
experiments must use pinned binaries, approved scenarios, and the result contract.

The manually dispatched `G4 SRT over FIPS Live Capture` workflow is the first privileged
cross-layer pilot. Even a successful run remains experiment evidence and explicitly leaves G3 and
G4 unpassed until faulted route transitions and independent downstream media validation exist.

## Authoritative context

The internal strategy is maintained in the private SRT Knowledge Base at commit
[`b6276d5fdef7afa4ec2d5db5b4c6b64d016a88a6`](https://github.com/Robotweax/srt_knowledge_base/blob/b6276d5fdef7afa4ec2d5db5b4c6b64d016a88a6/docs/project/robotweax-intelligent-media-fabric-strategy.md).

Public Robotweax SRT contracts remain authoritative in the Robotweax SRT repository. This project
must consume public, installed, versioned interfaces rather than private SRT implementation details.

## Licensing and contributions

No public or open-source license has been granted for this repository. See
[LICENSE_POLICY.md](LICENSE_POLICY.md), [THIRD_PARTY.md](THIRD_PARTY.md), and
[CONTRIBUTING.md](CONTRIBUTING.md).
