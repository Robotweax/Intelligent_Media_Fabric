# Third-party components and references

No third-party implementation source is vendored in this initial repository.

The project records external candidates in `dependency-pins/baselines.json` and uses their public
or authorized interfaces only. Each dependency remains governed by its own license and access terms.
Its presence in the pin file does not copy, redistribute, sublicense, or approve it for a product.

| Component | Initial treatment | Distribution status |
| --- | --- | --- |
| Robotweax SRT | External pinned build; public installed API | Not included |
| Robotweax SRT Telemetry | External pinned build; versioned C ABI candidate | Not included |
| FIPS | External pinned daemon through `fips0`; control-socket candidate | Not included |

Before a dependency is distributed, linked into a product, copied, patched, or vendored, record:

- the exact source and artifact revision;
- the applicable license and notices;
- the build and runtime linkage model;
- source-offer or attribution obligations, if any;
- cryptographic and export considerations;
- vulnerability and update ownership; and
- the upstream or fork maintenance plan.

GitHub Actions used by CI are pinned to immutable commits in the workflow. CI validates the harness;
it does not create retained SRT/FIPS qualification evidence.
