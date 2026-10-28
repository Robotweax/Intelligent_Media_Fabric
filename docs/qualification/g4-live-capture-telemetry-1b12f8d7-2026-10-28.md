# Healthy SRT v0.3.1 over FIPS v0.5.3 live capture, Telemetry `1b12f8d7` — 2026-10-28

- Workflow: [G4 SRT over FIPS Live Capture, run 40745656211](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40745656211)
- Fabric runner revision: `43757965` (branch `dev/g4-faulted-diamond`)
- SRT v0.3.1 `57fcf51a`, SRT Telemetry `1b12f8d7d75658cb7b7e00a0575fc77d965dbbec`, FIPS v0.5.3 `f4a5b4a8`
- Platform: Linux x86_64, kernel `6.17.0-1022-azure`; two isolated namespaces, direct IPv4 UDP underlay

[ADR-0009](../decisions/0009-faulted-diamond-media-observation.md) moved SRT Telemetry from
`1a018dfd` to `1b12f8d7`, which adds the incident peer's media relay. This run repeats the
unchanged healthy pilot at the new pin. The workflow passed the complete pinned Telemetry
CTest suite (78 tests) and retained the
[13-file bundle](../../qualification/retained-bundles/2026-10-28-g4-srt-over-fips-live-40745656211/result.json).
The result manifest SHA-256 is
`2c698af406184d37cb37a02b9f2992dd357001427c19f0a7288e726a45580aa1`.

All 240 messages of 1024 bytes were delivered exactly. The run recorded 14 SRT samples per
endpoint and 14 FIPS observations, `srt-before-peer` ordering for both SRT/FIPS and
SRT/media, and complete cleanup. This is the same outcome as the
[2026-10-25 run](g4-live-capture-srt-031-2026-10-25.md). The relay addition did not change
the incident peer's existing command path or its `1alpha1` recordings, as far as this
workload can show. The 2026-10-25 bundle is now digest-locked history.

Limits are unchanged from the 2026-10-25 record. This was one healthy two-node path with no
fault, route transition or independent decode. It records `G3: not-passed` and
`G4: not-passed`.
