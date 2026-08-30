# FIPS G2 Linux effective-MTU boundary qualification

- Date: 2026-08-30
- Gate: G2 FIPS Connectivity
- Result: passed effective-MTU boundary slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `c29d78aeae9dd76fc9560fb2dd3d5d7dc4c38a53`
- Workflow run:
  [33295492782](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33295492782)
- Retained record:
  [Linux MTU-boundary result](../../qualification/retained-results/2026-08-30-fips-g2-linux-direct-mtu-boundary-x86_64.json)

## Question

Does the ADR-0003 FIPS baseline provide explicit IPv6 path-MTU feedback rather than silent loss
when an application sends exactly one byte beyond the effective 1203-byte inner IPv6 MTU, and does
the established data path remain usable immediately afterward?

## Method and controls

The schema-v2 direct runner repeated the retained two-node Linux namespace topology with TUN and
UDP MTU 1280. It first required successful ICMPv6 delivery below and exactly at the effective inner
IPv6 MTU. An ICMP echo payload of 1155 bytes produces a 1203-byte IPv6 packet after the 40-byte IPv6
and 8-byte ICMPv6 headers.

Before the above-boundary probe, the runner opened a root-only raw ICMPv6 socket inside node A's
network namespace and bound it to `fips0`. The observer accepted only ICMPv6 Packet Too Big and
wrote only type, code, and reported MTU to its temporary JSON output. It did not retain packet
bytes, source or destination addresses, identities, or socket output.

The runner then sent one ICMP echo with a 1156-byte payload, producing a 1204-byte IPv6 packet. The
probe had to receive no echo reply, while the independent observer had to receive ICMPv6 type 2,
code 0, reporting MTU 1203. A second 1155-byte boundary probe and the usual deterministic UDP
payload checks then had to pass before disconnect and teardown.

## Results

| Assertion | Observed result |
| --- | --- |
| Kernel/effective TUN MTU | 1280/1203 bytes on both nodes |
| Below and at boundary | ICMPv6 passed at 32- and 1155-byte echo payloads |
| Above-boundary probe | 1156-byte echo payload / 1204-byte IPv6 packet |
| Above-boundary echo | no reply received |
| Explicit feedback | ICMPv6 type 2, code 0 |
| Reported path MTU | 1203 bytes |
| Post-PTB recovery | 1155-byte boundary probe passed immediately afterward |
| Payload identity after PTB | exact UDP echo at 1, 1024, and 1155 payload bytes |
| FSP visibility | at least one session on each endpoint |
| Controlled disconnect | acknowledged; zero peers and links afterward |
| Teardown | daemons stopped, namespaces removed, ephemeral identity directory removed |

The retained file is byte-identical to the reviewed workflow artifact and has SHA-256
`453c113573248d36b8d413c28c6deae0c079258a1b89beb6faac72a3e37e07b7`.

## Interpretation

This closes the below/at/one-byte-above effective-MTU requirement for the pinned direct Linux FIPS
path. The result demonstrates explicit ICMPv6 Packet Too Big feedback with the expected 1203-byte
MTU and proves that a boundary-sized packet and exact UDP payloads still cross the existing path
after the rejected oversized packet. The observed behavior is therefore not a silent PMTUD
blackhole in this topology.

The result does not qualify a lower heterogeneous multihop bottleneck, IPv6 fragmentation, SRT
packetization, NAT-specific PMTUD, or impaired-network PTB loss. The subsequent
[lifecycle qualification](fips-g2-linux-lifecycle-2026-08-30.md) closed the direct link-dead and
daemon-restart slice. G2 remains open for broader NAT and discovery classes, alternate-route and
managed-transit reconvergence, impaired-network cases, heterogeneous multihop PMTUD, and resource
bounds. SRT-over-FIPS correctness and continuity remain G3 work.
