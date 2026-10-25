# Healthy SRT v0.3.1 over FIPS v0.5.3 live capture — 2026-10-25

- Workflow: [G4 SRT over FIPS Live Capture, run 40190670233](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40190670233)
- Fabric runner revision: `eeca6b40` (branch `dev/srt-031-refresh`)
- SRT v0.3.1: `57fcf51a31ec2eecf4189d63c2f998ff1e8daaa1` (shared-library ABI line 0.3)
- FIPS v0.5.3: `f4a5b4a8e61e340e6be7551608109a5c399f8353`
- SRT Telemetry: `1a018dfdc89a964b03159aebc155d39bca524384`
- Platform: Linux x86_64, kernel `6.17.0-1022-azure`; two isolated namespaces
- Path: Robotweax SRT over IPv6 `fips0`, direct IPv4 UDP underlay

The workflow built the pinned sources, built the Telemetry adapter against the SRT v0.3.1
headers and `librobotweax-srt.so`, passed the complete pinned Telemetry CTest suite (74 tests
on the runner, 73 locally; the runner's workflow installs `libdbus-1-dev`, which enables one
more) before the live capture, and retained the
[13-file evidence bundle](../../qualification/retained-bundles/2026-10-25-g4-srt-over-fips-live-40190670233/result.json).
The result manifest SHA-256 is
`82c1107b4c7bb9a31aee2b1a87294b3e32371785e5f0567219eea054a480e16c`. Repository validation
checks its file inventory, source-to-adapter replay, ordering assessments, declared media
observation and that the source recordings identify provider `0.3.1` at the pinned revision.

The healthy experiment passed: all 240 application messages of 1024 bytes were delivered
exactly. It recorded 14 SRT samples per endpoint, 14 FIPS observations, valid same-host
temporal ordering (`srt-before-peer` for both SRT/FIPS and SRT/media) and complete cleanup.
This confirms that SRT v0.3.1 and Telemetry `1a018dfd` work together over the pinned FIPS
v0.5.3 data plane in this bounded setup, and that the incident peer's `1alpha1` recordings
still satisfy the Fabric adapter contract after the Telemetry `1alpha3` addition.

## First attempt

The first dispatch on this branch,
[run 40189210887](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40189210887),
did not reach the capture: the workflow's gate, the pinned Telemetry suite on the runner,
failed `public_srt_fault_lab` with the receiver-advice criterion at 7/8. In the
`receiver_stall` scenario the receiver detected the fault at 2.1 s with the correct knob, but
18 of 77 later advice reads (from 14.2 s) returned no advice. The sender criterion was 10/10
and all 14 scenario verdicts were correct. The same suite passed 73/73 locally and 74/74 on
the rerun. No Fabric result exists for that attempt because the harness never started; it is
recorded here as a failed attempt and is not evidence about SRT over FIPS. The health-engine
advice-persistence timing belongs to SRT Telemetry and is noted for upstream, not changed
here.

## Limits

No loss, delay, UDP backpressure, outage, route transition or independent video decode was
exercised. The receiver is provider-linked. This result cannot establish a throughput, CPU,
RSS or continuity effect of SRT 0.3.1 over 0.3.0; it does not identify a first divergent
layer or fault domain. The bundle records `G3: not-passed` and `G4: not-passed`. The faulted
and comparative experiments required by [ADR-0008](../decisions/0008-srt-031-refresh.md) and
the [gate registry](gate-registry.md) remain outstanding.
