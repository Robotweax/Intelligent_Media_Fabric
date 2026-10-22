# FIPS v0.5.3 four-node alternate-route qualification

The [Linux workflow run 39796547753](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/39796547753)
passed on project revision `9ab26fa92b0b96e9c5e0f0ed3da247201aa7df19`
with pinned FIPS `f4a5b4a8e61e340e6be7551608109a5c399f8353` (v0.5.3),
x86_64 Linux. The complete reviewed-shape result is retained at
[`qualification/retained-results/2026-10-22-fips-g2-linux-alternate-route-v0.5.3-x86_64.json`](../../qualification/retained-results/2026-10-22-fips-g2-linux-alternate-route-v0.5.3-x86_64.json).
The workflow validated the result; repository validation also checks it.

The four-node UDP diamond formed with two authenticated peers and links per
node. Endpoint `b` chose `r1` as tree parent; during the initial exact echo
probe only `r1` forwarded (six packets, 5,166 bytes) while `r2` forwarded
nothing, so this run does show exclusive initial forwarding through the
observed parent. The harness killed `r1` with `SIGKILL` and confirmed the
immediate outage probe was blocked. `b` automatically reparented to `r2` in
31.733 seconds, within the 60-second budget. The established endpoint FSP
sessions remained present through reparenting and, unlike v0.5.1, were
**preserved** afterwards: no session restart occurred (`session_continuity:
preserved`, `session_start_changed_per_endpoint: [false, false]`, 115 control
polls at 250 ms). Exact post-failure delivery traversed `r2` in 39.261 seconds
from failure, within the 180-second budget. No manual connect/route/session
reset was issued, and cleanup passed.

Compared with the retained [v0.5.1 result](fips-g2-linux-alternate-route-v0.5.1-2026-09-23.md)
(reparent 31.436 s, payload recovery 92.896 s after a 90-second idle-timeout
session restart), reparenting time is unchanged and payload recovery is
roughly 54 seconds faster because the session no longer waits for idle expiry.
This matches the v0.5.3 changelog entry that an established session which loses
its route looks the destination up again instead of staying dark. It is one
run on each revision, not a statistical comparison.

## First attempt and contract change

The first v0.5.3 attempt, [run 39793279574](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/39793279574),
is [retained as a failure](../../qualification/failure-results/README.md). It
reached the same recovered route and then failed in `post-failure-data-plane`
because the contract required a new session per endpoint, a requirement that
had frozen the v0.5.1 teardown-and-rebuild. The harness, validator and schema
were extended in `9ab26fa9` to record `session_continuity` with consistent
companion fields; results without the field keep the historical meaning and the
v0.5.1 evidence validates unchanged. No budget was loosened.

## Limits

This is one successful, bounded **G2 connectivity/recovery** experiment on
v0.5.3, not a hitless continuity claim. A preserved FSP session says nothing
about the roughly 39 seconds during which no payload was delivered, about SRT
socket or media continuity, G6 route change, NAT rebinding, public discovery,
Nostr relays, heterogeneous PMTUD or impaired links. OD-15 remains open: the
v0.5.1 observation it was raised on is superseded by this one as the current
FIPS behaviour, but the SRT/media resilience comparison it asks for has not
been run. G2 remains `in-progress`.
