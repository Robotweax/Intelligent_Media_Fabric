# Architecture overview

## Decision boundary

Robotweax Intelligent Media Fabric is an orchestration, correlation, and qualification layer. It
does not replace either transport system and must not duplicate capabilities without evidence.

```text
Media source / encoder
          |
          v
Robotweax SRT public API
  reliability, timing, ARQ, FEC, connection groups
          |
          v
Operating-system IP path through fips0
          |
          v
External pinned FIPS daemon
  identity, discovery, NAT, encrypted mesh, route telemetry
          |
          v
Underlay links and relays

Side-channel observation only during the first phases:
  SRT Telemetry + FIPS control socket + OS/network observations
                      |
                      v
       Correlation envelope + retained evidence
```

## Initial integration

Phase 1 uses an external, pinned FIPS daemon and its `fips0` interface. Robotweax SRT communicates
through normal public socket APIs. No FIPS source is vendored, no private SRT object is linked, and
no new FIPS native-datagram dependency is accepted in the first implementation.

The native FIPS API becomes a candidate only if qualified TUN, MTU, copying, or performance evidence
fails an approved gate. Generic multipath requires a separate post-Phase-4 decision.

## Control authority

The initial Media Fabric is observational:

- adapters collect SRT, FIPS, and OS measurements;
- a correlation envelope aligns monotonic and wall-clock time;
- route epochs make path changes explicit;
- the recorder produces bounded, provenance-complete evidence; and
- the advisor may later make deterministic recommendations.

It must not mutate routes, SRT settings, encoders, or relay selection until a later gate grants that
authority. Unavailable inputs remain unavailable.

## Failure and security boundaries

An established SRT socket is not a continuity result. Continuity is measured at the downstream
media consumer and includes payload correctness and timing. Likewise, an encrypted FIPS peer is not
an authorized Robotweax device or tenant; policy is a separate Media Fabric responsibility.

Fault domains must represent physical or administrative independence rather than interface labels.
SRT connection groups are the first resilience baseline. FIPS reconvergence and future FIPS-level
multipath are evaluated against that baseline, not assumed to be superior.

## Stable contracts in Phase 0

- immutable dependency pins;
- qualification scenario and result schemas;
- correlation and route-epoch schemas;
- explicit gate identifiers and evidence classes; and
- security and authorization drafts.

These are repository-internal pre-alpha contracts. Versioning them does not turn them into public
product commitments.
