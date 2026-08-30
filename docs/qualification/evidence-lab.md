# Evidence Lab

## Purpose

The lab converts integration hypotheses into retained, reproducible evidence. It distinguishes
harness qualification from media-transport qualification and records missing observations as
missing rather than zero.

## Initial harness

The Python harness uses only the standard library. It:

- validates immutable dependency pins and repository JSON contracts;
- loads a reviewed scenario;
- executes commands as argument arrays without a shell;
- uses a small sanitized environment;
- enforces per-case timeouts and bounded output capture;
- records hashes and byte counts instead of raw stdout and stderr;
- records platform, project revision, scenario digest, and baseline digest; and
- writes a result atomically.

It does not configure TUN devices, namespaces, netem, NAT, packet capture, FIPS, or SRT. Those
adapters are later WP1-WP3 work and require explicit privilege boundaries.

## Commands

```bash
make check
make smoke

PYTHONPATH=src python3 -m rimf_lab validate-scenario \
  qualification/scenarios/harness-smoke.json

PYTHONPATH=src python3 -m rimf_lab run \
  --scenario qualification/scenarios/harness-smoke.json \
  --output artifacts/harness-smoke-result.json
```

The included smoke scenario is classified `harness-only`. Its result must never be cited as SRT,
FIPS, networking, performance, security, or continuity evidence.

## Real experiment requirements

Before adding a real scenario:

1. freeze the question, topology, inputs, stop condition, and expected downstream validator;
2. reference exact build and dependency artifacts;
3. select an approved gate from the gate registry;
4. use deterministic test and fault seeds;
5. predeclare repetitions and evaluation logic;
6. review every command and required privilege;
7. ensure output cannot contain secrets or customer payload; and
8. retain external binary logs separately under an approved retention policy.

Raw evidence is not committed by default. A retained result requires review for size, licensing,
privacy, secrets, and reproducibility before it enters `qualification/retained-results/`.

## Privileged FIPS G2 Linux direct runner

The manually dispatched `FIPS G2 Linux Direct Qualification` workflow is the first privileged
network adapter. It is not part of push or pull-request CI. It:

- fetches only FIPS `v0.4.2` at the ADR-0003 commit and verifies the Cargo lockfile and
  toolchain-file digests before building with `--locked`;
- creates two temporary Linux network namespaces joined by one IPv4 veth underlay;
- starts one FIPS daemon per namespace with TUN enabled, DNS disabled, and ephemeral identities;
- confirms `fips0`, kernel and effective MTU, an authenticated UDP link, and full MMP visibility;
- sends ICMPv6 below and at the effective inner-MTU boundary;
- sends one 1204-byte IPv6 packet, requires no echo and explicit ICMPv6 Packet Too Big type 2/code
  0 reporting MTU 1203, then rechecks boundary-sized delivery;
- verifies exact deterministic UDP echo digests at 1, 1024, and 1155 payload bytes;
- observes an FSP session, performs a control-socket disconnect, and checks peer/link removal; and
- stops processes and removes namespaces and the temporary identity directory before reporting
  success.

The runner requires Linux root only for namespace and TUN setup. Its host-visible state is bounded
to the temporary veth setup, `/tmp` work directory, and the requested result path; teardown verifies
that the processes, namespaces, and identity directory are gone. Private keys, npubs, addresses,
raw payloads, raw ICMP packets, and daemon logs are excluded from the result. The bounded raw-socket
observer retains only ICMPv6 type, code, and reported MTU. On failure, only the failed phase,
cleanup state, and redacted daemon-log tails are exposed.

Successful output must pass
`schema/qualification/fips-g2-linux-direct-result.schema.json` and the repository contract before
it can be reviewed for retention. The workflow artifact expires after 14 days; it is not retained
evidence merely because the workflow passed.

## Privileged FIPS G2 Linux one-sided NAT runner

The manually dispatched `FIPS G2 Linux NAT Qualification` workflow extends the direct runner with
a third router namespace and two IPv4 segments. A default-deny forwarding policy permits new flows
from private node B to public node A, permits only stateful return traffic in the other direction,
and applies SNAT at the outside interface. Before starting FIPS, the runner proves that A cannot
open a new flow to B and B can reach A.

B must initiate the authenticated FIPS UDP link. The runner then requires A's peer view to observe
the translated source endpoint and repeats the direct runner's TUN, MTU, MMP, ICMPv6, deterministic
payload, FSP, disconnect, and teardown assertions. The retained result contains only booleans for
the directional and translated-path observations; it excludes identities and underlay endpoints.

Successful output must pass
`schema/qualification/fips-g2-linux-nat-result.schema.json` and the repository contract. This test
does not claim STUN, hole punching, symmetric-NAT, discovery, or relay qualification.

## Privileged FIPS G2 Linux managed-transit runner

The manually dispatched `FIPS G2 Linux Managed Transit Qualification` workflow creates three FIPS
nodes in a line across two IPv4 segments. Endpoint A and endpoint B each authenticate only to
managed transit node R. IPv4 forwarding on R is disabled, a direct endpoint underlay probe must
fail, and the authenticated peer/link counts must remain `[1, 2, 1]` with no direct A–B peer.

Each endpoint resolves the other endpoint's identity through its own FIPS DNS responder bound only
to `::1:5354`. This warms the identity cache needed for multihop route discovery without enabling
public discovery. The runner then requires:

- full MMP and SRTT visibility on all four adjacent-link views;
- ICMPv6 delivery at 32 and 1155 payload bytes from A through R to B;
- exact UDP echo at 1, 1024, and 1155 payload bytes;
- positive FIPS forwarding packet and byte counters at R;
- at least one FSP session at each endpoint and zero terminated FSP sessions at R; and
- acknowledged disconnects, empty peer/link sets, and complete namespace and process teardown.

Successful output must pass
`schema/qualification/fips-g2-linux-managed-transit-result.schema.json` and the repository
contract. This qualifies a static managed FIPS data-plane transit path. It does not qualify a Nostr
signaling relay, public discovery, NAT traversal, relay selection, failure behavior, or SRT media.

## Privileged FIPS G2 Linux lifecycle runner

The manually dispatched `FIPS G2 Linux Lifecycle Qualification` workflow freezes one direct
link-dead and daemon-restart experiment. It generates persistent FIPS keypairs only inside the
runner's mode-0700 temporary directory, configures A with B as a static `auto_connect` peer, and
requires the initial authenticated link, full MMP, exact UDP payloads, and FSP sessions before
injecting a failure.

The fault is an ungraceful `SIGKILL` of B with no protocol disconnect. A must independently remove
the peer, link, and FSP session within the 60-second observation budget configured around FIPS's
30-second link-dead timeout. An IPv6 probe must fail while B is absent. B is then restarted from the
same temporary identity; its public identity and derived mesh address must be unchanged, while its
daemon process changes. A must reconnect through FIPS's configured automatic retry path within 90
seconds. No `fipsctl connect` command is allowed before or after the fault.

After recovery, the runner repeats full-MMP, effective-MTU-boundary ICMPv6, exact deterministic UDP
echo, and FSP-session assertions. A final acknowledged control disconnect must remove peer, link,
and session state on both nodes. Success additionally requires the faulted process to have been
reaped, all live daemons stopped, both namespaces removed, and the entire persistent-identity
directory deleted.

Successful output must pass
`schema/qualification/fips-g2-linux-lifecycle-result.schema.json` and the repository contract. The
result retains elapsed milliseconds and booleans, but excludes private keys, public identities,
mesh and underlay addresses, process identifiers, raw payloads, and daemon logs. The budgets are
qualification stop conditions, not production SLOs. This single direct-path experiment does not
qualify alternate-route reconvergence, NAT rebinding, managed-transit failure, discovery, a
signaling relay, impaired networks, or SRT media continuity.

## Privileged FIPS G2 Linux alternate-route runner

The manually dispatched `FIPS G2 Linux Alternate Route Qualification` workflow creates an
authenticated four-node A–R1/R2–B FIPS diamond across four isolated IPv4 underlay segments. Both
transits have IPv4 forwarding disabled and no direct A–B underlay exists. Temporary persistent
identities are ordered by derived node address so A is the deterministic tree root. A 20 ms
one-way netem delay on each direction of the R2–B edge freezes R1 as B's active parent and R2 as an
already authenticated, higher-cost alternate; this is a route-selection control, not an
impaired-network claim.

Before failure, the runner requires two authenticated peers and links per node, full MMP on all
eight adjacent-link views, loopback-only endpoint identity registration, boundary-sized ICMPv6,
exact UDP echo, positive R1 forwarding deltas, zero R2 forwarding deltas, and endpoint-only FSP
termination. It then sends `SIGKILL` to R1 while leaving the underlay up. B must reparent to R2
within 60 seconds with a stable root and depth, increased tree declaration and parent-loss
telemetry, and no route or connect command.

The runner records that the original endpoint FSP session remains established during tree
reparenting but does not claim continuity. The pinned baseline retains stale coordinates until the
explicitly configured 90-second idle-session timeout removes the unused session. Subsequent TUN
traffic must automatically trigger discovery and a new FSP session over R2 with zero manual
session-reset commands. Boundary ICMPv6 and exact UDP payloads must then pass while R1 remains
unavailable, and R2 must expose positive forwarding deltas without terminating FSP.

Successful output must pass
`schema/qualification/fips-g2-linux-alternate-route-result.schema.json` and the repository
contract. The 60- and 180-second bounds are qualification stop conditions, not production SLOs.
This runner qualifies bounded FIPS connectivity recovery only. It explicitly does not qualify
hitless failover, SRT socket survival, downstream media timing, G6, G3, public discovery, NAT
rebinding, or impaired-network behavior.

## Privileged FIPS G2 Linux heterogeneous multihop-MTU runner

The manually dispatched `FIPS G2 Linux Multihop MTU Qualification` workflow reuses the isolated
three-node A–R–B managed-transit line while assigning UDP transport MTUs 1280/1000/1280 to A/R/B.
All three TUN interfaces stay at MTU 1280. Ordinary IPv4 forwarding on R remains disabled, no
direct A–B underlay exists, and endpoint identities are registered through loopback-only FIPS DNS.

The runner requires FIPS discovery to retain transport PMTU 1000 for the remote endpoint and both
endpoint FSP sessions to expose path MTU 1000. With the pinned 77-byte FIPS IPv6 overhead, this
produces an inner IPv6 path MTU of 923 bytes while the endpoint-local effective MTU remains 1203.
An ICMPv6 echo payload of 875 bytes must pass because it creates a 923-byte IPv6 packet. A payload
of 876 bytes creates a 924-byte packet and must receive no echo; the root-only observer must instead
receive ICMPv6 Packet Too Big type 2/code 0 reporting MTU 923. Boundary traffic must still pass
immediately afterward.

The runner also requires exact UDP echo at 1, 512, and 875 payload bytes, positive transit
forwarding counters, endpoint-only FSP termination, controlled disconnect, and complete namespace
and credential-directory teardown. Successful output must pass
`schema/qualification/fips-g2-linux-multihop-mtu-result.schema.json` and the repository contract.
This is one static proactive discovery/session PMTUD case. It does not qualify a changing physical
underlay MTU, lost PTB messages, NAT-specific PMTUD, SRT packetization, or media continuity.

## Reactive path-MTU experiment status

The follow-on attempt to lower an established A–R–B bottleneck at runtime is **not qualified**.
The stock FIPS `v0.4.2` daemon exposes no control operation that can change an active transport MTU
or invoke the library's runtime peer-update path. Restarting R invalidates the route state needed by
the first reactive packet; waiting for recovery instead lets discovery learn the smaller MTU
proactively. A concurrent TCP handshake also failed to migrate the active FMP link.

The failed experimental workflow is not kept on `main`. The reviewed observations, source-level
boundary, decision, and upstream acceptance contract are recorded in the
[reactive path-MTU capability-gap assessment](fips-g2-reactive-mtu-gap-2026-08-30.md). It is not
passing G2 or G6 evidence and does not weaken the retained static multihop-MTU result.

## Privileged FIPS G2 Linux fixed-delay MMP runner

The manually dispatched `FIPS G2 Linux Delay MMP Qualification` workflow freezes one direct-link
telemetry response experiment. It is not part of push or pull-request CI. The runner establishes a
two-node UDP FIPS link and endpoint FSP session with a one-second heartbeat interval, then requires
both full-MMP peer views to report baseline SRTT at or below 25 ms.

It applies Linux `tc netem` with a fixed 40 ms egress delay to both underlay directions and no
configured loss. Within 60 seconds both peer views must report SRTT between 55 and 200 ms and at
least 30 ms above their own baseline. Peer, link, and FSP session identity must stay unchanged while
effective-MTU-boundary ICMPv6 and exact UDP payloads of 1, 1024, and 1155 bytes pass. After removing
both qdiscs, both SRTT views must recover to at most 25 ms within a second 60-second budget without
replacing the FSP session.

Successful output must pass
`schema/qualification/fips-g2-linux-delay-mmp-result.schema.json` and the repository contract. The
result excludes identities, addresses, session timestamps, raw payloads, packets, and daemon logs.
This is one deterministic fixed-delay response test; it does not qualify loss, jitter, reordering,
duplication, corruption, bandwidth limits, queue pressure, route changes, NAT, SRT, or production
telemetry thresholds.

## Privileged FIPS G2 Linux fixed-loss MMP runner

The manually dispatched `FIPS G2 Linux Loss MMP Qualification` workflow freezes one direct-link
loss-telemetry response experiment. It is not part of push or pull-request CI. The runner establishes
a two-node UDP FIPS link and endpoint FSP session with a one-second heartbeat interval, then requires
both full-MMP peer views to report a baseline current loss rate at or below 0.01.

It applies seeded Linux `tc netem` with 20 percent random egress loss to both underlay directions and
sends 600 ICMPv6 overlay probes at 20 ms intervals. Within 60 seconds both peer views must report a
current loss rate from 0.05 through 0.60 and at least 0.04 above their own baseline. The aggregate
overlay probe loss must remain within a 10–70 percent sanity bound, while peer, link, and endpoint FSP
session identity remain unchanged. After removing both qdiscs, 300 recovery probes must return both
current loss views to at most 0.01 within a second 60-second budget without replacing the FSP session.
Effective-MTU-boundary ICMPv6 and exact UDP payloads of 1, 1024, and 1155 bytes are required after
recovery; stochastic loss deliberately carries no exact-delivery claim.

Successful output must pass
`schema/qualification/fips-g2-linux-loss-mmp-result.schema.json` and the repository contract. The
result excludes identities, addresses, session timestamps, raw payloads, packets, and daemon logs.
This is one seeded random-loss response test; the seed improves repeatability but does not freeze an
identical drop trace across kernels. It does not qualify bursts, jitter, reordering, duplication,
corruption, bandwidth limits, queue pressure, route changes, NAT, SRT, or production telemetry
thresholds.
