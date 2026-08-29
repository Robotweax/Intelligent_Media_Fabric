# FIPS G2 Linux managed-transit qualification

- Date: 2026-08-30 (Europe/Berlin; run completed 2026-08-29 UTC)
- Gate: G2 FIPS Connectivity
- Result: passed managed-transit slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `40d7cd448b692f454abb7fb9d65d1518bca81860`
- Workflow run:
  [33278182406](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33278182406)
- Retained record:
  [Linux managed-transit result](../../qualification/retained-results/2026-08-30-fips-g2-linux-managed-transit-x86_64.json)

## Question

Can the ADR-0003 FIPS baseline carry exact endpoint payloads across a three-node A–R–B overlay
when A and B have no direct authenticated link and cannot communicate through ordinary IPv4
forwarding, while R forwards the FIPS data path without terminating the endpoint FSP session?

## Topology and controls

The manually dispatched workflow used one ephemeral Ubuntu 24.04 runner and three Linux network
namespaces. A and R shared one IPv4 veth segment; R and B shared another. Explicit endpoint routes
pointed toward R, but IPv4 forwarding on R was disabled and a preflight A-to-B IPv4 probe had to
fail. Each namespace ran a separate externally built FIPS daemon with an active `fips0` interface.

A connected only to R's left underlay address and B connected only to R's right address. The
resulting authenticated peer/link counts had to be `[1, 2, 1]`, with no direct A–B peer
relationship. Both endpoints registered the remote endpoint identity through their own
loopback-only FIPS DNS responder at `::1:5354`; the run did not use public discovery.

This is a managed FIPS data-plane transit test. A Nostr relay in the FIPS architecture is a
signaling and discovery facility, not the forwarding node exercised here. No Nostr relay, public
discovery, NAT traversal, or direct A–B underlay was enabled.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| FIPS version | `0.4.2 (rev 487fa86f65)` |
| Underlay exclusion | R IPv4 forwarding disabled; direct A-to-B probe blocked |
| Authenticated topology | peer/link counts `[1, 2, 1]`; estimated mesh size three; no direct endpoint peer |
| Identity registration | endpoint identities resolved locally through FIPS DNS; no public discovery |
| TUN state | all three nodes `active`, name `fips0` |
| Kernel/effective MTU | 1280/1203 bytes on all three nodes |
| MMP | four direct-link views `full`, ETX 1, loss 0, SRTT present |
| Multihop ICMPv6 | passed at 32 bytes and the 1155-byte effective-MTU payload boundary |
| Payload identity | exact A-to-B UDP echo through R at 1, 1024, and 1155 payload bytes |
| Transit evidence | R forwarded 25 packets and 12,148 bytes |
| FSP roles | one endpoint session on A and B; zero sessions terminated on R |
| Controlled disconnect | both adjacent links acknowledged; zero peers and links afterward |
| Teardown | daemons stopped, all namespaces removed, ephemeral identity directory removed |

The retained record excludes identities, underlay addresses, raw packets, keys, control responses,
and daemon logs. It is byte-identical to the reviewed workflow artifact and has SHA-256
`47a813d7b2133c5f56f1445a95f53a227f9873ef70966101d48d3c469c953995`.

## Interpretation

This closes the static managed-FIPS-transit slice of G2. It demonstrates an authenticated
three-node overlay data path with exact endpoint payload delivery, direct-endpoint exclusion,
positive forwarding counters on R, and endpoint-only FSP termination. The result supports the
strategy's distinction between an authorized managed transit service and discovery signaling.

It does not prove that R was unable to inspect plaintext by independent packet capture. Payload
opacity is classified only from the pinned FIPS protocol contract. The run also does not qualify a
Nostr signaling relay, public discovery, NAT-assisted relay selection, alternate routes, transit
failure, restart, route reconvergence, impaired networks, or SRT media behavior.

G2 therefore remains open for one-byte-above-boundary MTU behavior, broader NAT/discovery classes,
link-dead and restart cases, reconvergence, impairment and resource bounds. Robotweax SRT payload,
timing, and continuity over the qualified `fips0` paths remain G3 work.
