# Golden contract cases

These fixtures are deterministic, pseudonymous, and machine-checked. They exercise contract and
analysis behavior; they are not live transport evidence unless a case explicitly says otherwise.

- `srt-adapter-v1` proves byte-reproducible conversion from the pinned SRT Telemetry JSONL contract
  into the Fabric SRT observation contract. The first-sample delta boundary remains `partial`.
- `g4-clock-domain-boundary-v1` pairs synthetic SRT and FIPS observations from distinct
  `local-only` clock domains. The required outcome is `insufficient-evidence`, with unknown temporal
  order and no root-cause claim.

Every case contains immutable input/output hashes, supported claims, and explicit non-claims.
Repository validation checks manifests and payload contracts; unit tests regenerate outputs and
require byte identity.
