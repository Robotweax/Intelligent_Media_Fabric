# FIPS G2 Linux direct qualification

- Date: 2026-08-29
- Gate: G2 FIPS Connectivity
- Result: passed direct-underlay slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `c9c69158ca1e6b11f50e8349c5c71cc7896f29b5`
- Workflow run:
  [33274254004](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33274254004)
- Retained record:
  [Linux direct result](../../qualification/retained-results/2026-08-29-fips-g2-linux-direct-x86_64.json)

## Question

Can the ADR-0003 FIPS baseline create two isolated Linux `fips0` interfaces, carry exact IPv6
payloads across an authenticated direct UDP underlay at the expected MTU, expose the corresponding
control observations, and remove all privileged test state?

## Topology and controls

The manually dispatched qualification workflow used one ephemeral Ubuntu 24.04 GitHub runner. It
created two Linux network namespaces joined by a direct IPv4 veth pair. Each namespace ran one
externally built FIPS daemon with:

- TUN enabled as `fips0`;
- TUN and UDP MTU set to 1280;
- DNS disabled;
- an explicit private control socket;
- an ephemeral identity written only under a mode-0700 `/tmp` directory; and
- no static peers or discovery relay.

The runner fetched the exact FIPS commit, required a clean tracked source tree, verified the
Cargo.lock and `rust-toolchain.toml` digests, and built only `fips` and `fipsctl` with
`cargo build --release --locked`.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| FIPS version | `0.4.2 (rev 487fa86f65)` |
| TUN state | both nodes `active`, name `fips0` |
| Kernel TUN MTU | 1280 bytes on both nodes |
| Effective inner IPv6 MTU | 1203 bytes on both nodes |
| Authenticated topology | one peer and one link per node; estimated mesh size two |
| MMP | `full`, ETX 1, loss 0, SRTT present on both nodes |
| ICMPv6 | two echoes at 32 bytes and two at the 1155-byte effective-MTU payload boundary |
| Payload identity | exact UDP echo at 1, 1024, and 1155 payload bytes |
| FSP visibility | one session observed on each node |
| Controlled disconnect | acknowledged; zero peers and zero links afterward |
| Teardown | daemons stopped, namespaces removed, ephemeral identity directory removed |

The retained payload digests are deterministic test-vector hashes. No raw packet payload, identity,
address, key, control response, or daemon log is retained. The retained file is byte-identical to
the workflow artifact and has SHA-256
`54a2d430125cf1830e6fba30e7fa0dacf21c03401616a5a5ceef4b893e544398`.

## Interpretation

This closes the direct Linux TUN slice of G2. It demonstrates that the selected release baseline can
provide an operating `fips0` data path, FSP session establishment, exact payload delivery at the
effective MTU boundary, correlated control observations, and deterministic cleanup in isolated
Linux namespaces.

It does not pass G2 as a whole and is not G3 media evidence. After the later MTU-boundary and
lifecycle follow-ups, the following remain:

1. broader NAT traversal and public/private discovery classes;
2. broader managed-transit failure, usable-session recovery, and route-continuity behavior;
3. loss, delay, reordering, queue, and resource bounds; and
4. Robotweax SRT payload and downstream media timing over the qualified `fips0` path.

The subsequent
[one-sided NAT qualification](fips-g2-linux-nat-2026-08-29.md) added a third router namespace and
retained the same identity, MTU, observation, and teardown guarantees. Relay-assisted connectivity
and broader traversal mechanisms remained before any SRT workload was introduced.

The later
[managed-transit qualification](fips-g2-linux-managed-transit-2026-08-30.md) also proved exact
endpoint payload forwarding through a third authenticated FIPS node without a direct endpoint link.
It is data-plane transit evidence, not Nostr signaling-relay or public-discovery evidence.

The [effective-MTU boundary qualification](fips-g2-linux-mtu-boundary-2026-08-30.md) subsequently
proved that a 1204-byte IPv6 packet receives explicit ICMPv6 Packet Too Big feedback reporting MTU
1203, while boundary-sized and exact UDP payloads continue to cross the established direct path.

The [lifecycle qualification](fips-g2-linux-lifecycle-2026-08-30.md) subsequently proved direct
link-dead cleanup, identity-preserving daemon restart, automatic reauthentication without a manual
connect, and restored exact payload/FSP behavior.

The [alternate-route qualification](fips-g2-linux-alternate-route-2026-08-30.md) subsequently
proved automatic tree reparenting and exact-payload recovery through a second authenticated
transit. Its 93.439-second recovery depended on FSP idle expiry and session replacement, so it is
bounded G2 connectivity evidence rather than G6 or G3 continuity evidence.
