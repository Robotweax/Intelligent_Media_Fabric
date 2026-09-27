# Healthy SRT v0.2.6 over FIPS live capture — 2026-09-27

- Workflow: [G4 SRT over FIPS Live Capture, run 36309262514](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/36309262514)
- Fabric runner revision: `64c5b9d54e0eff48b01034eea33b5d7d95f4b9ea`
- SRT v0.2.6: `50cba37bc89f423ee7c0a292c3c3eae71b5fc7f9`
- FIPS v0.5.1: `c5aeef39ef9442d9e5047331156df368ace40cbd`
- SRT Telemetry: `bf10da0431fdf23772210262755f745b62b6ff58`
- Platform: Linux x86_64, kernel `6.17.0-1022-azure`; two isolated namespaces
- Path: Robotweax SRT over IPv6 `fips0`, direct IPv4 UDP underlay

The workflow built the pinned sources and ran the complete pinned Telemetry
CTest suite before the live capture. It retained the
[13-file evidence bundle](../../qualification/retained-bundles/2026-09-27-g4-srt-over-fips-live-36309262514/result.json).
The result manifest SHA-256 is
`a9fa7d9059acd1accd71d70e4bb2c50bd0640a36ed6a60850804df282beca090`.
Repository validation checks its file inventory, source-to-adapter replay,
ordering assessments and declared media observation.

The healthy experiment passed: all 240 application messages of 1024 bytes were
delivered exactly. It recorded 14 SRT samples per endpoint, 14 FIPS observations,
valid same-host temporal ordering and complete cleanup. This confirms that the
selected SRT v0.2.6 and SRT Telemetry revisions work together over the pinned
FIPS data plane in this bounded setup.

No loss, delay, UDP backpressure, outage, route transition or independent video
decode was exercised. The receiver is provider-linked. This result cannot
establish a throughput, CPU, RSS or continuity improvement over the prior SRT
candidate; it does not identify a first divergent layer or fault domain. The
bundle explicitly records `G3: not-passed` and `G4: not-passed`. Future faulted
and comparative experiments remain required by
[ADR-0006](../decisions/0006-srt-026-baseline.md).
