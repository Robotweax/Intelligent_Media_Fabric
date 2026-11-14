# Draft upstream request: two FIPS identities on one host — 2026-11-14

- Status: **draft, not sent.** Nothing has been posted to the FIPS project. Sending it, in any form, is a separate explicit owner step.
- Serves OD-10 (generic capabilities proposed upstream). Follows [ADR-0014](0014-continuity-by-srt-group.md), which says the missing capability is taken to the FIPS project as a request and that no fork is made.
- It changes no gate and closes nothing by itself.

Section 1 is context for this repository. Section 2 is the text proposed for upstream,
written to stand on its own. Section 3 lists what the owner would decide before anything is
sent.

## 1. Why this repository needs it

[ADR-0012](0012-interruption-budget.md) sets a hitless target for the loss of one transit.
A single SRT session over FIPS cannot meet it: the gap follows the FIPS link-dead timer. An
SRT connection group with one member per independent path does meet it, and it did so over
FIPS in the [stage 2 run](../qualification/g5-srt-group-over-fips-2026-11-14.md).

A group needs two paths that fail independently. A FIPS node has one identity, one address
and one route to a peer, so two group members between the same two FIPS addresses share one
route. Stage 2 therefore gave each endpoint two identities by running two daemons, each in
its own overlay. That works only with a lab step FIPS v0.5.3 does not provide, which is what
this request is about. Until it is resolved, ADR-0014 allows the group over FIPS to be
described only as demonstrated, not supported.

## 2. Proposed text for upstream

> ### Two daemons with separate identities in one network namespace
>
> **What we are doing.** We carry a live media stream over FIPS with SRT. For continuity
> when a transit node fails we use an SRT connection group: two SRT member connections that
> must take paths which fail independently. One process opens both members, so both local
> addresses have to exist in one network namespace. We give the host two FIPS identities by
> running two daemons there, each peered into a separate mesh.
>
> **What happens (v0.5.3, `f4a5b4a8`, Linux).** The second daemon starts degraded:
>
> ```
> WARN fips::node::lifecycle: Failed to initialize TUN, continuing without it
>   error=failed to configure TUN device: failed to add fd00::/8 route:
>   Received a netlink error message File exists (os error 17)
> WARN fips::node::lifecycle: Node started DEGRADED ... degraded_children={Tun}
> ```
>
> Each daemon installs `fd00::/8` on its own TUN device in the main table. The first one
> succeeds; the second add collides with it. Everything else we needed was already
> configurable and did not collide: `tun.name`, the control socket path, the UDP
> `bind_addr`, and the DNS port.
>
> Reading the default branch at `6aa8050` (2026-11-14), the Linux path still adds the same
> route unconditionally, and a comment there names this case: a create that fails "another
> node's TUN already owns fd00::/8 in this namespace". We have not run that revision.
>
> **Minimal reproduction.** In one namespace, start two daemons whose configurations differ
> in identity, `tun.name`, control socket and UDP bind address. `fipsctl show status` on the
> second reports `tun_state: failed`.
>
> **What we do today.** After each daemon has configured its TUN, we delete its `fd00::/8`
> route, then add one `/128` route per remote address on the TUN of the daemon that can
> reach it. With that in place both overlays carry traffic, an address of one overlay does
> not reach the other, and blackholing one overlay's transit stops only that overlay. We
> ran a 160 s stream this way with no lost frame while one overlay's transit was
> blackholed. It is a workaround in our test harness: it races the daemon's own setup and
> undoes something the daemon did.
>
> **What we are asking.** Is running two daemons with separate identities in one namespace
> something FIPS would support? If so, the smallest change we can see is an option under
> `tun` that makes the daemon configure the device (address, MTU, up) and leave routing for
> `fd00::/8` to the operator, for example `tun.install_routes: false`. With it the
> operator, not the daemon, decides which destinations go to which TUN, and nothing needs
> to be undone.
>
> We are not asking for the second add to be tolerated silently. Two daemons that both
> believe they own `fd00::/8` would send traffic for one mesh into the other.
>
> **The larger question, if it is of interest.** What we actually need is two paths to one
> peer that fail independently, and a way for an application to pin a flow to one of them.
> Two identities are our way of getting that with what exists. One identity with two
> concurrent paths would serve the same purpose and would remove the need for the peer to
> know two identities. We do not propose a design for that here; issue 143 (a peer
> reachable over two interfaces) looks related from the transport side.
>
> **Scope of our evidence.** One Linux host with network namespaces, veth links and a
> 1 Mbit/s stream. We have not tried this on macOS, Windows or BSD, and have not looked at
> how the firewall baseline or `fips-dns-setup` would behave with two daemons.

## 3. Decisions for the owner before anything is sent

1. **Send it at all,** and in whose name. This would be the first public contact from this
   project with the FIPS project.
2. **Form:** an issue, a discussion, or direct contact with the maintainer first. The FIPS
   contribution guide asks that behaviour-changing work be backed by its integration
   harness; a question is the lighter first step.
3. **How much to ask:** only the `tun` option, or also raise the two-paths question.
4. **Whether to offer a patch.** A patch would be work in the FIPS repository under its
   rules and is not started. ADR-0014 rules out a fork, not a contribution.
5. **What to disclose about the use case.** The text above names SRT and live media and
   links nothing. Linking this repository's records is possible, since it is public.

## What this draft rests on, and its limits

- The failure and the workaround were observed in a local probe and in the retained
  [stage 2 run](../qualification/g5-srt-group-over-fips-2026-11-14.md), both at FIPS v0.5.3.
  The probe is not retained evidence; the run is.
- The statement about the default branch comes from reading its source on 2026-11-14, not
  from building or running it. The option name `tun.install_routes` is a suggestion, not
  something FIPS has.
- Whether FIPS wants to support this is the maintainer's decision. A refusal would leave
  ADR-0014 standing as written: group over FIPS demonstrated, not supported.
- The reference to issue 143 is a reading of its title and opening text only.
