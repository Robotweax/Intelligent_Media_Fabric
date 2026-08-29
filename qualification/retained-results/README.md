# Retained results

The first retained record is the
[FIPS WP1 source/build assessment](2026-08-29-fips-source-build-assessment-macos-arm64.json). It
contains source, build, upstream-test, control-contract, and bounded macOS loopback observations.
It is partial G2 evidence, not SRT-over-FIPS qualification.

Do not commit generated output automatically. A retained result must pass review for provenance,
reproducibility, secrets, privacy, customer payload, size, licensing, and evidence classification.
Harness-only results are normally CI artifacts and do not belong here.

Retained FIPS assessment records must validate with:

```bash
PYTHONPATH=src python3 -m rimf_lab validate-fips-assessment \
  qualification/retained-results/2026-08-29-fips-source-build-assessment-macos-arm64.json
```
