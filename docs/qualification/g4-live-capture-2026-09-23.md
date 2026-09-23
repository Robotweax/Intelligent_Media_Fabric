# Healthy SRT over FIPS live capture — 2026-09-23

- Workflow: [G4 SRT over FIPS Live Capture, run 35857439840](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35857439840)
- Fabric revision: `d89d9175c73b56c1a07f06132d44aba1aaa7c8d3`
- SRT revision: `def14a7b6d8a2ba1860677414e415fd86bbc953a`
- FIPS v0.5.1 revision: `c5aeef39ef9442d9e5047331156df368ace40cbd`
- SRT Telemetry revision: `bf10da0431fdf23772210262755f745b62b6ff58`
- Host: Linux x86_64, kernel `6.17.0-1022-azure`; two network namespaces on one host
- Path: Robotweax SRT over IPv6 `fips0`, direct IPv4 UDP underlay

The [retained bundle](../../qualification/retained-bundles/2026-09-23-g4-srt-over-fips-live-35857439840/result.json)
contains the original 13 workflow artifact files. Repository validation replays the
source-to-adapter conversions and cross-layer assessments, checks every file size and
SHA-256 digest, and rejects modified or missing samples.

The experiment passed: all 240 synthetic application messages of 1024 bytes were
delivered exactly. It contains 14 SRT samples per endpoint and 14 FIPS observations.
The recorded SRT-to-FIPS and SRT-to-application ordering assessments are valid
within the shared host monotonic clock domain. All namespace, process and temporary
identity cleanup fields are true.

This is one healthy path. No loss, delay, outage or route transition was injected.
The receiver validates application messages through the SRT-linked peer, not an
independent media decoder. The bundle explicitly concludes `G3: not-passed` and
`G4: not-passed`; it does not identify a first divergent layer or fault domain.

The private repository read secret was present for this workflow. Its value is not
part of the artifact.
