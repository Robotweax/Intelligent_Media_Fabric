# ADR-0014: Continuity across a path loss comes from an SRT group; FIPS recovery is recovery

- Status: accepted
- Date: 2026-11-14
- Closes OD-15 (response to non-hitless FIPS alternate-route recovery). OD-11, OD-10, OD-07 and OD-01 stay open. ADR-0012's budgets are retained unchanged.

## Decision

OD-15 required an ADR selecting improvement, bounded workaround or pivot. The repository
owner chose, on 2026-11-14, answer A of the
[proposal](proposal-od15-resilience-response-2026-11-14.md): the **bounded workaround**.

1. **Continuity for the loss of one path is provided by an SRT connection group with one
   member per independent path.** A hitless claim is only ever made for a group arrangement.
2. **FIPS reconvergence is not a continuity mechanism.** A single SRT session over FIPS is
   judged against ADR-0012's 6 s single-path floor, not against the hitless target. G6 keeps
   that budget.
3. **The group over FIPS is demonstrated, not supported.** Until FIPS offers two usable
   identities or two usable paths per host, a group over FIPS rests on a lab routing step and
   may be described only with that limit.
4. **No FIPS fork and no patch stack.** The missing capability is to be taken to the FIPS
   project as a request. A fork would need its own ADR.
5. **Making FIPS recovery itself hitless is not pursued.** Shorter FIPS timers remain worth
   qualifying for the single-path floor, as ADR-0012 says; that is separate work.

## Basis

Retained evidence only; one diamond, one stream at 1 Mbit/s, one fault class (the transit
carrying the stream is lost), measured at an independent downstream collector.

| Arrangement | Downstream gap | Frames missing of 4,000 | Retained runs |
| --- | --- | --- | --- |
| One session over FIPS, link-dead 30 s (stock), SRT peer idle 60 s | 31.2 to 32.5 s | 757 to 789 | 10 |
| One session over FIPS, link-dead 3 s, SRT peer idle 60 s | 4.2 to 5.3 s | 83 to 109 | 8 |
| One session over FIPS, both products at stock settings | media does not return | 3,501 | 8 |
| SRT group, one member per transit, routed IPv6, no FIPS ([stage 1](../qualification/g5-srt-group-comparison-2026-11-14.md)) | none | 0 | 2 |
| SRT group, one member per FIPS overlay ([stage 2](../qualification/g5-srt-group-over-fips-2026-11-14.md)) | none | 0 | 2 |

The gap of a single session tracks the FIPS link-dead timer, because a loss has to be detected
before a route can change. No timer makes that zero. The group was hitless in Broadcast and in
Backup, with and without FIPS underneath; in stage 2 FIPS reported the lost link after 31 to
32 s while the stream continued on the other member.

The alternatives were rejected on the same evidence. Improving FIPS recovery cannot reach the
hitless target ADR-0012 set. Taking FIPS off the continuity path reaches it, but gives up
identity, encryption and reachability, which a group over FIPS keeps.

## Consequences

- OD-15 is closed. It no longer blocks G6. G6 stays `not-started`: its question is whether a
  single stream survives a route change within the 6 s floor, and OD-16 still blocks the
  reactive path-MTU part.
- G5 carries the continuity claim and stays `in-progress`. This ADR passes no gate.
- A product statement about hitless operation over FIPS is not available yet. What is
  retained is a lab arrangement with two FIPS daemons per endpoint and a routing step
  FIPS v0.5.3 does not provide.
- The two things a product needs from FIPS are named: either an option that leaves the
  `fd00::/8` route to the operator, so two daemons can share a host, or one identity with two
  disjoint paths to a peer.

## Not decided here

The proposal asked three further questions. They were not answered with this decision and
stay open:

1. Whether to draft the FIPS capability request as a document in this repository (OD-10).
   Sending anything upstream is a separate, explicit owner step.
2. Whether OD-11 stays open. It is unchanged by this ADR: the lab's two paths are separate
   transits and links on one host, and the architecture asks for physical or administrative
   independence.
3. What G5 needs before it can pass, and in which order. The proposal lists repeats, a member
   that rejoins, partial and one-way loss on one member, the higher pilot rate, and faulting
   the slower path.

Also open: the choice between Broadcast and Backup, which belongs to the pilot profile
(OD-01), and how a peer's second identity is learned and authorised (OD-07).

## Limits

- The group rows are one run per mode and stage, on one host with one kernel and one clock.
- One fault class, full and two-way. A degraded member is untested.
- "Hitless" is ADR-0012's definition at the downstream collector, not a statement about a
  live player.
- This is not a verdict on FIPS. Its retained behaviour matches its documented timers.
