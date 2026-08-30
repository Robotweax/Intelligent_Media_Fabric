# FIPS WP1 source, build, and bounded runtime assessment

- Date: 2026-08-29
- Gate: G2 FIPS Connectivity
- Result: partial evidence; G2 remains `in-progress`
- Decision: [ADR-0003](../decisions/0003-fips-phase1-baseline.md)
- Retained record:
  [fips-source-build-assessment](../../qualification/retained-results/2026-08-29-fips-source-build-assessment-macos-arm64.json)

## Question

Which pinned FIPS candidate should be the Phase 1 transparent-`fips0` baseline, and what observable
or controllable capabilities already exist without a Robotweax fork?

This assessment distinguishes four evidence classes:

1. source-contract inspection;
2. clean locked build provenance;
3. upstream test-suite behavior; and
4. a bounded two-daemon loopback smoke.

Only the fourth class is runtime network evidence, and its TUN interface was deliberately disabled
on the macOS assessment host.

## Reproduction boundary

Both candidates were separate clean worktrees from
`https://github.com/jmcorgan/fips.git`. The exact commands were:

```text
git worktree add --detach <release-worktree> 487fa86f65794071e3b91313c298d4f09b98b7fe
git worktree add --detach <development-worktree> 6b6d2a8df9fb6c6d5c2d1ba9e17e7bd0347dae73
cargo build --release --locked
cargo test --locked
```

The project-pinned toolchain in both trees resolved to:

| Item | Observed value |
| --- | --- |
| Host | Darwin 25.5.0 arm64 |
| Rust target | `aarch64-apple-darwin` |
| rustc | `1.94.1 (e408947bf 2026-03-25)` |
| cargo | `1.94.1 (29ea6fb6a 2026-03-24)` |
| rustup installer SHA-256 | `6c30b75a75b28a96fd913a037c8581b580080b6ee9b8169a3c0feb1af7fe8caf` |

The retained JSON records the Cargo lockfile, toolchain-file, and binary SHA-256 digests and sizes.
Build products themselves are not committed.

## Candidate comparison

| Property | Release candidate | Development candidate |
| --- | --- | --- |
| Version / revision | `v0.4.2` / `487fa86f6579…` | `0.5.0-dev` / `6b6d2a8df9fb…` |
| Locked release build | passed | passed |
| Complete passing test attempt | 1,646 passed, 0 failed, 6 ignored | 2,225 passed, 0 failed, 6 ignored |
| Additional test observation | three non-fatal test-code warnings | first full attempt: 2,132 passed, 1 intermittent native test failure, 5 ignored |
| Transparent `fips0` daemon | yes | yes |
| Development native API | absent | experimental, disabled by default |
| Registered control mutation | connect, disconnect | connect, disconnect, probes, tick profiler |
| Route selection or pinning | absent | absent |
| Phase 1 disposition | primary baseline | research-only |

The development failure
`native::tests::an_arrival_reaches_the_listener_descriptor_with_its_flow_and_what_it_held`
passed in isolation, and the second complete run passed. It is therefore recorded as intermittent,
not as a deterministic release blocker. It nevertheless raises the qualification cost of making the
experimental native API a foundational dependency.

## Source-contract inventory

Both candidates default to:

| Contract | Default |
| --- | --- |
| Control interface | enabled |
| Control heartbeat | 10 seconds |
| Link-dead timeout | 30 seconds |
| Tree hold-down | 30 seconds |
| Tree reevaluation | 60 seconds |
| Flap dampening | 120 seconds |
| Session idle timeout | 90 seconds |
| TUN name | `fips0` |
| TUN MTU | 1280 bytes |
| UDP MTU | 1280 bytes |
| FIPS IPv6 overhead | 77 bytes |
| Effective inner IPv6 MTU | 1203 bytes |
| MMP link/session mode | `full` |
| MMP log interval | 30 seconds |
| MMP OWD window | 32 samples |

The control catalog is read-rich: status, peers, links, tree, sessions, MMP, metrics, transports,
routing, sockets, cache, identity cache, connection state, gateway state, mappings, and historical
statistics are available. The stable mutations are only `connect` and `disconnect`.

Neither pinned candidate registers a command for route pinning, route-selection mutation,
disjoint-path selection, or multipath mutation. That result sharpens OD-09: the initial advisor can
consume observations, but later active control requires a separately designed upstream capability
or a governed patch decision.

The development native API is not an SRT replacement. Its documented contract has no
acknowledgement, retransmission, ordering, or flow control. Local clients authorized through the
FIPS group can act as the node, so the interface is also not a tenant-isolation boundary. Its
documentation is inconsistent about macOS listener support, which must be clarified before any
cross-platform dependency.

## Bounded runtime smoke

Two `v0.4.2` daemons ran with persistent test identities, explicit control sockets, separate UDP
loopback ports, DNS disabled, and TUN disabled. No secret key, raw daemon log, or high-cardinality
identity is retained.

Observed after connection:

- one authenticated outbound/inbound peer relationship and one link per node;
- estimated mesh size of two;
- UDP transport on loopback;
- MMP mode `full`, zero observed loss, ETX 1, and an SRTT measurement;
- reported effective inner IPv6 MTU of 1203 bytes; and
- no FSP session because no application payload was initiated.

The release control command acknowledged `disconnect`, and both nodes subsequently reported an
empty peer set. Both daemons then exited cleanly on interrupt.

This proves a macOS control/UDP/authenticated-link/MMP smoke only. It does not prove `fips0`
forwarding, media continuity, NAT traversal, relay operation, Linux gateway behavior, or a security
property beyond the observed protocol state.

## Decision and remaining G2 work

ADR-0003 selects `v0.4.2` as the Phase 1 baseline and keeps the development candidate available for
separate observation/probe research. G2 remains open until retained Linux evidence covers:

1. two isolated nodes with `fips0` present and the expected MTU;
2. bidirectional payload identity across the TUN path;
3. FSP session and control-observation agreement;
4. packet-size boundaries below, at, and above the conservative inner MTU;
5. at least direct, NATed, and managed-FIPS-transit connectivity classes;
6. explicit connect, disconnect, link-dead, and daemon-restart behavior;
7. bounded logs, source/artifact provenance, and missing-metric representation; and
8. teardown proving no residual namespace, route, process, or credential material.

SRT-over-FIPS performance and continuity remain G3 evidence and must not be inferred from this WP1
assessment.

## Linux direct progress update

The [FIPS G2 Linux direct qualification](fips-g2-linux-direct-2026-08-29.md) subsequently completed
the two-node direct-`fips0` slice: both TUN devices were active at MTU 1280, exact IPv6/UDP payloads
crossed the overlay through the 1203-byte effective IPv6 boundary, FSP sessions were visible, and
disconnect plus privileged teardown completed. At that point, G2 remained `in-progress` for NAT and
managed-transit classes, above-boundary MTU behavior, failure/restart cases, and impaired-network
qualification. The NAT and managed-transit updates below supersede the first two remaining items.

The [one-sided NAT qualification](fips-g2-linux-nat-2026-08-29.md) subsequently proved a
private-originated authenticated UDP link through stateful SNAT, including public-side observation
of the translated peer endpoint and the same exact-payload and teardown checks. G2 remains
`in-progress` for managed transit, broader traversal, above-boundary MTU behavior, failure/restart
and reconvergence cases, and impaired-network qualification.

The [managed-transit qualification](fips-g2-linux-managed-transit-2026-08-30.md) subsequently
proved exact A-to-B endpoint payloads across a static authenticated A–R–B FIPS line, with no direct
endpoint peer or ordinary IPv4 forwarding path. R reported positive forwarding counters while FSP
sessions terminated only at A and B. This completes the static managed-transit class, but it is not
Nostr signaling-relay or public-discovery evidence.

The [effective-MTU boundary qualification](fips-g2-linux-mtu-boundary-2026-08-30.md) subsequently
proved explicit ICMPv6 Packet Too Big type 2/code 0 with MTU 1203 for a 1204-byte direct-path IPv6
packet, followed by successful boundary-sized and exact UDP traffic. This completes the direct
below/at/one-byte-above MTU class.

The [lifecycle qualification](fips-g2-linux-lifecycle-2026-08-30.md) subsequently proved bounded
link-dead cleanup after an ungraceful direct-peer failure, stable identity across daemon restart,
automatic reauthentication with zero manual reconnect commands, and restored exact payload/FSP
behavior. This completes the explicit direct link-dead/daemon-restart item. At that point G2 remained
`in-progress` for broader NAT and discovery classes, alternate-route and managed-transit
reconvergence, impaired networks, heterogeneous multihop PMTUD, and resource bounds.

The [alternate-route qualification](fips-g2-linux-alternate-route-2026-08-30.md) subsequently
proved bounded recovery in an authenticated A–R1/R2–B diamond. After R1 was killed, B reparented to
R2 in 31,746 ms with no route or connect command. Exact payload recovery followed after 93,439 ms
through automatic idle-session removal, discovery, and FSP re-establishment with no session-reset
command. This closes the basic alternate-route connectivity slice but is explicitly non-hitless;
it does not qualify SRT socket or media continuity.

The [heterogeneous multihop-MTU qualification](fips-g2-linux-multihop-mtu-2026-08-30.md)
subsequently proved transport PMTU 1000 and inner IPv6 PMTU 923 across a static A–R–B path, with
explicit PTB/923 above the boundary and exact payload below it. G2 remains `in-progress` for broader
NAT and discovery, dynamic or lost-feedback PMTUD, other impaired networks, and resource bounds.
