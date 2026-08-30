# FIPS G2 Linux one-sided NAT qualification

- Date: 2026-08-29
- Gate: G2 FIPS Connectivity
- Result: passed one-sided-NAT slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `8da2a1072dfe1913ffdaff0d63999481be950a2a`
- Workflow run:
  [33276449713](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33276449713)
- Retained record:
  [Linux NAT result](../../qualification/retained-results/2026-08-29-fips-g2-linux-nat-x86_64.json)

## Question

Can a FIPS node behind a stateful one-sided SNAT boundary initiate an authenticated UDP link to an
outside node, expose the translated peer path at the public side, and carry the same exact `fips0`
payloads and control observations proven by the direct-underlay test?

## Topology and controls

The manually dispatched workflow used one ephemeral Ubuntu 24.04 runner and three Linux network
namespaces: public node A, private node B, and a router between separate IPv4 veth segments. The
router had a default-deny forwarding policy. It allowed new flows only from B toward A, allowed
return traffic by connection state, and applied SNAT on the outside interface.

Before either FIPS daemon started, the runner required a new A-to-B ICMP flow to fail and a B-to-A
flow to succeed. B then initiated the FIPS connection to A. A's `show peers` response had to report
the router's translated outside endpoint rather than B's private endpoint. The endpoint itself,
peer identities, control responses, packet contents, and daemon logs were not retained.

Both FIPS daemons otherwise used the same controls as the direct test: ephemeral identities, DNS
disabled, `fips0` enabled, TUN and UDP MTU 1280, explicit private control sockets, the pinned clean
source tree, verified lock/toolchain digests, and a `--locked` release build.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| Directional underlay boundary | new A-to-B flow blocked; new B-to-A flow allowed |
| NAT path | one-sided SNAT; stateful return only |
| Connection initiator | private node B |
| Public-side peer observation | translated source endpoint observed |
| TUN state | both nodes `active`, name `fips0` |
| Kernel/effective MTU | 1280/1203 bytes on both nodes |
| Authenticated topology | one peer and one link per node; estimated mesh size two |
| MMP | `full`, ETX 1, loss 0, SRTT present on both nodes |
| ICMPv6 | two echoes at 32 bytes and two at the 1155-byte effective-MTU payload boundary |
| Payload identity | exact UDP echo at 1, 1024, and 1155 payload bytes |
| FSP visibility | one session observed on each node |
| Controlled disconnect | initiated by B and acknowledged; zero peers and links afterward |
| Teardown | daemons stopped, all three namespaces removed, identity directory removed |

The retained file is byte-identical to the workflow artifact and has SHA-256
`20db254ff8abf006fb8bc36ad33415dd89b7d654a26675f04e79d691344763ad`.

## Interpretation

This closes a deliberately narrow one-sided NAT slice of G2. It demonstrates that the selected FIPS
release can establish and operate a bidirectional authenticated overlay when the private node initiates
the direct UDP flow through stateful SNAT. It also proves that the public FIPS peer view reflects
the translated underlay path while the same MTU-boundary, payload-identity, FSP, disconnect, and
cleanup assertions remain true.

It is not a general NAT-traversal result. STUN, hole punching, endpoint-dependent/symmetric NAT,
port remapping, discovery, and relays were not exercised. G2 also remains open for
link-dead and restart cases, reconvergence, impaired networks, and resource bounds. SRT-over-FIPS
media correctness and continuity remain G3 work. The later
[direct MTU-boundary qualification](fips-g2-linux-mtu-boundary-2026-08-30.md) closed the
one-byte-above-boundary behavior for the direct topology; NAT-specific PMTUD remains unqualified.

The subsequent
[managed-transit qualification](fips-g2-linux-managed-transit-2026-08-30.md) exercised a pinned
three-node A–R–B FIPS data path without public discovery and compared its authenticated peer/link,
payload, session, forwarding-counter, and cleanup contract with the retained direct and NAT records.
That result is distinct from Nostr signaling-relay and NAT-traversal qualification.
