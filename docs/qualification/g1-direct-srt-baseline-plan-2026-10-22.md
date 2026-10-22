# G1 direct-SRT baseline — predeclared experiment contract

Status: predeclared on 2026-10-22; see the end of this document for retained runs.

G1 asks whether the control is correct and the harness non-distorting. This experiment is
the control for the SRT-over-FIPS pilots: the identical workload, measurement path and
coordinator, with the FIPS data plane removed. It is not a performance comparison; G3's
direct/FIPS scorecard needs frozen budgets (OD-01, OD-04, OD-14) that do not exist yet.

## What is held identical to the G4 pilot

- Robotweax SRT, SRT Telemetry and the incident-peer binary at the pinned revisions, built by
  the same CMake steps.
- Two Linux network namespaces joined by one veth pair; the application transfer of 240
  messages of 1024 bytes with 5 ms send pacing; one pre-transfer sample, twelve 100 ms
  samples during the transfer and one post-transfer sample per endpoint; the Telemetry
  adapter with an explicit Fabric context; the receiver's byte-identity media observation;
  and the same-host SRT/media ordering assessment.

## What differs

- The SRT peers bind to IPv6 addresses on the veth itself (`fd00:1::/64`, link MTU 1500);
  there is no `fips0`, no FIPS daemon and no FIPS observation stream.
- The transfer is repeated `repetitions` times (default 3) in one run with fresh peer
  processes, flow identifiers and recordings, inside the same namespaces.

## Fail-closed requirements (each repetition)

1. Exact application delivery of all 240 messages, confirmed by the provider-linked receiver.
2. Zero sender and receiver drop packets in the final SRT sample of both endpoints.
3. The coordinator never misses a complete 100 ms sampling interval; the schedule error of
   every sample is recorded.
4. Fourteen samples per endpoint; the Telemetry adapter accepts the recordings and its output
   replays byte-for-byte at validation time; ordering of the selected SRT observation against
   the media observation is `ordered` on the shared host clock.
5. Complete teardown: peers stopped, namespaces removed, work directory removed.

## Recorded without thresholds

Retransmitted and loss packet totals, unique and total wire bytes, RTT range across samples,
the first sample index at which the receiver held all messages, per-sample schedule error,
and each peer's CPU time and peak RSS read from `/proc` before it is told to exit. These are
distortion indicators for the owner to judge when budgets are frozen; the harness does not
grade them, and a passing result makes no claim about them.

## Not exercised

Loss, delay, reordering, bandwidth limits, UDP backpressure, outages, route changes, FIPS,
independent media decode, and anything about SRT over the pinned FIPS pin.

## Evidence and gate effect

Output follows `schema/qualification/g1-direct-srt-baseline-result.schema.json` and the
repository bundle validator; it records `G1: not-passed` and changes no gate status on its
own. Retained bundles make G1 `in-progress`; passing G1 is an owner decision over repeated
retained runs.
