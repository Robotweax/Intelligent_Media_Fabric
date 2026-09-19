# Dependency refresh assessment — 2026-09-19

Status: requalification in progress; no product gate passed.

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
- Fabric: 107 unit/contract tests passed; repository validation passed.
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
New Linux run outcomes must be recorded here before claiming G2 coverage for v0.5.1.
Even a passing healthy G4 pilot does not pass G3/G4.
