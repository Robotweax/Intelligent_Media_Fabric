# Agent handoff — Intelligent Media Fabric

Snapshot: 2026-11-12. This is an orientation file, not a substitute for the
current `main`, PR checks, ADRs or gate registry. Refresh remote state before
making a decision. The repository is public under the MIT license
([ADR-0011](docs/decisions/0011-mit-license-and-public-repository.md)) and pre-alpha; no
product, security, performance or continuity claim is released.

## Start on a new machine

Use an authorized GitHub account with access to this repository and to the
private SRT Knowledge Base repository. Robotweax SRT and SRT Telemetry are public (Telemetry since
2026-11-13). Do not
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
3. [ADR index](docs/decisions/README.md), especially [ADR-0004](docs/decisions/0004-srt-telemetry-adapter-boundary.md), [ADR-0009](docs/decisions/0009-faulted-diamond-media-observation.md) and [ADR-0010](docs/decisions/0010-srt-032-refresh.md).
4. [Strategy pointer](docs/strategy/README.md) to the authoritative private Knowledge Base document. Do not maintain a divergent strategy copy here.
5. [Evidence lab](docs/qualification/evidence-lab.md) and [contribution rules](CONTRIBUTING.md) before changing schemas or experiments.

## Immutable dependency selection

The machine-readable source of truth is
[`dependency-pins/baselines.json`](dependency-pins/baselines.json); the runner and
workflows must agree with it. Do not substitute a moving `main` or a local build.

| Component | Selected revision | Role |
| --- | --- | --- |
| Robotweax SRT v0.3.2 | `e45d0edd346e5c427d85e4c3b1ac605c81a23397` | Public C API and `librobotweax-srt` media transport |
| Robotweax SRT Telemetry | `d03ca4527b005be0cfbe542ddaac6c0ede5e7955` | Public SRT adapter and source measurements; incident peer with group mode ([ADR-0013](docs/decisions/0013-telemetry-group-mode-pin.md)) |
| FIPS v0.5.3 | `f4a5b4a8e61e340e6be7551608109a5c399f8353` | External daemon and `fips0` overlay |

The historical FIPS development candidate in the manifest is research-only.
Toolchain and action pins are in
[`dependency-pins/toolchain.json`](dependency-pins/toolchain.json) and the
workflows. The G4 workflow needs the repository secret `ROBOTWEAX_REPO_TOKEN`
with read-only Contents access to SRT Telemetry and SRT (both public now, but the workflows
still require the token); the secret
value is neither in source nor in retained evidence. Do not expose or broaden it.

## Evidence and its limits

- [2026-11-14 SRT group over two FIPS overlays, stage 2](docs/qualification/g5-srt-group-over-fips-2026-11-14.md):
  run 43574559867 at `915c8a55`, first attempts, under the
  [predeclared plan](docs/qualification/g5-srt-group-over-fips-plan-2026-11-14.md). Two separate FIPS
  overlays on the diamond, two FIPS daemons per endpoint, one group member per overlay; the transit of
  one overlay was blackholed. Broadcast and Backup both delivered every datagram and frame with no
  downstream gap: the first retained stream **over FIPS** that is hitless by ADR-0012's definition.
  FIPS reported the lost link after 31 to 32 s; the stream had continued on the other member. **Limit:**
  FIPS v0.5.3 does not support two daemons in one namespace, so the lab removes the `fd00::/8` route
  FIPS installs and adds host routes. The result does not show that FIPS supports this. G5 stays
  `in-progress`.
- [2026-11-14 SRT-group comparison, stage 1](docs/qualification/g5-srt-group-comparison-2026-11-14.md):
  run 43567524615 at `79d825e9`, first attempts, under the
  [predeclared plan](docs/qualification/g5-srt-group-comparison-plan-2026-11-13.md). One SRT group with
  two members over separate transits of the diamond, on routed IPv6 **without FIPS**; the transit
  carrying the stream was blackholed. Broadcast and Backup both delivered 17,729 of 17,729 datagrams
  and 4,000 of 4,000 frames with no downstream gap: the first retained runs that are hitless by
  ADR-0012's definition. Backup sent about 5 s of the stream on both members until the dead member
  was removed. One run per mode; it does not show a group over FIPS. G5 is `in-progress`.
- [2026-11-13 Telemetry `d03ca452`](docs/qualification/telemetry-d03ca452-requalification-2026-11-13.md):
  ADR-0013 moved Telemetry to `d03ca452` (incident-peer group mode and its test fix; SRT and FIPS
  unchanged). Retained at the new pin, all first attempts at `859160d4`: G1 run 43402399643 (3/3
  exact), healthy pilot 43402398402 (240/240) and all eight faulted-diamond combinations (run
  43402399663: gaps 5.2 s and 32.2 s with the session kept, 6.3 s and 32.5 s with a coordinator
  restart). They reproduce the `7a6b8eff` behaviour within the run-to-run spread; nothing is
  attributed to the pin change. No retained run uses the group mode yet. Everything below is
  digest-locked history for its own revisions.
- [2026-11-12 SRT 0.3.2 refresh](docs/qualification/dependency-refresh-2026-11-12.md):
  ADR-0010 moved SRT to v0.3.2 and Telemetry to `7a6b8eff` (same ABI line 0.3, FIPS unchanged).
  Retained at the new pins, all first attempts at `c5052b1e`: the
  [G1 run](docs/qualification/g1-direct-srt-baseline-2026-11-12.md) (run 43244304465, 3/3 exact), the
  [healthy pilot](docs/qualification/g4-live-capture-srt-032-2026-11-12.md) (run 43244297357, 240/240) and
  [both faulted-diamond profiles](docs/qualification/g4-faulted-diamond-srt-032-2026-11-12.md)
  (run 43244304348: gap 32.2 s with link-dead 30 s, 4.2 s with link-dead 3 s). They reproduce the
  0.3.1 behaviour within the run-to-run spread of about 1 s; no difference is attributed to the
  pin change.
- [2026-10-28 faulted diamond](docs/qualification/g4-faulted-diamond-2026-10-28.md):
  ADR-0009 moved Telemetry to `1b12f8d7` (incident-peer media relay). Run 40743995191
  killed the active transit; FIPS reparented after about 31 s, one SRT session (peer idle
  60 s) spanned both route epochs, and an independent FFmpeg decode showed 782 missing and
  19 concealed frames; a [repeat](docs/qualification/g4-faulted-diamond-repeat-2026-10-28.md)
  (run 40748574042) reproduced it. A predeclared
  [fast-detection variant](docs/qualification/g4-faulted-diamond-fast-detection-2026-10-30.md)
  (FIPS link-dead 3 s, run 41022516133) cut the gap from 31.2 s to 5.2 s against a
  same-revision baseline. All are ordering-only, not causal or hitless, and does not pass G4. The
  [healthy pilot](docs/qualification/g4-live-capture-telemetry-1b12f8d7-2026-10-28.md) (run 40745656211)
  and [G1 run](docs/qualification/g1-direct-srt-baseline-2026-10-28.md) (run 40743995008) at the
  new pin are retained; the 2026-10-25 bundles are digest-locked history.
- [2026-10-25 SRT 0.3.1 refresh](docs/qualification/dependency-refresh-2026-10-25.md):
  ADR-0008 moved SRT to v0.3.1 and Telemetry to `1a018dfd` (same ABI line 0.3,
  FIPS unchanged). The [v0.3.1 pilot](docs/qualification/g4-live-capture-srt-031-2026-10-25.md)
  (run 40190670233, 240/240) and [v0.3.1 G1 run](docs/qualification/g1-direct-srt-baseline-2026-10-25.md)
  (run 40189973066, 3/3 exact) are retained; a first G4 attempt failed in the
  upstream Telemetry fault-lab gate before capture and is recorded, not hidden.
  The 0.3.0 bundles below are digest-locked history, not evidence for 0.3.1.
- [2026-10-22 dependency refresh](docs/qualification/dependency-refresh-2026-10-22.md):
  ADR-0007 moved the pins to SRT v0.3.0, Telemetry `24475483` and FIPS v0.5.3.
  All eight G2 scenarios passed on v0.5.3 and are retained; the
  [v0.5.3 alternate-route run](docs/qualification/fips-g2-linux-alternate-route-v0.5.3-2026-10-22.md)
  preserved the FSP session and recovered payload in 39.3 s (v0.5.1: 92.9 s
  with a session restart). The
  [healthy SRT v0.3.0 pilot](docs/qualification/g4-live-capture-srt-030-2026-10-22.md)
  (run 39795866081) delivered 240/240 messages and is retained. Nothing below
  is evidence for the new pins; nothing above changes a gate.
- [G1 direct-SRT baseline](docs/qualification/g1-direct-srt-baseline-2026-10-22.md):
  run 39806840201, three exact repetitions over a plain veth with zero loss; timing, CPU
  and RSS recorded without thresholds. G1 is `in-progress`, not passed.
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
  validates bounded FFmpeg output comparison; the faulted-diamond run above is its
  first use on a faulted network path.

The [gate registry](docs/qualification/gate-registry.md) is authoritative: G1,
G2, G4 and G5 are in progress, G3 has not started, and G6–G9 have not started.
Do not promote a gate from green CI or a healthy pilot alone. Keep failed runs
and unavailable measurements explicit; preserve source commits, binary hashes,
clock domains, route epochs and downstream identity checks.

## Bounded next work

1. Repeat the direct-SRT control (G1) — the
   [first run](docs/qualification/g1-direct-srt-baseline-2026-10-22.md) is retained — then
   compare direct SRT with SRT-over-FIPS at the same 0.3.2 pin for G3. Freeze the workload and budgets
   before claiming throughput, CPU, RSS, wire or timing effects. OD-01, OD-03,
   OD-04 and OD-14 remain prerequisites for a G3 decision.
2. Build on the [first faulted-diamond run](docs/qualification/g4-faulted-diamond-2026-10-28.md):
   it is repeated, has a fast-FIPS-detection variant and a
   [default-peer-idle variant](docs/qualification/g4-faulted-diamond-default-peer-idle-2026-11-12.md)
   (run 43255432045: with SRT's 5 s default the session ended under both FIPS timer profiles; the incident
   peer does not reconnect) and a
   [coordinator-driven reconnect variant](docs/qualification/g4-faulted-diamond-reconnect-2026-11-12.md)
   (run 43280995407: restarting the session from the test coordinator closed the gap at 6.4 s with
   link-dead 3 s and 32.5 s with link-dead 30 s; about 1 s of that is the coordinator's own detection
   delay) and a
   [silent transit blackhole variant](docs/qualification/g4-faulted-diamond-blackhole-2026-11-13.md)
   (run 43381166414: indistinguishable from the kill under both timer profiles). [ADR-0012](docs/decisions/0012-interruption-budget.md)
   now sets the budget for one transit failure: hitless as the target, 6 s with the session kept as the
   single-path floor. No retained single-session run meets the target, so the next experiment is the
   SRT-group comparison OD-15 asks for. Its stage 1
   ([record](docs/qualification/g5-srt-group-comparison-2026-11-14.md)) is retained: groups on routed IPv6
   without FIPS were hitless in both modes. Open after it: whether stage 1 alone may close OD-15, or
   stage 2 is required. Stage 2 (a group over two FIPS overlays,
   [record](docs/qualification/g5-srt-group-over-fips-2026-11-14.md)) is retained and was hitless in both
   modes too. It depends on a lab routing workaround, because FIPS v0.5.3 does not support two daemons
   in one namespace. Open after it, all owner decisions: whether these two stages close OD-15 and
   OD-11; whether to raise two identities or two paths per host with FIPS upstream (no fork without an
   ADR); and whether G5 needs repeats or further fault classes before it can pass. Other open variants: a peer that reconnects by itself (also a Telemetry
   change), partial or one-way loss. Each variant is a new predeclaration. Do not
   claim causality or a first divergent layer from time ordering alone.
3. Reassess the [reactive-MTU gap](docs/qualification/fips-g2-reactive-mtu-gap-2026-08-30.md)
   on the pinned FIPS revision before using such evidence for G6. Do not enable
   production route mutation or a FIPS fork without a separate approved ADR.

Before any PR or merge, inspect the current diff, relevant owner decisions,
required checks and remote base. At handoff preparation there were no existing
open PRs; always rerun `gh pr list --state open` because this statement ages.
