# FIPS v0.5.1 four-node alternate-route qualification

The [Linux workflow run 35868354910](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35868354910)
passed on project revision `650999634acf34bed5a7ea778f84de0f035df4fb`
with pinned FIPS `c5aeef39ef9442d9e5047331156df368ace40cbd` (v0.5.1),
x86_64 Linux. The complete reviewed-shape result is retained at
[`qualification/retained-results/2026-09-23-fips-g2-linux-alternate-route-v0.5.1-x86_64.json`](../../qualification/retained-results/2026-09-23-fips-g2-linux-alternate-route-v0.5.1-x86_64.json).
The workflow validated the result; repository validation also checks it.

The four-node UDP diamond formed with two authenticated peers and links per
node. Endpoint `b` chose `r2` as tree parent even with the configured 20 ms
`r2`–`b` delay stimulus. Both transit forwarding counters increased during the
initial exact echo probe (three packets and 2,583 bytes each); thus the
observation does **not** prove exclusive initial forwarding through `r2`.
The harness killed `r2`, the observed parent, with `SIGKILL` and confirmed the
immediate outage probe was blocked. `b` automatically reparented to `r1` in
31.436 seconds, within the 60-second budget. The established endpoint sessions
remained present through reparenting, then restarted automatically after the
configured 90-second idle timeout. Exact post-failure delivery traversed `r1`
in 92.896 seconds from failure, within the 180-second budget. No manual
connect/route/session reset was issued, and cleanup passed.

This is one successful, bounded **G2 connectivity/recovery** experiment, not a
hitless continuity claim. It does not qualify SRT media continuity, G6 route
change, NAT rebinding, public discovery, Nostr relays, heterogeneous PMTUD, or
impaired links. G2 remains `in-progress`: the earlier v0.5.1 initial-route
failure is unclassified, and this single successful run does not replace the
remaining required G2 evidence.
