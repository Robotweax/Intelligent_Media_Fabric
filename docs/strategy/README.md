# Strategy source and synchronization

The authoritative internal strategy is stored in the private SRT Knowledge Base:

- document: `docs/project/robotweax-intelligent-media-fabric-strategy.md`
- registered baseline: `RWX-IMF-STRATEGY-2026-08-29`
- immutable Knowledge Base commit:
  [`b6276d5fdef7afa4ec2d5db5b4c6b64d016a88a6`](https://github.com/Robotweax/srt_knowledge_base/blob/b6276d5fdef7afa4ec2d5db5b4c6b64d016a88a6/docs/project/robotweax-intelligent-media-fabric-strategy.md)

The strategy is linked rather than copied so that two full documents cannot silently diverge. This
repository translates it into executable pins, ADRs, schemas, gates, scenarios, and evidence.

A strategy revision that changes project authorization, architecture ownership, public boundaries,
or Go/Pivot/Stop gates must update this pointer and receive a corresponding ADR or gate-registry
change in the same review cycle.
