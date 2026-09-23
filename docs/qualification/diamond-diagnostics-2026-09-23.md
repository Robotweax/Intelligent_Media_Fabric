# Bounded four-node setup diagnostics

Two unchanged FIPS v0.5.1 alternate-route attempts on 2026-09-19 failed before
fault injection: one after link convergence while waiting for the initial overlay
route, and one while waiting for the authenticated diamond and tree. The existing
failure results do not contain enough control-plane state to distinguish a harness
assumption from startup variability or an upstream defect.

The diagnostic run records a sidecar `fips-g2-linux-alternate-route-result-diagnostics.json`
in the same GitHub Actions artifact as the qualification result. It samples no more
than once every five seconds and retains at most 32 samples, including a final failure
snapshot. Each sample has elapsed monotonic milliseconds, phase, four local node
roles and, when a probe was attempted, its exit code. The per-node projection
contains link/peer/session counts, peer roles, tree parent/root roles and counters,
and selected lookup/forwarding counters. Unknown identities become `unknown`.
Raw keys, npubs, node addresses, underlay addresses, control responses and logs
are not stored in this sidecar.

The sidecar is diagnostic evidence; it cannot turn a failed qualification into a
passed result.

## Observed on the pinned v0.5.1 build

[Workflow run 35866901080](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35866901080)
on project revision `46fbe7481a7ac11b8938c62162d331ef409a6c78` failed in
`diamond-convergence`, before any fault was injected. At 5.7 seconds and in every
subsequent sample through 60.7 seconds, all four nodes had two authenticated peers
and two links; the tree had root `a`, transit depths 1, endpoint depth 2, and endpoint
`b`'s parent was `r2`. The fixed test predicate required parent `r1`, so it rejected
this otherwise complete diamond until timeout. The 20 ms `tc netem` delay on the
`r2`-to-`b` segment is a fixed stimulus, not proof that FIPS will choose `r1` as
its tree parent. The sample does not establish why FIPS preferred `r2`.

The corrected qualification accepts either transit as the initial authenticated
parent, verifies which one actually forwarded the exact initial payload, kills that
transit, and still requires automatic reparenting, exact recovered delivery and the
original timing budgets. The topology, delay stimulus, timeouts and G2 acceptance
criteria remain unchanged. This corrects a harness assumption; it is **not** a
successful alternate-route qualification until a new live result passes. The
earlier initial-route failure is also still unclassified.
