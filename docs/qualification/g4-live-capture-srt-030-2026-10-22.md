# Healthy SRT v0.3.0 over FIPS v0.5.3 live capture — 2026-10-22

- Workflow: [G4 SRT over FIPS Live Capture, run 39795866081](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/39795866081)
- Fabric runner revision: `c093d9b2` (branch `dev/dependency-refresh-2026-10-22`)
- SRT v0.3.0: `4ae6330d62f2b5030d96964bf3500283f32dd39c` (shared-library ABI line 0.3)
- FIPS v0.5.3: `f4a5b4a8e61e340e6be7551608109a5c399f8353`
- SRT Telemetry: `2447548388a47aaac647bb2eafdc4f9e962f0baa`
- Platform: Linux x86_64, kernel `6.17.0-1022-azure`, Python 3.12.3; two isolated namespaces
- Path: Robotweax SRT over IPv6 `fips0`, direct IPv4 UDP underlay

The workflow built the pinned sources with the new Actions pins, built the
Telemetry adapter against the SRT v0.3.0 headers and `librobotweax-srt.so`, ran
the complete pinned Telemetry CTest suite (72 tests at this revision) before the
live capture, and retained the
[13-file evidence bundle](../../qualification/retained-bundles/2026-10-22-g4-srt-over-fips-live-39795866081/result.json).
The result manifest SHA-256 is
`5d7c5188946ce6631455894c56e6f2a5ac3b19aa7c469c5b60b6f01e2c43b547`.
Repository validation checks its file inventory, source-to-adapter replay,
ordering assessments, declared media observation and that the source
recordings identify provider `0.3.0` at the pinned revision.

The healthy experiment passed: all 240 application messages of 1024 bytes were
delivered exactly. It recorded 14 SRT samples per endpoint, 14 FIPS observations,
valid same-host temporal ordering (`srt-before-peer` for both SRT/FIPS and
SRT/media) and complete cleanup. This confirms that the selected SRT v0.3.0 and
SRT Telemetry revisions work together over the pinned FIPS v0.5.3 data plane in
this bounded setup, and that the incident peer's `1alpha1` recordings still
satisfy the Fabric adapter contract at the new Telemetry revision.

No loss, delay, UDP backpressure, outage, route transition or independent video
decode was exercised. The receiver is provider-linked. This result cannot
establish a throughput, CPU, RSS or continuity effect of SRT 0.3.0, FIPS 0.5.3
or the Telemetry changes over the prior candidates; it does not identify a
first divergent layer or fault domain. The bundle explicitly records
`G3: not-passed` and `G4: not-passed`. The faulted and comparative experiments
required by [ADR-0007](../decisions/0007-dependency-refresh-2026-10-22.md) and
the [gate registry](gate-registry.md) remain outstanding.

An interim capture on SRT v0.2.9
([run 39793287761](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/39793287761))
also passed earlier the same day; its bundle is not retained because v0.2.9 was
replaced by v0.3.0 before merge.
