# G4 faulted diamond, first retained run — 2026-10-28

- Workflow: [G4 Faulted Diamond, run 40743995191](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40743995191)
- Fabric runner revision: `43757965` (branch `dev/g4-faulted-diamond`, PR #12)
- SRT v0.3.1 `57fcf51a`, SRT Telemetry `1b12f8d7` (media relay), FIPS v0.5.3 `f4a5b4a8`, FFmpeg `6.1.1-3ubuntu5`
- Platform: Linux x86_64, kernel `7.0.0-1017-azure`; four isolated namespaces a–r1–b / a–r2–b
- Contract: the [predeclared plan](g4-faulted-diamond-experiment-plan-2026-09-23.md) and its frozen execution profile (two revisions on 2026-10-28, both before this run), [ADR-0009](../decisions/0009-faulted-diamond-media-observation.md)

The workflow built the pinned sources, passed the complete pinned Telemetry CTest suite
(78 tests, including the new media-relay test), and retained the
[16-file evidence bundle](../../qualification/retained-bundles/2026-10-28-g4-faulted-diamond-40743995191/result.json)
(4.7 MB). The result manifest SHA-256 is
`dfc3d7b69bdc3adb6db219ffca7a7a47e8aaead5861e242676b22c1ac36abdf1`. Repository validation
re-checks the pins and FFmpeg version, the frozen profile including the packet budget and
decode options, every file digest, the route-epoch marker against its two FIPS observations,
byte-exact adapter replay of both SRT recordings, the frame assessment recomputed from the
retained framehashes (with zero re-timed frames), and the timeline recomputed from the raw
events.

## What happened

The packet budget held: inner IPv6 MTU 1203 on both endpoints, 1139 B of clear SRT payload,
1128 B media datagrams. `b`'s tree parent before the fault was `r2`. 20 s after the source
started, the runner sent SIGKILL to `r2`'s daemon (exit observed after 16 ms) and left the
underlay up. FIPS later reported `b` reparented to `r1` with the G2 peer, link and tree
conditions, so route epoch 2 was recorded. The one SRT session spanned both epochs
(`connectionBroken: false` on both relays, peer idle 60 s), and the run met every stop rule.

Times are milliseconds from SIGKILL-sent. Each is an interval at the layer's own sampling
resolution: collector per datagram, SRT 500 ms, FIPS 1 s (500 ms after the fault).

| Observation | Interval, ms |
| --- | --- |
| Downstream media stops (last datagram before the gap) | 143 |
| SRT receiver stall (no received-packet delta) | 490–990 |
| SRT sender loss or drop counters advance | 990–1490 |
| FIPS reports link loss and reparent to `r1` | 30,991–31,491 |
| SRT receiver resumes delivery | 31,990–32,490 |
| Downstream media resumes | 32,298 |

The collector saw one gap of 32,155 ms. The caller's relay handed all 17,729 source
datagrams to SRT with no send failure; the listener delivered 14,264. The difference is
the outage, dropped by SRT's too-late-packet drop. The source's largest lateness was 0.76 ms.
SRT sampling missed no interval (327 samples per endpoint), and FIPS was observed 195 times.
Cleanup was complete, including reaping the killed daemon.

The decoded frame comparison with the fixture reports 4000 expected frames, 3218 observed,
782 missing, 19 changed, 0 unexpected and 0 re-timed. The missing frames are 499–1280, one
contiguous 31.28 s run. The changed frames are 1281–1299: delivery resumed inside the GOP that
starts at frame 1275, so those P-frames were decoded without their reference until the next
I-frame at 1300. Every other frame matches the fixture's own decode bit-for-bit. No frame
size changed.

## What this does and does not establish

In this setup, an SRT live session with a 60 s peer-idle timeout survived a 31 s FIPS
reparent and resumed delivering the same stream. The downstream gap equals the FIPS
detection time plus about one second. Nearly all of the outage is FIPS noticing that `r2`
is gone (about 31 s with the pinned timers), not path selection or SRT reconnection.

The ordering is time-based only. Media stopping first at +143 ms reflects the collector's
per-datagram resolution against SRT's 500 ms and FIPS's 1 s sampling; it does not mean the
media layer diverged first. `causal_claim` is null. No first divergent layer, fault domain,
hitless claim, interruption budget or gate passage follows. The bundle records
`G4: not-passed`. This is one run on one host-local clock domain with one fault type, and
the 60 s idle timeout is an experiment setting, not a product profile. OD-01 and OD-14 still
block any continuity threshold. OD-15 still asks for the SRT-group comparison, which this run
does not provide.

## Superseded and failed attempts

- Runs [40732541677](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40732541677)
  and [40735801062](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40735801062)
  used 1316-byte datagrams, which exceeded the fips0 packet budget, and delivered no media.
  They are [retained as failures](../../qualification/failure-results/README.md).
- Run [40740237463](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/40740237463)
  (revision `f5c0cef`) produced a valid timeline of the same shape (media gap 31,135 ms;
  FIPS reparent 30,991–31,491 ms). Its frame comparison is invalid: FFmpeg's default 10 s
  MPEG-TS discontinuity correction re-based every post-gap frame by 756 frames. The decode
  was re-predeclared with `-dts_delta_threshold 1000000` and a re-timing guard. That run is
  superseded and not retained as a result.
