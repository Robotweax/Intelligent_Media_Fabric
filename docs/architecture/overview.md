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

## Relay terminology

Three distinct roles must not be collapsed into one generic "relay":

- a Nostr relay carries discovery and signaling metadata; it is not the FIPS media data path;
- a managed FIPS transit node is an authenticated overlay peer that forwards encrypted FIPS
  packets between endpoint peers; and
- a NAT gateway or traversal service changes underlay reachability and endpoint visibility.

Each role requires separate topology, security, and qualification evidence. The retained
[managed-transit qualification](../qualification/fips-g2-linux-managed-transit-2026-08-30.md)
exercises only the second role. The subsequent
[alternate-route qualification](../qualification/fips-g2-linux-alternate-route-2026-08-30.md)
also exercises that role with two authenticated transits and an active-transit failure. It proves
automatic tree reparenting, but its 93.439-second exact-payload recovery is explicitly non-hitless
and is not media-continuity evidence.

## Initial integration

Phase 1 uses an external, pinned FIPS daemon and its `fips0` interface. Robotweax SRT communicates
through normal public socket APIs. No FIPS source is vendored, no private SRT object is linked, and
no new FIPS native-datagram dependency is accepted in the first implementation.

The native FIPS API becomes a candidate only if qualified TUN, MTU, copying, or performance evidence
fails an approved gate. Generic multipath requires a separate post-Phase-4 decision.

The TUN boundary does not imply one mesh-wide MTU. The retained
[heterogeneous multihop-MTU qualification](../qualification/fips-g2-linux-multihop-mtu-2026-08-30.md)
shows endpoint-local effective MTU 1203 with a learned remote-path MTU of 923. Packetization and
later SRT configuration must consume qualified per-destination path state rather than assume the
local `fips0` limit applies end to end.

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

The first retained FIPS alternate-route result reinforces this boundary: tree reparenting completed
after 31.746 seconds, while the stale endpoint FSP session required automatic expiry and
re-establishment before data recovered after 93.439 seconds. G6 must therefore compare observable
application recovery, not route state alone.

## Stable contracts in Phase 0

- immutable dependency pins;
- qualification scenario and result schemas;
- correlation and route-epoch schemas;
- explicit gate identifiers and evidence classes; and
- security and authorization drafts.

These are repository-internal pre-alpha contracts. Versioning them does not turn them into public
product commitments.
