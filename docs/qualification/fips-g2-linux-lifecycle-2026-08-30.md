# FIPS G2 Linux lifecycle qualification

- Date: 2026-08-30
- Gate: G2 FIPS Connectivity
- Result: passed link-dead/daemon-restart slice; G2 remains `in-progress`
- Baseline: FIPS `v0.4.2` at `487fa86f65794071e3b91313c298d4f09b98b7fe`
- Runner revision: `b9af41705bad5548087d6077077a2d62f54fc624`
- Workflow run:
  [33297079567](https://github.com/Robotweax/Intelligent_Media_Fabric/actions/runs/33297079567)
- Retained record:
  [Linux lifecycle result](../../qualification/retained-results/2026-08-30-fips-g2-linux-lifecycle-x86_64.json)

## Question

Does the ADR-0003 FIPS baseline detect an ungracefully failed direct peer through its link-dead
mechanism, remove stale link and FSP state, preserve the failed node's identity across daemon
restart, and reconnect automatically without an operator-issued connect command before resuming
exact payload delivery?

## Method and controls

The manually dispatched workflow used two Linux network namespaces joined by a direct IPv4 veth
underlay. Each namespace ran a separate externally built FIPS daemon with `fips0` active at TUN and
UDP MTU 1280. Both identities were generated as persistent key files inside one mode-0700 temporary
directory; private and public files had modes 0600 and 0644. A configured B as one static
`auto_connect` peer with `auto_reconnect: true`. B had no static peer. No `fipsctl connect` command
was used.

Before failure, the runner required an authenticated two-node link, estimated mesh size two, full
MMP and SRTT views, exact deterministic UDP echo at 1, 1024, and 1155 payload bytes, and at least one
FSP session on each node. It then sent `SIGKILL` to B without a graceful protocol disconnect.

A had to remove its peer, link, and FSP session within a 60-second observation budget around the
configured 30-second link-dead timeout. A 32-byte ICMPv6 payload probe then had to fail while B was
absent. The runner restarted B from the same temporary key files and required a changed daemon
process but an unchanged public identity and derived mesh address. A had to reconnect through the
configured automatic retry path within 90 seconds, with the manual reconnect-command count fixed
at zero.

After recovery, both nodes again had to expose active TUN state, one authenticated peer and link,
estimated mesh size two, full MMP and SRTT, boundary-sized ICMPv6 delivery, exact UDP echo, and FSP
sessions. An acknowledged final disconnect had to remove all peer, link, and session state before
complete process, namespace, and credential-directory teardown.

## Results

| Assertion | Observed result |
| --- | --- |
| Linux architecture | `x86_64`, kernel `6.17.0-1022-azure` |
| FIPS version | `0.4.2 (rev 487fa86f65)` |
| Initial connection | one configured auto-connect peer; one authenticated peer/link per node; mesh size two |
| Initial data plane | full MMP/SRTT; exact UDP echo at 1, 1024, and 1155 bytes; one FSP session per node |
| Failure injection | B terminated by `SIGKILL`; no graceful disconnect |
| Link-dead observation | A reached zero peers, links, and FSP sessions after 31,978 ms |
| Outage proof | ICMPv6 data-plane probe blocked while B was absent |
| Identity continuity | public identity and mesh address unchanged; daemon process changed |
| Automatic reconnect | zero manual reconnect commands; authenticated topology restored 3,037 ms after B restarted |
| Post-restart ICMPv6 | two echoes passed at the 1155-byte effective-MTU payload boundary |
| Post-restart payload | exact UDP echo at 1, 1024, and 1155 payload bytes |
| Post-restart FSP | one session on each node |
| Controlled disconnect | acknowledged; zero peers, links, and sessions afterward |
| Teardown | faulted daemon reaped; live daemons stopped; namespaces and identity directory removed |

The elapsed times are single-run observations from a GitHub-hosted runner, not production SLOs.
The retained file is byte-identical to the reviewed workflow artifact and has SHA-256
`9516ae123e5825bee2f3045313f762481c11233e6184a571735d55aa93cbd685`. It excludes private keys,
public identities, mesh and underlay addresses, process identifiers, raw payloads, control
responses, and daemon logs.

## Interpretation

This closes the explicit direct-path link-dead and daemon-restart slice of G2. The result proves
that the pinned FIPS baseline removed stale direct peer, link, and FSP state after an ungraceful
failure, reused the failed daemon's stable identity, reauthenticated automatically from a static
peer contract without a manual connect, and restored exact data-plane and session behavior.

This is not alternate-route reconvergence evidence: the underlay and endpoint address were
unchanged, and no backup peer or managed transit route was available. It also does not qualify
transit-node failure, NAT rebinding, public discovery, signaling relay recovery, impaired networks,
resource bounds, or SRT media continuity. G2 therefore remains open for the remaining
connectivity/discovery, heterogeneous multihop PMTUD, impairment, and resource slices. Route
reconvergence and running-stream continuity remain G6 and G3 work respectively.

The subsequent
[alternate-route qualification](fips-g2-linux-alternate-route-2026-08-30.md) closed the bounded
transit-failure connectivity slice: FIPS reparented automatically to an already authenticated
alternate in 31.746 seconds and restored exact payload after automatic FSP session replacement in
93.439 seconds. That result is non-hitless and does not change the G6 or G3 continuity status.
