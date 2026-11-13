# ADR-0013: Select SRT Telemetry `d03ca452` (incident-peer group mode)

- Status: accepted
- Date: 2026-11-13
- Supersedes ADR-0010 for the SRT Telemetry selection only. The SRT v0.3.2, FIPS v0.5.3 and toolchain pins, the evidence policy and ADR-0009's experiment decisions are retained.

## Decision

Pin SRT Telemetry main at `d03ca4527b005be0cfbe542ddaac6c0ede5e7955` (2026-11-13) for new
Fabric experiments. Robotweax SRT stays at v0.3.2 `e45d0edd` and FIPS at v0.5.3 `f4a5b4a8`.

It is a **requalification candidate**. Every retained bundle at Telemetry `7a6b8eff` stays
evidence only for that revision and is now digest-locked: the 2026-11-12 G1 run, the
2026-11-12 healthy G4 pilot and all twenty faulted-diamond bundles of 2026-11-12 and
2026-11-13 (the SRT 0.3.2 repeat, the default-peer-idle, reconnect and blackhole variants and
their same-revision baselines). A new run cannot present `7a6b8eff` as the active pin.

## Why this revision

It is two commits after `7a6b8eff`.
[Robotweax/srt_telemetry#75](https://github.com/Robotweax/srt_telemetry/pull/75) (`21dc05b9`)
gives the incident peer a connection-group mode, and
[#76](https://github.com/Robotweax/srt_telemetry/pull/76) (`d03ca452`) fixes a port race in
two of its tests, described below. The
[SRT-group comparison](../qualification/srt-group-comparison-design-2026-11-13.md) that
[ADR-0012](0012-interruption-budget.md) makes the next experiment cannot run without it.

What #75 changes, read from its diff:
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

## The first candidate, `21dc05b9`, and why it was replaced

This ADR first selected `21dc05b9`. Its hosted runs on 2026-11-13 are recorded here and not
retained:

- G1 run 43395352469 and the healthy G4 pilot 43395349816 passed.
- Faulted-diamond run 43395352315: seven of eight jobs passed on the first attempt. The job
  `fast-detection`, `default`, `coordinator-restart` failed before its experiment started, in
  the pinned Telemetry suite: the new incident-peer group test failed after 0.4 s with
  `media relay UDP input bind 127.0.0.1:58051`. A second attempt of that job passed.

The failure was a defect in the test, not in the peer or in Fabric. The test probed a free
UDP port for the caller's media input and released it; the listener then received the same
port for SRT, and the caller's later bind was refused. #76 takes that port from below the
range the system allocates from, in the group test and in the media relay test, which had
the same latent race. It changes two test files and one handoff line.

Because every experiment job runs that suite, a pin with a test known to fail at random
would make later runs fail the same way. The pin moves to `d03ca452` before anything is
retained. The `21dc05b9` bundles are not retained: they would be historical at once, and the
same combinations run again at the selected revision.

## Outcome at `d03ca452`

Both points were shown on 2026-11-13 at Fabric revision `859160d4`, all first attempts: G1 run
43402399643, healthy pilot 43402398402 and faulted-diamond run 43402399663 passed, each job
with the 82-test Telemetry suite passing and nothing skipped. The ten bundles are retained
and tabulated beside the `7a6b8eff` results in the
[requalification record](../qualification/telemetry-d03ca452-requalification-2026-11-13.md).
The existing experiments behave as before within the recorded run-to-run spread.

## Known limits

- At the time of this ADR the group mode had been built and run only against Robotweax SRT
  v0.3.2 (Linux aarch64 locally, x86_64 in the hosted runs above), plus Telemetry's automatic
  Linux smoke job. Telemetry's full provider matrix, including Haivision libsrt, had not run
  on either commit. Fabric uses Robotweax SRT only.
- The port race was never reproduced outside the one hosted job. The fix removes its cause
  by construction; no run demonstrates its absence.
- This ADR selects the revision. It does not predeclare the group comparison and changes no
  gate.
