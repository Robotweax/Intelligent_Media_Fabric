# Healthy SRT v0.3.2 over FIPS v0.5.3 live capture — 2026-11-12

- Workflow: [G4 SRT over FIPS Live Capture, run 43244297357](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/43244297357), dispatched on the branch
- Fabric runner revision: `c5052b1e` (branch `dev/srt-032-refresh`, PR #14)
- SRT v0.3.2 `e45d0edd`, SRT Telemetry `7a6b8eff65c686ccafa36a0adace148a8b87d3ca`, FIPS v0.5.3 `f4a5b4a8`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure`; two isolated namespaces, direct IPv4 UDP underlay

[ADR-0010](../decisions/0010-srt-032-refresh.md) moved SRT from v0.3.1 to v0.3.2 and SRT
Telemetry from `1b12f8d7` to `7a6b8eff`. This run repeats the unchanged healthy pilot at the
new pins. It was the first attempt; no earlier attempt failed. The workflow passed the
complete pinned Telemetry CTest suite (81 tests, none failed, none skipped) and retained the
[13-file bundle](../../qualification/retained-bundles/2026-11-12-g4-srt-over-fips-live-43244297357/result.json).
The result manifest SHA-256 is
`90b1e2eb992d3878d73e96a7fa0ebd257290cc8225f925009a11e42adbbf1a6b`.

All 240 messages of 1024 bytes were delivered exactly. The run recorded 14 SRT samples per
endpoint and 14 FIPS observations, `srt-before-peer` ordering for both SRT/FIPS and
SRT/media, and complete cleanup. This is the same outcome as the
[2026-10-28 run](g4-live-capture-telemetry-1b12f8d7-2026-10-28.md). The Telemetry delta-engine
refactor between the pins did not change the `1alpha1` recordings in any way the adapter
replay or this workload can show. The 2026-10-28 bundle is now digest-locked history.

Limits are unchanged from the [2026-10-25 record](g4-live-capture-srt-031-2026-10-25.md).
This was one healthy two-node path with no fault, route transition or independent decode.
It records `G3: not-passed` and `G4: not-passed`.
