# Dependency refresh assessment — 2026-09-19

Historical status at the time of the refresh. The private read secret was added on
2026-09-23 and the [healthy SRT-over-FIPS pilot](g4-live-capture-2026-09-23.md)
passed on the merged `main` revision. Subsequently, two
[v0.5.1 alternate-route attempts](fips-g2-linux-alternate-route-v0.5.1-2026-09-23.md)
passed after a fixed-parent harness assumption was corrected. The original
initial-route failure remains unclassified; the dated assessment below records
the earlier state and is not rewritten as a success.

Status: promotion blocked after partial requalification; no product gate passed.

## Selected sources

| Component | Immutable commit |
| --- | --- |
| Robotweax SRT (main snapshot, version 0.2.4) | def14a7b6d8a2ba1860677414e415fd86bbc953a |
| FIPS v0.5.1 | c5aeef39ef9442d9e5047331156df368ace40cbd |
| SRT Telemetry (unchanged) | bf10da0431fdf23772210262755f745b62b6ff58 |

FIPS Cargo.lock SHA-256: `77208a84234e33ed7fcf5b91c29f135e05a20bf23952066b28521b6e5985d24f`.
Rust toolchain SHA-256: `6a95738ee0eea5867a071922541a1ccaac80c63ccba5c947eb78b6130e1b22d3`.
Both were measured from the clean v0.5.1 checkout.

## Local verification

- macOS arm64, AppleClang 21.0.0, OpenSSL 3.6.3, Release shared SRT build succeeded.
- Pinned Telemetry compiled against the selected SRT public headers and namespaced library.
- Initial sandbox run: 39/42 tests passed; three local UDP tests failed at bind.
  Complete repeat with authorized local socket access: 42/42 tests passed (4.34 seconds).
- Fabric: 109 unit/contract tests passed; repository validation passed.
- Harness smoke passed (harness-only; not transport evidence).
- FIPS cannot be built locally in this environment: Cargo is absent and no Docker daemon is running.
  This is an environment limitation, not a successful FIPS runtime qualification.

## Linux qualification and remaining limits

All eight G2 workflows use the new source commit, Cargo.lock digest and cache key.
The G4 workflow also uses the selected SRT revision and namespaced library, and now runs the
complete pinned Telemetry test suite before capture.

The repository secret list was empty at inspection. G4 requires `ROBOTWEAX_REPO_TOKEN`
with read-only Contents access to Robotweax/srt and Robotweax/srt_telemetry.
No credential has been created, copied or exposed by this update.

Historical retained results were not rewritten. They do not qualify these new candidates.
The following Linux x86_64 runs used runner commit
`14a033a031fb37a415647490b98d43450e510bd1` with unchanged acceptance budgets.

| Scenario | Run | Outcome |
| --- | --- | --- |
| Direct + MTU boundary | [35456057093](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456057093) | passed |
| NAT | [35456098062](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456098062) | passed |
| Heterogeneous multihop MTU | [35456099672](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456099672) | passed |
| Managed transit | [35456101190](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456101190) | passed |
| Lifecycle | [35456102867](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456102867) | passed |
| Delay / MMP | [35456104542](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456104542) | passed |
| Loss / MMP | [35456106321](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456106321) | passed |
| Alternate route | [35456108334](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456108334) | failed during initial-data-plane |
| Alternate route, unchanged repeat | [35456568143](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456568143) | failed during diamond-convergence |
| SRT over FIPS | [35456305577](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/35456305577) | blocked at missing-token preflight |

Seven successful, schema-validated artifacts are retained under
`qualification/retained-results/2026-09-19-*-v0.5.1-x86_64.json`.
The failed attempt is preserved unchanged in
[failure-results](../../qualification/failure-results/2026-09-19-fips-g2-linux-alternate-route-v0.5.1-x86_64.json),
separate from the success-only retained-result contract. The
[unchanged repeat](../../qualification/failure-results/2026-09-19-fips-g2-linux-alternate-route-v0.5.1-x86_64-repeat.json)
is retained separately, not substituted for the first attempt.

The alternate-route run authenticated all four diamond links, observed MMP, and resolved endpoint
identities, but timed out waiting 45 seconds for the initial overlay route. It failed before the
relay outage was injected, so it provides no failover/recovery result. Logs contained UDP
send-buffer clamping warnings, but no evidence yet establishes these as the cause. Do not
declare this an upstream regression or relax the budget based on this observation.
The unchanged repeat timed out earlier, waiting 60 seconds for the authenticated diamond and
spanning-tree conditions. Thus both attempts failed before fault injection, but not in the same
phase. Startup/convergence remains unqualified; the existing bounded outputs do not establish
whether this is a harness assumption, convergence variability, or an upstream defect.

**Promotion is blocked:** diagnose the alternate-route failure and complete the SRT-over-FIPS
capture after the bounded private-read token is supplied. Keep the new pins classified as
requalification candidates. No upstream code was patched and main has not been merged.
Even a passing healthy G4 pilot does not pass G3/G4.

## Next bounded work

1. Instrument diamond setup with redacted per-node link/tree/route state and monotonic timestamps;
   reproduce without increasing any acceptance timeout.
2. If necessary compare the old and new FIPS releases under the same topology and runner conditions,
   keeping their evidence separate. Do not silently fall back to the old release.
3. Supply the repository-scoped private-read secret and rerun G4, including its Telemetry tests.
4. Obtain owner review before merging the update. Neither seven successful scenarios nor a green
   harness CI overrides the two failed diamond attempts or the missing cross-layer run.
