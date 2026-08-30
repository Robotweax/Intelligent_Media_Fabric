# ADR-0004: SRT Telemetry adapter boundary

- Status: accepted
- Date: 2026-08-30
- Closes: OD-08

## Context

Intelligent Media Fabric needs SRT observations for cross-layer correlation, but the separate
Robotweax SRT Telemetry project already owns the public-SRT adapter, field semantics, the delta
engine for lifetime counters, quality masks, bounded recorder, JSONL format, and SRT-domain
incident analysis. Reimplementing any of those functions in the Fabric would create two meanings
for the same SRT counters and widen the provider contract.

The Fabric currently pins Robotweax SRT commit
`e3d61f77e852001224b6586c63bcff46a3200223`. SRT Telemetry revision
`9c49648dda59231f3c1bd8dfa4fc9fbeea1eceb2` was rebuilt against that exact installed public SRT
interface and passed all 42 tests, the supported session-destroy-before-socket-close lifecycle,
provider-linked JSONL recording, and bidirectional Haivision v1.5.5 interoperability for the common
nine-field unencrypted Live/Message IPv4 loopback subset.

Telemetry retention commit `9e879b13d94e9e4f62e1e9167012e98c5b945c9d` adds only qualification
records and documentation over the tested revision. It was the initial Fabric dependency pin. The
newer Robotweax SRT profile does not inherit the older profile's loss, burst, pressure,
recovery-margin, or operator-study claims.

Follow-up commits `40767f0a46018852853574b4c8651eb4f1b1f4a9` and
`bf10da0431fdf23772210262755f745b62b6ff58` make the provider-linked incident peer explicitly
addressable over IPv4 or IPv6 and its 1–1,316-byte test payload explicit, with an IPv6-loopback
1,024-byte JSONL regression. Fabric pins the latter commit so its external coordinator can place
the unchanged peer on a declared `fips0` address within the frozen MTU budget; SRT sampling
semantics remain owned by SRT Telemetry.

## Decision

Consume SRT Telemetry as an external, pinned component through its installed versioned C ABI and
CMake targets. The Fabric must not call `srt_bistats` independently, clear provider counters, derive
a second set of SRT deltas, or vendor a second SRT implementation.

The adapter contract is
[`srt-telemetry-observation.schema.json`](../../schema/telemetry/srt-telemetry-observation.schema.json).
Each Fabric SRT observation carries the complete upstream recording header and sample without
renaming or reinterpreting source values. The adapter may add only:

- a Fabric event identifier and route epoch;
- an explicitly authorized tenant, device, or Fabric stream mapping;
- a declared clock domain, synchronization mechanism, maximum error, and cross-host-ordering flag;
- immutable provider, telemetry, source-schema, and build provenance; and
- a generic availability summary while preserving every upstream availability, quality, reset, and
  rate bitmask verbatim.

Direct `source: srt` input is excluded from the older generic correlation envelope so producers
cannot bypass these requirements.

Fabric identity is never inferred from the SRT Telemetry `streamId` or `flowId`. Each mapping is
either `explicit-policy` or `unavailable`, and source identifiers must already be pseudonymous.
Route epoch zero means unknown or not yet assigned; it is not an SRT path or connection-group ID.

Local monotonic time is the ordering authority inside one declared clock domain. `local-only` and
`unknown` clocks prohibit cross-host ordering. NTP, PTP, or GPS permits cross-host ordering only
when the observation includes a non-negative maximum clock error; G4 experiments must still define
their own acceptable error bound. SRT source and TSBPD timestamps remain transport metadata.

Metric namespaces and semantics remain separate:

- SRT fields retain their sender/receiver side, counter/gauge/delta temporality, and base units of
  seconds, octets, packets, and bits per second;
- FIPS MMP link/session loss, ETX, and SRTT remain FIPS observations; and
- the Fabric may correlate the two namespaces but must not equate FIPS MMP `loss_rate` with SRT
  sender loss, receiver loss, drop, or retransmission counters.

SRT Telemetry remains authoritative for its bounded raw recorder and SRT-domain hypotheses. The
Fabric recorder may retain source digests and derived cross-layer evidence, and the Fabric analyzer
may combine SRT hypotheses with FIPS, OS, route, and media-consumer evidence. It must not overwrite
source records or present a cross-layer inference as a source fact.

The integration is observation-only. It grants no route, SRT, encoder, or relay mutation authority.

## Rationale

- One SRT semantics owner prevents divergent counter clearing, reset handling, availability, units,
  and sender/receiver interpretations.
- A complete upstream payload keeps unavailable distinct from zero and lets future investigations
  reproduce the Fabric mapping.
- Explicit identity and clock contracts prevent attractive but invalid joins across tenants, boots,
  hosts, or unsynchronized endpoints.
- Separate metric namespaces allow correlation without manufacturing a false shared denominator.
- Exact pins and narrow qualification claims keep pre-alpha evidence from silently expanding into a
  production compatibility promise.

## Consequences

- OD-08 is closed. The deterministic adapter and negative clock-boundary fixture start G4 but do
  not pass it. A fail-closed healthy live-pilot runner is now frozen; retained live results,
  faulted route transitions, and first-divergent-layer evidence are still required.
- The adapter must validate the upstream JSONL line against the pinned upstream schema before
  constructing the Fabric observation, then pass the executable Fabric validator.
- The pinned upstream schema ID is
  `https://robotweax.com/schemas/srt-telemetry/telemetry-jsonl-line-v1alpha1.json`; its SHA-256 at the
  pinned revision is `ec235ac4fcc4e1ffc0a3881dcb2fe7a206c80013de5f1b6e2a23a7de42ffcd8e`.
- Any change to the SRT Telemetry ABI, JSONL schema, quality bits, metric semantics, provider revision,
  lifecycle, or build profile requires a new exact pin and scoped requalification.
- Linux, IPv6, encryption, FEC, groups, `fips0`, counter resets, concurrent close/sample, and
  representative deployment performance remain unqualified for the new Robotweax SRT profile.

## Evidence

- [G4 adapter and clock-boundary implementation result](../qualification/g4-unified-observation-data-quality-2026-08-30.md)
- [Fabric-pinned Robotweax SRT candidate](https://github.com/Robotweax/srt_telemetry/blob/9e879b13d94e9e4f62e1e9167012e98c5b945c9d/qualification/candidates/robotweax-srt-0.2.0-11-ge3d61f7.json)
- [Runtime and lifecycle result](https://github.com/Robotweax/srt_telemetry/blob/9e879b13d94e9e4f62e1e9167012e98c5b945c9d/qualification/results/2026-08-30-macos-arm64-public-srt-runtime-e3d61f7.json)
- [Bidirectional interoperability result](https://github.com/Robotweax/srt_telemetry/blob/9e879b13d94e9e4f62e1e9167012e98c5b945c9d/qualification/results/2026-08-30-macos-arm64-public-srt-interop-e3d61f7.json)
- [Executable adapter fixture](../../qualification/fixtures/srt-telemetry-observation-v1.json)
