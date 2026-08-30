# FIPS G2 Linux heterogeneous multihop-MTU qualification

- Date: 2026-08-30
- Gate: G2 FIPS Connectivity
- Result: passed static heterogeneous multihop-PMTUD slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `71491460933f88b895d3510a9a236669df2d7642`
- Workflow run:
  [33300362782](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33300362782)
- Retained record:
  [Linux multihop-MTU result](../../qualification/retained-results/2026-08-30-fips-g2-linux-multihop-mtu-x86_64.json)

## Question

Does the pinned FIPS baseline propagate a smaller transport MTU on an authenticated managed
transit into endpoint discovery and FSP path state, return explicit ICMPv6 Packet Too Big at the
derived inner path boundary, and preserve exact data delivery at and below that boundary?

## Method and controls

The privileged workflow reused the isolated three-node A–R–B topology from the managed-transit
qualification. Each edge occupied a separate IPv4 `/30` veth segment, R had ordinary IPv4
forwarding disabled, and no direct A–B underlay existed. All kernel `fips0` interfaces retained MTU
1280, while the FIPS UDP transport MTUs for A/R/B were fixed at 1280/1000/1280.

Both endpoints registered the remote identity through loopback-only FIPS DNS. A small IPv6 probe
triggered normal FIPS discovery and FSP establishment. Before the boundary test, the runner
required A's coordinate cache and both endpoint session-MMP views to expose transport path MTU
1000. Applying the pinned 77-byte FIPS IPv6 overhead yields an effective inner IPv6 path MTU of
923 bytes, below the endpoints' local effective MTU of 1203 bytes.

An ICMPv6 echo payload of 875 bytes creates a 923-byte IPv6 packet including the IPv6 and ICMPv6
headers and had to pass through R. A root-only raw ICMPv6 observer was then bound to A's `fips0`.
The runner sent an 876-byte echo payload, creating a 924-byte IPv6 packet. The probe had to receive
no echo, while the observer had to receive ICMPv6 type 2/code 0 reporting MTU 923. A second
boundary-sized probe then had to pass.

Finally, deterministic UDP echo at 1, 512, and 875 payload bytes had to be byte-exact. R had to
expose positive forwarding counters while terminating zero FSP sessions. Controlled disconnect
and complete daemon, namespace, and temporary identity-directory teardown remained mandatory.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| FIPS version | `0.4.2 (rev 487fa86f65)` |
| Topology | authenticated A–R–B line; peer/link counts `[1, 2, 1]`; no direct endpoint peer or underlay |
| Kernel TUN MTUs A/R/B | `[1280, 1280, 1280]` bytes |
| FIPS UDP MTUs A/R/B | `[1280, 1000, 1280]` bytes |
| Local effective IPv6 MTUs A/R/B | `[1203, 923, 1203]` bytes |
| Learned coordinate-cache PMTU | 1000 transport bytes |
| Endpoint FSP session PMTUs | `[1000, 1000]` transport bytes |
| Effective multihop IPv6 PMTU | 923 bytes |
| Boundary probe | 875-byte echo payload / 923-byte IPv6 packet passed |
| Above-boundary probe | 876-byte echo payload / 924-byte IPv6 packet received no echo |
| Explicit feedback | ICMPv6 type 2, code 0, reported MTU 923 |
| Post-PTB recovery | boundary-sized probe passed immediately afterward |
| Payload identity | exact UDP echo at 1, 512, and 875 payload bytes |
| Transit evidence | R forwarded 37 packets / 14,532 bytes and terminated zero FSP sessions |
| Controlled disconnect | two acknowledgements; zero peers and links afterward |
| Teardown | daemons stopped, namespaces removed, ephemeral identity directory removed |

The retained file is byte-identical to the reviewed workflow artifact and has SHA-256
`a029153e488190222be1267f57a3068be6c5aa1882fec26880ab361160d3a2d8`. It excludes private keys,
public identities, mesh and underlay addresses, process identifiers, raw payloads, control
responses, packet captures, and daemon logs.

## Interpretation

This closes the explicit static heterogeneous multihop-PMTUD slice of G2. The pinned baseline
propagated the smaller transit transport MTU into discovery and both endpoint sessions, generated
the correct inner ICMPv6 PTB at one byte above the derived path boundary, and continued exact
delivery at and below the boundary. The result is stronger than the earlier direct-MTU test because
the endpoint-local effective MTU remained 1203 while the learned remote path admitted only 923.

The run did not change a live underlay MTU, suppress ICMP feedback, exercise IPv6 fragmentation,
combine the constraint with NAT, or send Robotweax SRT traffic. Dynamic MTU reduction, PTB loss,
reactive `MtuExceeded` recovery, and SRT packetization therefore remain separate impairment and G3
work. G2 remains open for broader NAT and public/private discovery classes, impaired-network
cases, and resource bounds.
