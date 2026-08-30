# FIPS G2 Linux fixed-delay MMP qualification

- Date: 2026-08-30
- Gate: G2 FIPS Connectivity
- Result: passed fixed-delay MMP response slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `a68cf0958f1e71b51dda1f2eaa5703cd4140e775`
- Workflow run:
  [33305791869](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33305791869)
- Retained record:
  [Linux fixed-delay MMP result](../../qualification/retained-results/2026-08-30-fips-g2-linux-delay-mmp-x86_64.json)

## Question

Does the pinned FIPS baseline report a bounded, directional MMP SRTT response when a fixed delay
is applied to an established direct link, while retaining the authenticated peer, FMP link,
endpoint FSP session, effective-MTU delivery, and exact payload identity? Does the measurement
recover after the impairment is removed without replacing that session?

## Method and controls

The privileged workflow created two Linux network namespaces joined by one IPv4 veth pair. Each
namespace ran one unmodified, digest-checked FIPS daemon with `fips0` and UDP MTU 1280, full link
and session MMP, and a one-second heartbeat interval. Node A established the only authenticated UDP
link to B through the control socket. A small overlay probe established one endpoint FSP session in
each direction.

Before impairment, both peer MMP views had to report SRTT no greater than 25 ms. The runner then
installed a root `tc netem` qdisc with exactly 40 ms fixed egress delay and zero configured loss on
both veth directions. Both qdiscs had to be visible before measurement.

Within 60 seconds, both full-MMP views had to report SRTT between 55 and 200 ms and at least 30 ms
above their own baseline. While the delay remained active, peer/link/session counts and both FSP
session start values had to remain unchanged. Two effective-MTU-boundary ICMPv6 echoes and exact
UDP echo at 1, 1024, and 1155 payload bytes then had to pass.

After removing and verifying removal of both qdiscs, both MMP views had to recover to at most 25 ms
within 60 seconds with the same endpoint FSP sessions. Controlled disconnect and complete qdisc,
daemon, namespace, and temporary identity-directory cleanup were mandatory.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| FIPS version | `0.4.2 (rev 487fa86f65)` |
| Topology | one authenticated direct UDP peer/link per node; one FSP session per endpoint |
| Baseline peer SRTT A/B | `1.000 / 2.000 ms` |
| Injected impairment | `tc netem`, 40 ms fixed one-way egress delay in both directions, 0% configured loss |
| Degraded peer SRTT A/B | `57.136 / 57.185 ms` |
| Degraded convergence | 14,882 ms within the 60,000 ms bound |
| Session continuity | both endpoint session start values unchanged; peer/link/session counts `[1,1]` |
| Effective-MTU delivery under delay | two 1155-byte ICMPv6 echo payloads passed |
| Payload identity under delay | exact UDP echo at 1, 1024, and 1155 payload bytes |
| Recovered peer SRTT A/B | `18.915 / 24.234 ms` |
| Recovery convergence | 18,028 ms within the 60,000 ms bound; both FSP session starts unchanged |
| Controlled disconnect | acknowledged; zero peers, links, and FSP sessions afterward |
| Teardown | both qdiscs absent, daemons stopped, namespaces and identity directory removed |

The retained file is byte-identical to the reviewed workflow artifact and has SHA-256
`af8805971087027419d7cf7eb4579d3651f1f8cfb397be46e27f4c22d9936c5a`. It excludes private keys,
public identities, mesh and underlay addresses, session timestamps, process identifiers, raw
payloads, packets, control responses, and daemon logs.

## Interpretation

This closes one deterministic fixed-delay telemetry slice of G2. On the pinned Linux runner class,
FIPS MMP moved both peer SRTT observations across the predeclared degraded threshold, preserved the
active connectivity and endpoint FSP sessions, carried exact boundary-sized data, and returned both
observations below the recovery threshold after the qdiscs were removed.

The observed degraded SRTT is not asserted to equal the configured 80 ms round-trip sum: the test
qualifies threshold response and recovery, not estimator calibration against a laboratory clock.
The 25/55/200 ms thresholds and 60-second budgets are controls for this runner class, not production
SLOs.

No loss, jitter, reordering, duplication, corruption, bandwidth cap, queue pressure, route change,
NAT, discovery service, or Robotweax SRT stream was exercised. G2 therefore remains open for
broader traversal/discovery, additional impairment and resource-bound classes. Reactive path-MTU
change remains separately blocked by the documented stock-daemon capability gap.
