# FIPS G2 Linux fixed-loss MMP qualification

- Date: 2026-08-30
- Gate: G2 FIPS Connectivity
- Result: passed fixed-loss MMP response slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `84c854e0e264951c9b828456c3fed92218badda2`
- Workflow run:
  [33307799473](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33307799473)
- Retained record:
  [Linux fixed-loss MMP result](../../qualification/retained-results/2026-08-30-fips-g2-linux-loss-mmp-x86_64.json)

## Question

Does the pinned FIPS baseline report a bounded, directional MMP current-loss response when
independent random loss is applied to an established direct link, while retaining the authenticated
peer, FMP link, and endpoint FSP session? Does the current-loss measurement recover after the
impairment is removed without replacing that session, and does exact boundary-sized delivery resume?

## Method and controls

The privileged workflow created two Linux network namespaces joined by one IPv4 veth pair. Each
namespace ran one unmodified, digest-checked FIPS daemon with `fips0` and UDP MTU 1280, full link and
session MMP, and a one-second heartbeat interval. Node A established the only authenticated UDP link
to B through the control socket. Overlay probes established one endpoint FSP session in each
direction.

Before impairment, both peer MMP views had to report a current loss rate no greater than 0.01. The
runner then installed a root `tc netem` qdisc with 20 percent independent random egress loss on both
veth directions. Both qdiscs had to be visible before measurement. The Ubuntu 24.04 runner's stock
iproute2 cannot seed netem's PRNG; the contract therefore measures and bounds the realized loss
instead of claiming an identical drop trace.

During 600 ICMPv6 overlay probes at 20 ms intervals, both full-MMP views had to report current loss
between 0.05 and 0.60 and at least 0.04 above their own baseline within 60 seconds. Aggregate overlay
loss had to stay between 10 and 70 percent. Peer/link/session counts and both FSP session start values
had to remain unchanged.

After removing and verifying removal of both qdiscs, 300 recovery probes had to return both current
loss views to at most 0.01 within 60 seconds with the same endpoint FSP sessions. Two
effective-MTU-boundary ICMPv6 echoes and exact UDP echo at 1, 1024, and 1155 payload bytes then had to
pass. Controlled disconnect and complete stimulus-process, qdisc, daemon, namespace, and temporary
identity-directory cleanup were mandatory.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| FIPS version | `0.4.2 (rev 487fa86f65)` |
| Topology | one authenticated direct UDP peer/link per node; one FSP session per endpoint |
| Baseline current loss A/B | `0.000000 / 0.000000` |
| Injected impairment | `tc netem`, 20% independent random egress loss in both directions |
| Degraded current loss A/B | `0.220779 / 0.155556` |
| Degraded convergence | 4,027 ms within the 60,000 ms bound |
| Realized overlay probe loss | 35.8333% across 600 requests |
| Session continuity | both endpoint session start values unchanged; peer/link/session counts `[1,1]` |
| Recovered current loss A/B | `0.000000 / 0.000000` |
| Recovery convergence | 6,285 ms within the 60,000 ms bound; both FSP session starts unchanged |
| Recovered boundary delivery | two 1155-byte ICMPv6 echo payloads passed |
| Recovered payload identity | exact UDP echo at 1, 1024, and 1155 payload bytes |
| Controlled disconnect | acknowledged; zero peers, links, and FSP sessions afterward |
| Teardown | both qdiscs absent, stimulus stopped, daemons stopped, namespaces and identity directory removed |

The retained file is byte-identical to the reviewed workflow artifact and has SHA-256
`19b2a1098b9ce380aecd536e70136fb264a6810c1c0de0e11cfafd356c845447`. It excludes private keys,
public identities, mesh and underlay addresses, session timestamps, process identifiers, raw
payloads, packets, control responses, and daemon logs.

## Interpretation

This closes one independent-random-loss telemetry slice of G2. On the pinned Linux runner class,
FIPS MMP moved both peer current-loss observations across the predeclared degraded threshold,
preserved the active connectivity and endpoint FSP sessions, and returned both observations to zero
after the qdiscs were removed. Boundary ICMPv6 and exact UDP identity then confirmed recovered data
delivery.

The reported aggregate overlay loss is expected to exceed either one-way 20 percent setting because
an echo request and its reply traverse independently impaired egress paths. It is a measured sanity
bound, not an exact probability assertion. `smoothed_loss` remained nonzero after current-loss
recovery, consistent with an EWMA retaining history; it is retained diagnostically but is not the
recovery gate. The loss thresholds and 60-second budgets are controls for this runner class, not
production SLOs.

No burst model, jitter, reordering, duplication, corruption, bandwidth cap, queue pressure, route
change, NAT, discovery service, process restart, or Robotweax SRT stream was exercised. Exact UDP
identity was intentionally tested after impairment removal, not asserted during stochastic loss. G2
therefore remains open for broader traversal/discovery and additional impairment and resource-bound
classes.
