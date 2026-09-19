# ADR-0005: Refresh SRT and FIPS qualification candidates

- Status: accepted
- Date: 2026-09-19
- Supersedes ADR-0003 for future qualification runs only

## Decision

Select Robotweax SRT main as observed on 2026-09-19 at
`def14a7b6d8a2ba1860677414e415fd86bbc953a` and FIPS v0.5.1 at
`c5aeef39ef9442d9e5047331156df368ace40cbd` for requalification.
Keep SRT Telemetry at `bf10da0431fdf23772210262755f745b62b6ff58`.
These are immutable candidates, not qualified replacements or gate passage.
Keep the historical development candidate research-only; it is not a current upstream head.

FIPS remains an external daemon with the transparent `fips0` data plane.
Explicitly disable the experimental native API and Nostr/LAN rendezvous in lab configurations.
No upstream patch, native-API migration, public discovery, or production route mutation is authorized.

## Reasons and migration

The prior SRT pin did not resolve through the upstream GitHub API on 2026-09-19.
Do not infer ancestry or rewrite the old provenance. The selected main includes the
acknowledged-source protection against delayed NAKs.

FIPS v0.5.1 includes mesh-lookup corrections and the Linux binary glibc packaging fix.
Version 0.5.0 also fixes path-MTU cache reseeding after transport changes.
Retest rather than carrying over v0.4.2 measurements.

- Update all nine Linux workflows, source guards, lockfile digest and versioned caches together.
- Keep Rust 1.94.1 and its existing toolchain-file digest; install Linux `libclang-dev`.
- Use SRT's default namespaced `librobotweax-srt.so`; report provider version 0.2.4.
- Build and run the pinned Telemetry test suite before the G4 capture.
- Use `node.rendezvous`, not deprecated `node.discovery`.
  Current collectors do not consume the renamed discovery/lookup metric family and
  do not filter old Rust tracing targets. Any future collector must use `lookup.*`.
- Preserve MTU, loss, timing and failover acceptance budgets. A failed new-version run
  must not silently loosen a bound.

## Evidence policy

Existing retained results and golden cases stay byte-for-byte unchanged and remain evidence
only for their recorded revisions. New runs must carry the new source and artifact digests.
G2 needs fresh direct/MTU, NAT, multihop, managed-transit, lifecycle, delay/loss and
alternate-route evidence. G3/G4 remain unpassed even after a successful healthy pilot.

See the [refresh assessment](../qualification/dependency-refresh-2026-09-19.md).

## Sources

- [Pinned SRT source](https://github.com/Robotweax/srt/tree/def14a7b6d8a2ba1860677414e415fd86bbc953a)
- [Pinned FIPS source](https://github.com/jmcorgan/fips/tree/c5aeef39ef9442d9e5047331156df368ace40cbd)
- [FIPS v0.5.0 release](https://github.com/jmcorgan/fips/releases/tag/v0.5.0)
- [FIPS v0.5.1 release](https://github.com/jmcorgan/fips/releases/tag/v0.5.1)
