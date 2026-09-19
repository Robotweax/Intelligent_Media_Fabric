# SRT-over-FIPS profile v0

- Status: Phase 0 experiment profile
- Scope: transparent Robotweax SRT over an external FIPS `fips0` interface

## Required topology

- two dedicated Linux endpoints for the first qualified run;
- exact Robotweax SRT and FIPS revisions from `dependency-pins/baselines.json`;
- no vendored or privately linked FIPS or SRT source;
- public SRT Caller/Listener APIs;
- direct-IP SRT control run on the same hardware;
- downstream payload and timing observer independent of socket state; and
- retained OS, kernel, NIC, MTU, topology, build, and fault-plan provenance.

The first automated live pilot deliberately uses a single Ubuntu-hosted two-namespace topology.
Its shared boot-scoped host monotonic clock authorizes temporal ordering across the namespace
boundary. This is a qualification convenience, not evidence that independent production hosts
share a clock domain.

## Candidate matrix

The first matrix is intentionally small:

- direct SRT versus SRT through `fips0`;
- IPv6 overlay with documented IPv4 or IPv6 underlay;
- FIPS `v0.5.1` requalification candidate; the older development pin remains research-only;
- Robotweax SRT clear or CTR-compatible baseline before optional GCM comparison;
- 188-byte, 376-byte, 1316-byte, and maximum-safe payload profiles; and
- no impairment, selected MTU reductions, NAT, one relay, and one controlled outage.

The pilot media workflow and frozen performance budgets remain open decisions.

## Conservative packet accounting

For the documented FIPS UDP MTU of 1280 bytes and 77 bytes of FIPS overhead:

```text
inner IPv6 MTU                         1203 bytes
minus Robotweax SRT IPv6/UDP/SRT        64 bytes
clear or CTR SRT payload               1139 bytes
minus AES-GCM extension overhead         16 bytes
GCM SRT payload                        1123 bytes
minus current FEC reservation             4 bytes
GCM plus FEC payload                   1119 bytes
```

The historical v0.4.2 heterogeneous multihop result shows that the remote path can be smaller than
the endpoint-local effective MTU. For a learned FIPS transport PMTU of 1000 bytes:

```text
learned inner IPv6 path MTU              923 bytes
minus Robotweax SRT IPv6/UDP/SRT          64 bytes
clear or CTR SRT payload                 859 bytes
minus AES-GCM extension overhead          16 bytes
GCM SRT payload                          843 bytes
minus current FEC reservation              4 bytes
GCM plus FEC payload                     839 bytes
```

These historical values require fresh v0.5.1 qualification; they are experiment inputs, not a
general product guarantee. Each run must derive and record
the actual underlay, FIPS, inner-IP, SRT, crypto, FEC, and media packet budgets. Fragmentation or an
unexplained payload-size change fails the MTU gate. Packetization must use the smaller of the local
effective MTU and the qualified per-destination path MTU; a fixed 1203-byte assumption is invalid
for heterogeneous paths.

## Required success evidence

- byte- or frame-exact downstream payload identity;
- explicit SRT reconnect detection;
- downstream media gap and timing measurement;
- useful goodput and wire bytes;
- CPU, memory, packet rate, queue high-water, retransmission, loss, and RTT where available;
- exact route epoch for every path transition; and
- no secret, key, token, or customer payload in the result.

A connected socket without downstream validation is not a successful result.
