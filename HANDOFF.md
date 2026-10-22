# Agent handoff — Intelligent Media Fabric

Snapshot: 2026-10-22. This is an orientation file, not a substitute for the
current `main`, PR checks, ADRs or gate registry. Refresh remote state before
making a decision. The repository is private, proprietary and pre-alpha; no
product, security, performance or continuity claim is released.

## Start on a new machine

Use an authorized GitHub account with access to this repository and to the
private Robotweax SRT, SRT Telemetry and SRT Knowledge Base repositories. Do not
copy credentials from the old machine or put token values in this repository.
For the commands below, install Git, `make`, Python 3.11+ and the GitHub CLI
(`gh`), and authenticate `gh` with that account. Native local builds additionally
need a C++20 toolchain, CMake, Ninja and OpenSSL 3; the privileged FIPS/SRT
workflow is Linux-specific and provisions its pinned toolchain in CI.

```sh
git clone https://github.com/Robotweax/Intelligent_Media_Fabric.git
cd Intelligent_Media_Fabric
git fetch origin
git switch main
git pull --ff-only
git status --short --branch
gh pr list --state open
python3 --version  # Python 3.11 or newer
make check
```

`make check` compiles the Python lab, runs its unit/contract tests and validates
retained evidence. On a fresh checkout, `make smoke` additionally exercises only
the evidence harness and writes `artifacts/harness-smoke-result.json`; it does
**not** test SRT over FIPS. The smoke output is exclusive, so do not rerun it over
an existing artifact. The basic lab has no Python package dependency beyond the
standard library. Privileged network experiments require Linux, the pinned
native toolchains and the dedicated GitHub Actions workflows.

## What this project owns

Fabric is the authorization, observation, correlation and qualification layer.
Robotweax SRT owns media transport, reliability and timing; SRT Telemetry owns
SRT measurement semantics and quality flags; the external FIPS daemon owns the
secure mesh and exposes `fips0`. Initial integration uses public SRT C APIs and
ordinary IP sockets over `fips0`. Do not use private SRT objects, vendor FIPS,
or infer that FIPS link metrics are SRT loss metrics.

Read these before implementation:

1. [README](README.md) and [architecture](docs/architecture/overview.md) for scope and layer boundaries.
2. [Gate registry](docs/qualification/gate-registry.md) and [open decisions](docs/decisions/open-decisions.md) for current authorization.
3. [ADR index](docs/decisions/README.md), especially [ADR-0004](docs/decisions/0004-srt-telemetry-adapter-boundary.md), [ADR-0006](docs/decisions/0006-srt-026-baseline.md) and [ADR-0007](docs/decisions/0007-dependency-refresh-2026-10-22.md).
4. [Strategy pointer](docs/strategy/README.md) to the authoritative private Knowledge Base document. Do not maintain a divergent strategy copy here.
5. [Evidence lab](docs/qualification/evidence-lab.md) and [contribution rules](CONTRIBUTING.md) before changing schemas or experiments.

## Immutable dependency selection

The machine-readable source of truth is
[`dependency-pins/baselines.json`](dependency-pins/baselines.json); the runner and
workflows must agree with it. Do not substitute a moving `main` or a local build.

| Component | Selected revision | Role |
| --- | --- | --- |
| Robotweax SRT v0.2.9 | `a87779d9c3d831583d32b2f61cae5b81edb05537` | Public C API and `librobotweax-srt` media transport |
| Robotweax SRT Telemetry | `2447548388a47aaac647bb2eafdc4f9e962f0baa` | Public SRT adapter and source measurements |
| FIPS v0.5.3 | `f4a5b4a8e61e340e6be7551608109a5c399f8353` | External daemon and `fips0` overlay |

The historical FIPS development candidate in the manifest is research-only.
Toolchain and action pins are in
[`dependency-pins/toolchain.json`](dependency-pins/toolchain.json) and the
workflows. The G4 workflow needs the repository secret `ROBOTWEAX_REPO_TOKEN`
with read-only Contents access to the two private SRT repositories; the secret
value is neither in source nor in retained evidence. Do not expose or broaden it.

## Evidence and its limits

- [2026-10-22 dependency refresh](docs/qualification/dependency-refresh-2026-10-22.md):
  ADR-0007 moved the pins to SRT v0.2.9, Telemetry `24475483` and FIPS v0.5.3.
  Local Fabric checks and the SRT/Telemetry build passed; the eight G2
  workflows and a new healthy G4 capture on the new pins are the next required
  evidence. Nothing below is evidence for the new pins.
- [SRT v0.2.6 healthy pilot](docs/qualification/g4-live-capture-srt-026-2026-09-27.md):
  [Linux run 36309262514](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/36309262514)
  built the pinned SRT/Telemetry/FIPS combination, passed the Telemetry suite,
  delivered 240/240 application messages exactly, and retained a validated
  [13-file bundle](qualification/retained-bundles/2026-09-27-g4-srt-over-fips-live-36309262514/result.json).
  It exercised one healthy two-node path, not loss, failover, independent media
  decode, performance comparison or a G3/G4 gate pass.
- [Previous healthy pilot](docs/qualification/g4-live-capture-2026-09-23.md)
  used SRT 0.2.4. Its result is intentionally historical and digest-locked; do
  not relabel or rewrite it as 0.2.6 evidence.
- [FIPS v0.5.1 alternate-route evidence](docs/qualification/fips-g2-linux-alternate-route-v0.5.1-2026-09-23.md)
  observed automatic reparenting, not hitless SRT/media recovery. FIPS-only G2
  remains in progress; the reactive-MTU capability gap is not yet resolved.
- [Framehash harness](docs/qualification/g4-faulted-diamond-experiment-plan-2026-09-23.md)
  validates bounded FFmpeg output comparison, but has not observed a faulted
  network path or independent downstream media in the same experiment.

The [gate registry](docs/qualification/gate-registry.md) is authoritative: G1
and G3 have not started, G2 and G4 are in progress, and G5–G9 have not started.
Do not promote a gate from green CI or a healthy pilot alone. Keep failed runs
and unavailable measurements explicit; preserve source commits, binary hashes,
clock domains, route epochs and downstream identity checks.

## Bounded next work

1. Complete the ADR-0007 requalification: eight G2 workflows on FIPS v0.5.3,
   then a healthy G4 capture on SRT v0.2.9; retain results and failures as-is.
2. Establish a repeated direct-SRT control (G1), then compare direct SRT with
   SRT-over-FIPS at the same 0.2.9 pin for G3. Freeze the workload and budgets
   before claiming throughput, CPU, RSS, wire or timing effects. OD-01, OD-03,
   OD-04 and OD-14 remain prerequisites for a G3 decision.
3. Implement the separate [faulted-diamond G4 plan](docs/qualification/g4-faulted-diamond-experiment-plan-2026-09-23.md):
   four-node Linux runner, observed route-epoch transition, negative tests,
   fail-closed result schema and an independent downstream decoder/collector.
   Do not retrofit the healthy two-node workflow or claim causality from time
   ordering alone.
4. Reassess the [reactive-MTU gap](docs/qualification/fips-g2-reactive-mtu-gap-2026-08-30.md)
   on the pinned FIPS revision before using such evidence for G6. Do not enable
   production route mutation or a FIPS fork without a separate approved ADR.

Before any PR or merge, inspect the current diff, relevant owner decisions,
required checks and remote base. At handoff preparation there were no existing
open PRs; always rerun `gh pr list --state open` because this statement ages.
