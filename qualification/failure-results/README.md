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
