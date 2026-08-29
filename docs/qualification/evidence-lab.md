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
