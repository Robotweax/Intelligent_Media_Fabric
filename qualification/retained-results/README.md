# Retained results

The first retained record is the
[FIPS WP1 source/build assessment](2026-08-29-fips-source-build-assessment-macos-arm64.json). It
contains source, build, upstream-test, control-contract, and bounded macOS loopback observations.
It is partial G2 evidence, not SRT-over-FIPS qualification.

The
[FIPS G2 Linux direct result](2026-08-29-fips-g2-linux-direct-x86_64.json) adds retained two-node
`fips0`, effective-MTU payload identity, FSP observation, disconnect, and teardown evidence.

The schema-v2
[FIPS G2 Linux MTU-boundary result](2026-08-30-fips-g2-linux-direct-mtu-boundary-x86_64.json)
adds a one-byte-above-boundary probe, explicit ICMPv6 Packet Too Big type/code and MTU 1203,
post-feedback boundary recovery, and the original exact-payload and teardown checks. No packet or
endpoint address is retained.

The
[FIPS G2 Linux one-sided NAT result](2026-08-29-fips-g2-linux-nat-x86_64.json) adds a third router
namespace, a proven stateful directional boundary, private-originated SNAT connectivity, and a
public-side translated-peer observation without retaining endpoints.

The
[FIPS G2 Linux managed-transit result](2026-08-30-fips-g2-linux-managed-transit-x86_64.json) adds a
static authenticated A–R–B FIPS data path across two underlay segments. It records direct-endpoint
exclusion, exact multihop payloads, positive forwarding counters at R, and endpoint-only FSP
termination. It is not Nostr-relay or public-discovery evidence.

The
[FIPS G2 Linux lifecycle result](2026-08-30-fips-g2-linux-lifecycle-x86_64.json) adds one
ungraceful direct-peer failure and daemon restart. It records bounded link-dead cleanup, a blocked
outage probe, stable identity, automatic reauthentication with zero manual reconnect commands,
post-restart payload/FSP recovery, and credential-directory teardown.

The
[FIPS G2 Linux alternate-route result](2026-08-30-fips-g2-linux-alternate-route-x86_64.json) adds
one authenticated four-node A–R1/R2–B diamond. It proves a bounded automatic tree reparent from a
failed active R1 to the already authenticated R2 path, followed by automatic FSP discovery and
session re-establishment after the configured 90-second idle timeout. Exact payload recovery took
93,439 ms, so this is explicitly non-hitless G2 connectivity evidence rather than G6 or media
continuity evidence.

The
[FIPS G2 Linux heterogeneous multihop-MTU result](2026-08-30-fips-g2-linux-multihop-mtu-x86_64.json)
adds a static A–R–B path with FIPS UDP MTUs 1280/1000/1280. It proves learned transport PMTU 1000,
endpoint session PMTU 1000, inner IPv6 PMTU 923, explicit ICMPv6 PTB/923 one byte above the path
boundary, and exact payload delivery at and below that boundary.

G2 remains in progress because broader NAT traversal, public/private discovery, dynamic or
impaired-network PMTUD cases, other impaired-network classes, and resource-bound classes are not
covered.

Do not commit generated output automatically. A retained result must pass review for provenance,
reproducibility, secrets, privacy, customer payload, size, licensing, and evidence classification.
Harness-only results are normally CI artifacts and do not belong here.

Retained FIPS assessment records must validate with:

```bash
PYTHONPATH=src python3 -m rimf_lab validate-fips-assessment \
  qualification/retained-results/2026-08-29-fips-source-build-assessment-macos-arm64.json

PYTHONPATH=src python3 -m rimf_lab validate-fips-g2-linux-direct \
  qualification/retained-results/2026-08-29-fips-g2-linux-direct-x86_64.json

PYTHONPATH=src python3 -m rimf_lab validate-fips-g2-linux-direct \
  qualification/retained-results/2026-08-30-fips-g2-linux-direct-mtu-boundary-x86_64.json

PYTHONPATH=src python3 -m rimf_lab validate-fips-g2-linux-nat \
  qualification/retained-results/2026-08-29-fips-g2-linux-nat-x86_64.json

PYTHONPATH=src python3 -m rimf_lab validate-fips-g2-linux-managed-transit \
  qualification/retained-results/2026-08-30-fips-g2-linux-managed-transit-x86_64.json

PYTHONPATH=src python3 -m rimf_lab validate-fips-g2-linux-lifecycle \
  qualification/retained-results/2026-08-30-fips-g2-linux-lifecycle-x86_64.json

PYTHONPATH=src python3 -m rimf_lab validate-fips-g2-linux-alternate-route \
  qualification/retained-results/2026-08-30-fips-g2-linux-alternate-route-x86_64.json

PYTHONPATH=src python3 -m rimf_lab validate-fips-g2-linux-multihop-mtu \
  qualification/retained-results/2026-08-30-fips-g2-linux-multihop-mtu-x86_64.json
```
