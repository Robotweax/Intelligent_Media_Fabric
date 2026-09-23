# Bounded four-node setup diagnostics

Two unchanged FIPS v0.5.1 alternate-route attempts on 2026-09-19 failed before
fault injection: one after link convergence while waiting for the initial overlay
route, and one while waiting for the authenticated diamond and tree. The existing
failure results do not contain enough control-plane state to distinguish a harness
assumption from startup variability or an upstream defect.

The next run records a sidecar `fips-g2-linux-alternate-route-result-diagnostics.json`
in the same GitHub Actions artifact as the qualification result. It samples no more
than once every five seconds and retains at most 32 samples, including a final failure
snapshot. Each sample has elapsed monotonic milliseconds, phase, four local node
roles and, when a probe was attempted, its exit code. The per-node projection
contains link/peer/session counts, peer roles, tree parent/root roles and counters,
and selected lookup/forwarding counters. Unknown identities become `unknown`.
Raw keys, npubs, node addresses, underlay addresses, control responses and logs
are not stored in this sidecar.

The qualification topology, timeouts and acceptance conditions are unchanged.
The sidecar is diagnostic evidence; it cannot turn a failed qualification into a
passed result. Compare samples with the exact workflow revision and pinned FIPS
binary before proposing any fix.
