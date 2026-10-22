# G1 direct-SRT baseline — first retained run — 2026-10-22

- Workflow: [G1 Direct SRT Baseline, run 39806840201](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/39806840201)
- Fabric runner revision: `daf078e2` (branch `dev/g1-direct-srt-baseline`)
- SRT v0.3.0: `4ae6330d62f2b5030d96964bf3500283f32dd39c`
- SRT Telemetry: `2447548388a47aaac647bb2eafdc4f9e962f0baa`
- Platform: Linux x86_64, kernel `6.17.0-1022-azure`; two isolated namespaces, direct IPv6 veth, MTU 1500, no FIPS
- Contract: [predeclared on 2026-10-22](g1-direct-srt-baseline-plan-2026-10-22.md)

The workflow built the pinned sources, passed the complete Telemetry test suite, then ran
three repetitions of the G4 workload (240 messages of 1024 bytes, 5 ms pacing, fourteen
samples per endpoint) directly over the veth. It retained the
[28-file evidence bundle](../../qualification/retained-bundles/2026-10-22-g1-direct-srt-baseline-39806840201/result.json);
the result manifest SHA-256 is
`6b8d341b97ae0eef0d9a5d1b761231a0a17ae189d386b882a9dcb26283ca6827`. Repository validation
replays all six adapter outputs byte-for-byte, checks every file digest, provider identity,
media identity, the ordering assessments and their input digests, and that the summary
ranges are exactly those of the recorded repetitions.

## What was observed

All three repetitions delivered the 240 messages exactly, with zero dropped packets, zero
loss and zero retransmissions on either endpoint, and 261,120 wire bytes in each direction.
Each coordinator sample landed within 0.094 ms of its 100 ms target; no interval was missed.
The receiver first held every message at the post-transfer sample (index 13) in all three
repetitions, and the coordinator confirmed the transfer 1,335–1,337 ms after it started. The
sender used 20 ms of CPU and 12.6–12.7 MiB peak RSS per repetition, the receiver 10–20 ms and
12.9 MiB; the SRT RTT estimate started at the 100 ms default and settled near 2.09 ms.

An earlier run of the same code on the transient pull-request merge commit
([39804204721](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/39804204721))
produced the same shape (3/3 exact, zero loss, ≤ 0.101 ms schedule error); it is not retained
because its recorded project revision cannot be checked out later.

## What this does and does not establish

This is the first retained direct-SRT control. It shows the harness and workload behave
reproducibly on a clean path and gives the reference the SRT-over-FIPS pilots will be compared
against. It does not pass G1: the gate asks for repeated runs under owner review, and the
recorded CPU, RSS, RTT and timing values carry no thresholds because OD-01, OD-04 and OD-14 are
open. It is not a direct/FIPS comparison, a G3 scorecard, or evidence about loss, delay,
backpressure or route change. G1 moves to `in-progress`.
