# Evidence Lab

## Purpose

The lab converts integration hypotheses into retained, reproducible evidence. It distinguishes
harness qualification from media-transport qualification and records missing observations as
missing rather than zero.

## Initial harness

The Python harness uses only the standard library. It:

- validates immutable dependency pins and repository JSON contracts;
- loads a reviewed scenario;
- executes commands as argument arrays without a shell;
- uses a small sanitized environment;
- enforces per-case timeouts and bounded output capture;
- records hashes and byte counts instead of raw stdout and stderr;
- records platform, project revision, scenario digest, and baseline digest; and
- writes a result atomically.

It does not configure TUN devices, namespaces, netem, NAT, packet capture, FIPS, or SRT. Those
adapters are later WP1-WP3 work and require explicit privilege boundaries.

## Commands

```bash
make check
make smoke

PYTHONPATH=src python3 -m rimf_lab validate-scenario \
  qualification/scenarios/harness-smoke.json

PYTHONPATH=src python3 -m rimf_lab run \
  --scenario qualification/scenarios/harness-smoke.json \
  --output artifacts/harness-smoke-result.json
```

The included smoke scenario is classified `harness-only`. Its result must never be cited as SRT,
FIPS, networking, performance, security, or continuity evidence.

## Real experiment requirements

Before adding a real scenario:

1. freeze the question, topology, inputs, stop condition, and expected downstream validator;
2. reference exact build and dependency artifacts;
3. select an approved gate from the gate registry;
4. use deterministic test and fault seeds;
5. predeclare repetitions and evaluation logic;
6. review every command and required privilege;
7. ensure output cannot contain secrets or customer payload; and
8. retain external binary logs separately under an approved retention policy.

Raw evidence is not committed by default. A retained result requires review for size, licensing,
privacy, secrets, and reproducibility before it enters `qualification/retained-results/`.

## Privileged FIPS G2 Linux direct runner

The manually dispatched `FIPS G2 Linux Direct Qualification` workflow is the first privileged
network adapter. It is not part of push or pull-request CI. It:

- fetches only FIPS `v0.4.2` at the ADR-0003 commit and verifies the Cargo lockfile and
  toolchain-file digests before building with `--locked`;
- creates two temporary Linux network namespaces joined by one IPv4 veth underlay;
- starts one FIPS daemon per namespace with TUN enabled, DNS disabled, and ephemeral identities;
- confirms `fips0`, kernel and effective MTU, an authenticated UDP link, and full MMP visibility;
- sends ICMPv6 below and at the effective inner-MTU boundary;
- verifies exact deterministic UDP echo digests at 1, 1024, and 1155 payload bytes;
- observes an FSP session, performs a control-socket disconnect, and checks peer/link removal; and
- stops processes and removes namespaces and the temporary identity directory before reporting
  success.

The runner requires Linux root only for namespace and TUN setup. Its host-visible state is bounded
to the temporary veth setup, `/tmp` work directory, and the requested result path; teardown verifies
that the processes, namespaces, and identity directory are gone. Private keys, npubs, addresses,
raw payloads, and daemon logs are excluded from the result. On failure, only the failed phase,
cleanup state, and redacted daemon-log tails are exposed.

Successful output must pass
`schema/qualification/fips-g2-linux-direct-result.schema.json` and the repository contract before
it can be reviewed for retention. The workflow artifact expires after 14 days; it is not retained
evidence merely because the workflow passed.
