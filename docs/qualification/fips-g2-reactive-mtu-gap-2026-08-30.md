# FIPS G2 reactive path-MTU capability gap — 2026-08-30

## Status and scope

**Status: not qualified.** This is a negative capability assessment, not retained passing G2
evidence and not proof that FIPS's `MtuExceeded` implementation is defective. It records why the
required reactive experiment cannot be put into its predeclared starting state through the stock
FIPS `v0.4.2` daemon interface.

The already retained
[heterogeneous multihop-MTU qualification](fips-g2-linux-multihop-mtu-2026-08-30.md) remains
valid. It proves proactive path-MTU discovery for a static A–R–B path. This assessment concerns the
different case where an established path becomes smaller at runtime.

## Frozen baseline and question

- FIPS release: `v0.4.2`
- FIPS commit: `487fa86f65794071e3b91313c298d4f09b98b7fe`
- FIPS source, lockfile, and Rust toolchain: unmodified and digest-checked by the workflow
- topology: isolated Linux namespaces in an A–R–B line, no direct A–B underlay and no ordinary
  IPv4 forwarding through R
- initial FMP transport MTU: 1280 bytes on both links
- target bottleneck MTU: 1000 bytes on R–B
- initial endpoint FSP session path MTU: 1280 bytes

The question was whether one oversized endpoint packet could reach R after the bottleneck change,
cause R to drop it and return authenticated `MtuExceeded`, and make A converge to path MTU 1000
without replacing the endpoint FSP session or rediscovering the smaller MTU first.

## Decisive observations

The workflow artifacts were bounded failure records: no identities, addresses, private keys, raw
packets, payloads, or complete daemon logs were retained. They expire from GitHub Actions after 14
days, so their reviewed fields and SHA-256 digests are recorded here.

| Track | Run and project revision | Reviewed observation | Result digest |
| --- | --- | --- | --- |
| Restart R, allow recovery | [run 33303514503](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33303514503), `e6bcb77bde5f05dae9eb62f26d177e8505a6d8f1` | The endpoint session already reported MTU 1000 before a reactive event. R had forwarded 114 packets; endpoint `MtuExceeded` and R MTU-drop deltas were all zero. Recovery/discovery had learned the bottleneck proactively. | `204050847caab310aa364426897cf15b0da8d15edbde578812b3f76234d23a4a` |
| Restart R, trigger after peer promotion | [run 33304068655](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33304068655), `fe927e82faec39f72d48e3d320cdf9defcaac3af` | Peer/link counts recovered to `[1,2,1]`, but A's coordinate-cache entry was absent, its FSP session still reported 1280, and R forwarded zero packets. The first oversized packet could not reach the transit data plane before rediscovery; no `MtuExceeded` or MTU-drop delta occurred. | `a7fa577094587148396e17c52da7472e8320b5ee2ffaf98b02c246d95aa2aa76` |
| Prestart TCP 1000, retain UDP 1280 | [run 33304897627](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33304897627), `548319527d2f48d307e93109110d178b79617188` | The alternate TCP handshake authenticated, entered same-epoch cross-connection resolution, swapped the Noise session on the winning side, and then closed the candidate TCP connection. The active R–B FMP link did not transition from UDP to TCP within the bound. | `d17d001dd045973936c173061da3b629fc01b6fba5ae4d2574cc62a2faa9396d` |

All three attempts completed cleanup: daemons stopped, namespaces removed, and the ephemeral
identity directory deleted.

## Source-level boundary

The pinned source explains the observed control boundary:

- the daemon's [mutating control dispatcher](https://github.com/jmcorgan/fips/blob/487fa86f65794071e3b91313c298d4f09b98b7fe/src/control/commands.rs#L12-L18)
  exposes only `connect` and `disconnect`;
- `connect` reaches `api_connect`, whose normal initiation path
  [skips an already active peer](https://github.com/jmcorgan/fips/blob/487fa86f65794071e3b91313c298d4f09b98b7fe/src/node/lifecycle.rs#L283-L310);
- the Rust library does have a public
  [`Node::update_peers`](https://github.com/jmcorgan/fips/blob/487fa86f65794071e3b91313c298d4f09b98b7fe/src/node/lifecycle.rs#L34-L48)
  path intended to race a new address while retaining the active link, but the stock daemon does
  not expose it through its control protocol; and
- a raw concurrent handshake is cross-connection resolution, not an operator-selected migration.
  The resolution path
  [closes and removes the losing candidate link](https://github.com/jmcorgan/fips/blob/487fa86f65794071e3b91313c298d4f09b98b7fe/src/node/handlers/handshake.rs#L1071-L1190).

Changing the configured transport MTU therefore required restarting R in the executable under
test. Peer removal also
[clears associated FSP state and pending TUN packets](https://github.com/jmcorgan/fips/blob/487fa86f65794071e3b91313c298d4f09b98b7fe/src/node/handlers/dispatch.rs#L107-L150),
while a parent change
[invalidates downstream coordinate-cache state](https://github.com/jmcorgan/fips/blob/487fa86f65794071e3b91313c298d4f09b98b7fe/src/node/tree.rs#L605-L650).
Waiting for those structures to recover lets discovery learn MTU 1000 proactively; triggering
earlier leaves no usable route for the packet that was meant to provoke the reactive signal.

## Decision

The disposable reactive runner and its non-passing workflow are not kept on `main`. G2 remains
`in-progress`, G6 remains `not-started`, and no reactive-MTU or continuity claim is added.

Further retries against the same daemon surface would test timing accidents rather than the frozen
question. Work resumes only after selecting one of these explicit paths:

1. expose an authenticated runtime peer/path update in the FIPS daemon control protocol, backed by
   `Node::update_peers`; or
2. add an in-place active-link MTU update that does not remove peers, tree state, coordinate state,
   or endpoint FSP sessions; or
3. adopt an embedded FIPS-library integration and qualify that integration as a distinct baseline.

Any implementation beyond the stock-daemon adapter requires an ADR before it can become project
baseline work.

## Upstream acceptance contract

A proposed capability is sufficient only if a new pinned-source experiment proves all of the
following:

1. establish A–R–B at path MTU 1280 and record stable peer/link counts, route coordinates, endpoint
   FSP session identifiers, and exact UDP delivery;
2. request an R–B MTU/path transition to 1000 through one documented runtime operation, with no
   daemon restart and no control disconnect;
3. retain authenticated peer counts `[1,2,1]`, the endpoint FSP session identifiers, and usable A–B
   coordinates across the transition;
4. prevent discovery or a periodic report from lowering A's path-MTU state before the trigger;
5. send exactly one 1203-byte IPv6 trigger packet and observe a positive R MTU-drop delta plus a
   positive A `MtuExceeded` delta;
6. converge both A's route cache and endpoint FSP session to transport PMTU 1000 within 20 seconds;
7. require IPv6 payload 875 to pass, payload 876 to fail with ICMPv6 Packet Too Big reporting 923,
   and exact UDP payloads 1, 512, and 875 to pass afterward; and
8. retain immutable provenance and prove complete teardown.

This contract separates the missing runtime mutation from the already qualified static PMTUD
behavior and gives an upstream change a deterministic definition of done.
