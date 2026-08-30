# FIPS G2 Linux alternate-route qualification

- Date: 2026-08-30
- Gate: G2 FIPS Connectivity
- Result: passed bounded alternate-route connectivity slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `87cc43d621b77bf23356a9dcbf8884d3858c39dd`
- Workflow run:
  [33299120262](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33299120262)
- Retained record:
  [Linux alternate-route result](../../qualification/retained-results/2026-08-30-fips-g2-linux-alternate-route-x86_64.json)

## Question

Can the pinned FIPS baseline reconverge from an active managed-transit path to an already
authenticated alternate path after an ungraceful transit-process failure, without an
operator-issued route, connect, or session-reset command, and eventually restore exact endpoint
payload delivery?

## Method and controls

The manually dispatched workflow created four Linux network namespaces in a diamond:

```text
        R1
       /  \
      A    B
       \  /
        R2
```

Each edge used its own isolated IPv4 `/30` veth segment and authenticated FIPS UDP link. Ordinary
IPv4 forwarding was disabled on R1 and R2, no A–B underlay link existed, and an A-to-B IPv4 probe
had to fail. All nodes ran `fips0` at TUN and UDP MTU 1280. A was assigned the lowest of four
freshly generated FIPS node addresses so it was the deterministic tree root. The R2–B edge had a
20 ms one-way netem delay in each direction; this froze R1 as B's lower-cost parent while retaining
R2 as an authenticated alternate. This is a path-cost control, not an impaired-network result.

Before fault injection, every node had two authenticated peers and links, all eight adjacent-link
views exposed full MMP and SRTT, and both endpoints registered the other's identity through their
loopback-only FIPS DNS responder. A-to-B ICMPv6 had to pass at the 1155-byte effective-MTU payload
boundary. Exact deterministic UDP echo at 1, 1024, and 1155 payload bytes had to produce positive
forwarding deltas on R1 and zero deltas on R2. FSP sessions terminated only at A and B.

The runner then sent `SIGKILL` to R1 without a graceful disconnect and left all underlay interfaces
up. The immediate overlay probe had to fail. Within the 60-second reparenting budget, A and B had
to remove R1, B had to change parent from R1 to R2 while keeping root A and depth two, and B's tree
declaration sequence and parent-loss counter had to increase. No route or connect command was
allowed.

The established endpoint FSP session was sampled throughout reparenting. The pinned baseline kept
the original session established, but its stale route coordinates did not immediately carry data.
The configuration therefore froze the baseline's 90-second idle-session timeout. Failed sends do
not refresh application activity; after idle removal, the next TUN packet had to trigger FIPS
discovery and a new endpoint FSP session automatically. The session-start values had to change on
both endpoints with zero manual session-reset commands. Exact payload and boundary-sized ICMPv6
then had to pass through R2 while R1 remained unavailable.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| FIPS version | `0.4.2 (rev 487fa86f65)` |
| Initial topology | four nodes, four authenticated links, two peers/links per node, root A, B parent R1 |
| Path-cost control | 20 ms one-way delay on the R2–B alternate edge |
| Initial exact payload path | R1 forwarded 6 packets / 5166 bytes; R2 forwarded zero |
| FSP termination | one endpoint session per endpoint; zero sessions on both transits |
| Failure injection | R1 terminated by `SIGKILL`; no graceful disconnect; underlay stayed up |
| Outage proof | immediate ICMPv6 overlay probe blocked |
| Automatic tree reparenting | B changed parent R1 → R2 in 31,746 ms; root and depth unchanged |
| Tree telemetry | declaration sequence and parent-loss counter increased |
| Operator mutation | zero route/connect commands and zero session-reset commands |
| Original FSP observation | remained established with unchanged start across 115 control polls during reparenting |
| Automatic FSP recovery | both endpoint session starts changed after the configured 90-second idle timeout |
| Exact payload recovery | succeeded through R2 after 93,439 ms; R2 forwarded 6 packets / 5166 bytes |
| Post-failure ICMPv6 | two echoes passed at the 1155-byte effective-MTU payload boundary |
| Payload identity | matching hashes at 1, 1024, and 1155 bytes before and after failure |
| Teardown | faulted daemon reaped; live daemons stopped; namespaces and identity directory removed |

The elapsed times are one-run GitHub-hosted observations and qualification stop conditions, not
production SLOs. The retained file is byte-identical to the reviewed workflow artifact and has
SHA-256 `16b8c4c9f1a8afb5e28f00576beb7be535ca5f673e4d1c4d154bdc1d068eedc3`. It excludes private
keys, public identities, mesh and underlay addresses, process identifiers, raw payloads, control
responses, and daemon logs.

## Interpretation

This closes a bounded alternate-route connectivity slice of G2: the pinned FIPS baseline detected
the failed active transit, reparented the tree to an already authenticated alternate without an
operator command, automatically rediscovered the endpoint after session expiry, and restored
byte-exact delivery through the surviving transit.

The result also exposes an important limitation. Tree reconvergence at 31.746 seconds did not make
the established FSP session immediately usable. Recovery depended on the 90-second idle timeout
and session re-establishment, producing 93.439 seconds from fault to exact-payload recovery. This is
not hitless, is not an acceptable media-continuity claim, and does not prove that an existing SRT
socket or running stream survives. It therefore does not pass G6 or G3.

The external-daemon baseline remains suitable for later transparent SRT experiments, but route
continuity must not be assumed. G6 must compare this behavior with SRT connection-group resilience
and determine whether a FIPS improvement, a bounded workaround, or a pivot is justified. G2 remains
open for broader NAT and discovery classes, dynamic or impaired-network PMTUD, other
impaired-network cases, and resource bounds. The subsequent
[heterogeneous multihop-MTU qualification](fips-g2-linux-multihop-mtu-2026-08-30.md) closed the
static lower-bottleneck PMTUD slice without changing this non-hitless reconvergence finding.
