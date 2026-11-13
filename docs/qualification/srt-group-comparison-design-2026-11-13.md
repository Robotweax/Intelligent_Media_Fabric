# SRT-group comparison: design draft — 2026-11-13

- Status: design draft. It is not a predeclaration: no runner exists and nothing has run.
  The experiment contract will be predeclared in its own plan before the first run.
- Serves OD-15 (response to non-hitless FIPS recovery), OD-11 (group topologies with
  independent fault domains) and G5. It changes no gate.

[ADR-0012](../decisions/0012-interruption-budget.md) sets a hitless target for the loss of one
transit. No single SRT session over FIPS met it. The architecture already names SRT connection
groups as the first resilience baseline, against which FIPS reconvergence is to be judged.
This draft says how to measure that baseline in the same lab.

## Question

With the same stream, the same fault and the same downstream measurement as the faulted
diamond: what does the collector see when the stream runs over an SRT group with one member
per transit?

## Why the current diamond cannot answer it

Each node has one `fips0` address and FIPS picks one route to it. Two group members between
the same two FIPS addresses would share that route and fail together. That is one fault
domain under two labels, which the architecture rules out. Each member needs its own path.

## Stage 1: group over the underlay, no FIPS

The baseline the architecture asks for. Same four namespaces and veth links.

| Element | Faulted diamond (retained) | Stage 1 |
| --- | --- | --- |
| FIPS daemons | on all four nodes | none |
| Transits | FIPS forwarding, kernel forwarding off | kernel forwarding on, static routes |
| SRT | one session `a` to `b` over `fips0` | one group, two members: via `r1` and via `r2` |
| Addresses | `fips0` IPv6 | IPv6 on the veth links, as in the G1 control |
| Stream, source, collector, decode | 160 s MPEG-TS, 1128-byte datagrams | unchanged |
| Alternate-path stimulus | 20 ms one way on `r2`–`b` | unchanged, so the two members differ by 20 ms |
| Fault | SIGKILL or blackhole of the active transit | blackhole of `r1`, the lower-delay path, 20 s after the source starts |
| Sampling | SRT 500 ms per endpoint, FIPS 1 s | SRT 500 ms per member; no FIPS stream |

The fault has to be the blackhole. Killing a FIPS daemon means nothing without FIPS, and the
[blackhole run](g4-faulted-diamond-blackhole-2026-11-13.md) showed it equals the kill for the
single-session case, so the retained FIPS gaps are the comparison.

Group modes, one job each:
- **Broadcast:** every packet on both members. Expected to be hitless. Costs twice the wire bytes.
- **Backup:** one active member, one standby. The gap is the time the group takes to declare
  the active member unusable and switch. That time is not known for the pinned SRT and is
  what the job measures.

Reported per job: missing and changed frames, the downstream gap if any, per-member SRT
samples around the fault, and wire bytes per member. Judged against ADR-0012: hitless means
no missing and no changed frame.

Stage 1 says what groups give on plain IP paths. It does not involve FIPS at all, so on its
own it compares two alternatives; it does not show them working together.

## Stage 2: group over two FIPS routes

The combination a product would use: FIPS for identity and reachability, a group for
continuity. Each endpoint would run two FIPS daemons with separate identities and TUN
devices, one mesh through `r1` and one through `r2`, and the group would have one member per
overlay. Whether two pinned FIPS daemons can share a namespace this way has not been
checked. Stage 2 is designed only after Stage 1 has run.

## What has to change, and where

**SRT:** nothing. The pinned v0.3.2 exports the Broadcast and Backup group API
(`srt_create_group`, `srt_connect_group`, `SRTO_GROUPCONNECT`, `srt_group_data`).

**SRT Telemetry (its own repository and review rules; public since 2026-11-13):** the incident
peer opened one socket when this draft was written. It needs a group mode, proposed in
[Robotweax/srt_telemetry#75](https://github.com/Robotweax/srt_telemetry/pull/75):
- caller: a group type and one local/remote address pair per member;
- listener: accept a group connection;
- media relay over the group socket, unchanged in what it forwards;
- samples that identify the member they describe, and the member's group state.

The proposed change keeps the recording format: each member is recorded to its own `1alpha1`
file, so Fabric's adapter reads member recordings as it reads single-socket ones
([ADR-0004](../decisions/0004-srt-telemetry-adapter-boundary.md) is untouched). Using it still
needs a Telemetry pin change and an ADR here once it is merged.

**Fabric:** a new runner beside the faulted diamond that reuses its source, collector, decode,
frame comparison and blackhole; a result contract for group runs; a workflow.

## Known before any run

- Broadcast doubles the bytes on the wire. A hitless broadcast result is a result at that cost.
- Both members cross the same two endpoints. Endpoint failure is outside this experiment.
- The lab paths are veth pairs on one host. Independence here means separate transits and
  links, not separate providers.
- One fault class, full and two-way. Partial loss on one member is a different experiment.

## Decisions needed before building

1. Go-ahead for the Telemetry incident-peer change, in that repository and under its rules.
2. Whether Stage 1 alone may close OD-15, or Stage 2 is required first.
