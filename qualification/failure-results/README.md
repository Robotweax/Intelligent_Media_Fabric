# Failed qualification attempts

These are unchanged redacted failure artifacts, not passed qualification evidence.
The existing G2 retained-result validators intentionally accept only successful experiments;
do not relabel a failure or put it in the success-only retained-results set.

The 2026-09-19 alternate-route attempts failed during initial route setup and diamond
convergence respectively, both before fault injection. Consequently
`faulted_daemon_reaped: false` does not mean a killed daemon leaked:
no daemon had yet been faulted. The other three cleanup fields are true.
The artifact carries the runner revision, but the existing failure format omits dependency
and binary provenance; use the linked workflow run in the refresh assessment for that context.

The 2026-10-22 alternate-route attempt on FIPS v0.5.3
([run 39793279574](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/39793279574),
result and diagnostics files) converged, injected the relay fault, reparented and recovered
the overlay route, then failed in `post-failure-data-plane` because the harness required a
*new* FSP session (`session_start_changed_per_endpoint: [true, true]`) and v0.5.3 kept the
existing one. That requirement encoded the v0.5.1 teardown-and-rebuild observed on
2026-09-23; v0.5.3's changelog documents session re-lookup instead. The contract was then
extended to record `session_continuity` (`re-established` or `preserved`) rather than demand
one outcome; this artifact is retained unchanged and is evidence of neither recovery nor
continuity. Only one 5-second diagnostics sample exists because the run failed early.
