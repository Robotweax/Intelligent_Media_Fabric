# G5 SRT-group comparison, stage 2: group over two FIPS overlays — predeclared experiment contract

Status: predeclared on 2026-11-14, before any run. No retained run yet. It changes no gate.

Follows [stage 1](g5-srt-group-comparison-2026-11-14.md) and the
[design draft](srt-group-comparison-design-2026-11-13.md). Serves OD-15, OD-11 and G5.

## Why

Stage 1 showed that an SRT group with two members on independent paths is hitless when one
transit is blackholed, on plain routed IPv6. The single-session runs over FIPS showed gaps of
about 5 s and 32 s for the same fault. Neither shows the combination: FIPS for identity,
encryption and reachability, and a group for continuity. Stage 2 measures that combination
with the same stream, fault and downstream measurement.

## Question

When each member of an SRT group runs over its own FIPS overlay and one overlay loses its
transit completely and silently, what does the independent downstream collector see?

## The obstacle, and what a feasibility probe found

A FIPS node has one identity, one address and one route to a peer. Two members between the
same two FIPS addresses share that route. Each endpoint therefore needs two FIPS identities.

The design draft left open whether two pinned FIPS daemons can share a namespace. A local
probe on 2026-11-14 (FIPS v0.5.3 `f4a5b4a8`, privileged Linux aarch64 container, two
namespaces with two links, no SRT, no media) found:

- **Unmodified, they cannot.** Each daemon installs the route `fd00::/8` on its own TUN
  device in the main table. The second daemon's route add fails with `File exists`, its TUN
  stays `failed` and the node starts degraded. The TUN name, control socket and UDP bind
  address are configurable and did not collide.
- **With one lab step, they can.** When the lab deleted the first daemon's `fd00::/8` route
  before starting the second, both TUNs became `active`. With both prefix routes then removed
  and one `/128` route per remote overlay address on the matching TUN, each overlay carried
  ping in both directions, an address of one overlay did not reach an address of the other,
  the effective path MTU was 1203 as in the retained runs, and a blackhole of one link
  stopped only that overlay.

The probe is a feasibility check, not an experiment under this contract. Its output is not
retained and is not evidence.

## Fixed setup

| Element | Value |
| --- | --- |
| Pins | Robotweax SRT v0.3.2 `e45d0edd`, SRT Telemetry `d03ca452`, FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`. All binaries unmodified. |
| Topology | The diamond's four namespaces `a`, `r1`, `r2`, `b` and four veth links with the IPv4 underlay of the faulted diamond. Kernel forwarding off on the transits. |
| FIPS | Six daemons, two separate overlays. Overlay 1: `a`/1, `r1`, `b`/1. Overlay 2: `a`/2, `r2`, `b`/2. Each endpoint daemon peers only with its own transit and binds its UDP transport to the underlay address of that link. No daemon of one overlay is a peer of the other. |
| Endpoint routing | The lab step from the probe: on `a` and `b`, the `fd00::/8` routes that FIPS installs are removed, and one `/128` route per remote overlay address points at the matching TUN. FIPS's own rule and addresses stay. |
| FIPS timers | The frozen `g2-alternate-route` profile (link-dead 30 s). Each overlay has one route, so the timer decides when FIPS reports the loss, not when media recovers. |
| SRT | One group from `a` to `b`, live mode, message API. Member 0 between the overlay-1 addresses with weight 20, member 1 between the overlay-2 addresses with weight 10. SRT's defaults otherwise: peer idle 5 s. |
| Group mode | `broadcast` or `backup`, one job each. |
| Path stimulus | 20 ms one-way delay on both ends of `r2`–`b`, unchanged. |
| Stream | The faulted diamond's fixture, unchanged: 160 s MPEG-TS, 4000 frames, 1128-byte datagrams, 1 Mbit/s; independent source, collector, decode and frame comparison. |
| Fault | `transit-blackhole` of `r1`, 20 s after the source starts, as in stage 1 and the blackhole variant. Nothing is restored. |
| Sampling | Every 500 ms: one group sample per endpoint with each member's state and SRT sample. About every 1 s: FIPS control state of the four endpoint daemons and the two transits. One coordinator clock. |

## Stop rules

A run fails when one of these does not hold:
1. All six FIPS daemons report an active TUN, and each overlay's peers and tree are the three
   nodes intended.
2. Before the stream starts, an address of overlay 1 does not reach an address of overlay 2,
   and `a` does not reach `b` over the IPv4 underlay.
3. The media datagram fits the clear SRT payload budget of both overlays, as computed in the
   faulted diamond.
4. Stage 1's rules 1 to 6, unchanged: both members connect and match by address; media flows
   before the fault with the member states the mode implies; the blackhole is in place and
   dropped packets; the listener's member 0 stops receiving within 2 s; the group stays
   connected to the end; no sampling interval is missed and teardown is complete.
5. Overlay 2 reports no link loss and no tree change during the whole run.

A gap, missing frames or changed frames do not fail a run. They are the result.

## What is recorded and reported

Everything stage 1 reports, plus the interval in which overlay 1's endpoint daemons report
the link loss. Hitless by ADR-0012's definition is applied and reported, not enforced. The
result stands beside stage 1 and the single-session FIPS runs, ungraded.

The bundle is stage 1's 21 files plus `fips-observations.jsonl`, and `result.json`. A passing
run records `G5: not-passed`; G5 stays `in-progress`.

## Known before any run, and not compensated

- **The endpoint routing is a lab workaround.** FIPS v0.5.3 does not support two daemons in
  one namespace. The lab removes a route FIPS installed and adds its own. A result shows
  what the combination can do once that is solved; it does not show that FIPS supports it.
  A product would need this from FIPS itself, or one identity with two usable paths.
- **Two identities per endpoint.** The group's members have different FIPS addresses on each
  side. How an application learns and authorises the second identity is not addressed.
- **Each overlay has exactly one route.** FIPS reconvergence is not exercised. If each
  overlay could also use the other transit, both could choose the same one, which is one
  fault domain under two labels.
- **Independence is topological,** as in stage 1: one host, one kernel, one clock, and four
  of the six daemons share two namespaces.
- **Broadcast doubles the wire bytes,** now including FIPS overhead on both paths. Stage 1
  showed Backup also sends on both members for about 5 s after the fault.
- **Prediction, not a requirement:** both modes hitless, as in stage 1. The group's packets
  are the size of the single-session packets, so the 1203-byte path should not matter, but
  the group handshake is larger and is checked only by the run.
- One fault class. Killing the `r1` daemon is now possible again and is left out to keep one
  change against stage 1.

## Owner decisions, 2026-11-14

The owner accepted the draft of this contract as proposed:

1. The endpoint routing workaround is accepted for this experiment, with the limit stated
   above. No FIPS fork or patch.
2. One FIPS timer profile, the frozen `g2-alternate-route` profile.
3. One fault, the blackhole of `r1`.
4. The runner, validator and workflow are built after this contract is committed.

Whether stage 2, once retained, closes OD-15 or OD-11 stays an owner decision.
