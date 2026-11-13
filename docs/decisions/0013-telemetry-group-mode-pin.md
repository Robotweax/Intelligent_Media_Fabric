# ADR-0013: Select SRT Telemetry `21dc05b9` (incident-peer group mode)

- Status: accepted
- Date: 2026-11-13
- Supersedes ADR-0010 for the SRT Telemetry selection only. The SRT v0.3.2, FIPS v0.5.3 and toolchain pins, the evidence policy and ADR-0009's experiment decisions are retained.

## Decision

Pin SRT Telemetry main at `21dc05b957855ddda270ee7fca7ab28c0d0781fe` (2026-11-13) for new
Fabric experiments. Robotweax SRT stays at v0.3.2 `e45d0edd` and FIPS at v0.5.3 `f4a5b4a8`.

It is a **requalification candidate**. Every retained bundle at Telemetry `7a6b8eff` stays
evidence only for that revision and is now digest-locked: the 2026-11-12 G1 run, the
2026-11-12 healthy G4 pilot and all twenty faulted-diamond bundles of 2026-11-12 and
2026-11-13 (the SRT 0.3.2 repeat, the default-peer-idle, reconnect and blackhole variants and
their same-revision baselines). A new run cannot present `7a6b8eff` as the active pin.

## Why this revision

It is one commit after `7a6b8eff`:
[Robotweax/srt_telemetry#75](https://github.com/Robotweax/srt_telemetry/pull/75), which gives
the incident peer a connection-group mode. The
[SRT-group comparison](../qualification/srt-group-comparison-design-2026-11-13.md) that
[ADR-0012](0012-interruption-budget.md) makes the next experiment cannot run without it.

What the commit changes, read from its diff:
- only the incident peer (a test host), one new Python test, one documentation section and
  the test registration. The Telemetry library, its C ABI, the public SRT adapter and the
  `1alpha1` recording format are untouched.
- without `--group` the peer's command protocol and output are unchanged, except the wording
  of one misuse error that Fabric does not read.
- in group mode each member is recorded to its own `1alpha1` file, so Fabric's adapter
  ([ADR-0004](0004-srt-telemetry-adapter-boundary.md)) needs no schema change.

## What has to be shown at the new pin

The peer binary changes, so its digest in every new result changes. The existing experiments
do not use the group mode; they are expected to behave as before, and that is to be
observed, not assumed:

1. the pinned Telemetry CTest suite passes in every experiment job (it gains the group test);
2. the G1 control, the healthy G4 pilot and the eight faulted-diamond combinations run at
   the new pin and are retained whatever they show, beside the `7a6b8eff` results, ungraded.

## Known limits

- At the time of this ADR the group mode had been built and run only against Robotweax SRT
  v0.3.2 on Linux aarch64, plus Telemetry's automatic Linux smoke job. Telemetry's full
  provider matrix, including Haivision libsrt, had not run on this commit. Fabric uses
  Robotweax SRT only.
- This ADR selects the revision. It does not predeclare the group comparison and changes no
  gate.
