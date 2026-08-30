# G4 unified-observation data-quality foundation

- Date: 2026-08-30
- Classification: harness-only contract fixtures
- Gate: G4 moved to `in-progress`; it has not passed
- Live capture: no

## Question

Can the first Fabric adapter and ordering-only analyzer preserve SRT source semantics, keep FIPS
metrics separate, and refuse a cross-layer sequence when the declared clocks do not support one?

## Adapter result

The deterministic SRT adapter consumes one complete pinned SRT Telemetry JSONL recording. It
validates the exact v1alpha1 header, raw fields, delta fields, quality/reset-mask consistency,
record count, monotonic sample-index order, and the explicit Fabric context before publishing
anything. Output uses an exclusive atomic link and is never overwritten.

The golden first sample preserves the complete source header and sample, attaches an explicit-policy
Fabric identity and route epoch 7, and produces the stable event ID
`af5cdf11-8dd9-5934-b358-92ee554dd312`. The upstream first-sample flag remains numeric value 1 and
the Fabric summary is `partial` with reason `first-sample-delta-baseline`.

- [Adapter manifest](../../qualification/golden-cases/srt-adapter-v1/manifest.json)
- [Pinned source JSONL](../../qualification/golden-cases/srt-adapter-v1/source.jsonl)
- [Expected Fabric observations](../../qualification/golden-cases/srt-adapter-v1/expected-observations.jsonl)

## Cross-layer clock-boundary result

The paired harness fixture uses the same explicit Fabric identity and route epoch for SRT and FIPS,
but declares two different `local-only` monotonic clock domains. The FIPS payload keeps
`metric_namespace: fips.mmp` and `metric_semantics: link-estimator`; its `loss_rate` is never mapped
to an SRT loss, drop, or retransmission field.

The ordering-only analyzer returns:

| Field | Expected result |
| --- | --- |
| Outcome | `insufficient-evidence` |
| Ordering | `unknown` |
| Reason | `clock-domains-not-comparable` |
| Ordering authorized | `false` |
| Metric semantics separate | `true` |

- [Clock-boundary manifest](../../qualification/golden-cases/g4-clock-domain-boundary-v1/manifest.json)
- [Synthetic SRT observation](../../qualification/golden-cases/g4-clock-domain-boundary-v1/srt-observation.json)
- [Synthetic FIPS observation](../../qualification/golden-cases/g4-clock-domain-boundary-v1/fips-observation.json)
- [Expected assessment](../../qualification/golden-cases/g4-clock-domain-boundary-v1/expected-assessment.json)

## Claims and limitations

This closes an initial adapter and negative data-quality slice. It proves deterministic preservation,
explicit mapping, local clock boundaries, route-epoch comparison, semantic namespace separation,
and a required insufficient-evidence outcome.

It does not establish a live or simultaneous SRT-over-FIPS capture, cross-host order, a first
divergent layer, a fault domain, root cause, G4 passage, or control authority. Matching tenant,
device, stream, and route epoch is insufficient to make two clock domains comparable.

## Reproduction

```bash
PYTHONPATH=src python3 -m rimf_lab adapt-srt-telemetry-jsonl \
  --source qualification/golden-cases/srt-adapter-v1/source.jsonl \
  --context qualification/golden-cases/srt-adapter-v1/context.json \
  --output /new/path/srt-observations.jsonl

PYTHONPATH=src python3 -m rimf_lab assess-cross-layer-ordering \
  --srt qualification/golden-cases/g4-clock-domain-boundary-v1/srt-observation.json \
  --peer qualification/golden-cases/g4-clock-domain-boundary-v1/fips-observation.json \
  --output /new/path/ordering-assessment.json
```

The next G4 evidence must be a simultaneous live SRT-over-FIPS capture with one declared shared
host monotonic domain or bounded synchronized clocks, route-epoch transitions, source-quality
fault cases, and downstream media-consumer observations. Temporal order alone will still not be
sufficient for a first-divergent-layer claim.

## Live-pilot runner

The manually dispatched `G4 SRT over FIPS Live Capture` workflow now freezes the first healthy
two-endpoint pilot. It builds the exact pinned FIPS, Robotweax SRT, and SRT Telemetry revisions,
creates two Linux network namespaces, connects their FIPS daemons, and binds the provider-linked
SRT incident peers to the node-B `fips0` IPv6 address. One host coordinator supplies all SRT,
FIPS, and application observations with the same Linux boot-scoped monotonic clock domain.

The pilot transfers 240 deterministic 1,024-byte SRT messages, below the profile's conservative
1,139-byte clear/CTR SRT payload ceiling. It records 14 SRT samples at each
endpoint and 14 FIPS MMP observations, validates exact receiver delivery, converts both JSONL
recordings through the strict Fabric adapter, and emits ordering-only SRT/FIPS and SRT/application
assessments. Every bundle file is hashed and the adapter outputs are byte-replayed during bundle
validation. Output is bounded to a 14-day workflow artifact unless it is separately reviewed for
retention.

Even a successful pilot result declares `G3: not-passed` and `G4: not-passed`. It contains one
healthy direct-veth route epoch, no injected fault or route transition, and a provider-linked
application receiver rather than an independent decoder. The next positive-diagnosis experiment
must add a predeclared impairment, a route-epoch transition, and an independent downstream media
observer before any first-divergent-layer claim can be considered.
