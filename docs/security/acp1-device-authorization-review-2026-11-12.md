# Review: SRT session authentication and ACP1 against the device-authorization draft

- Status: review note, input to OD-03 and OD-07. It decides nothing and changes no gate.
- Date: 2026-11-12
- Reviewed: Robotweax SRT `v0.3.2` at `e45d0edd346e5c427d85e4c3b1ac605c81a23397`
  ([session authentication](https://github.com/Robotweax/srt/blob/v0.3.2/docs/session-authentication.md),
  [experimental ACP1](https://github.com/Robotweax/srt/blob/v0.3.2/docs/experimental-acp1.md),
  `include/srt/srt.h`) against the [device-authorization draft](device-authorization-draft.md)
  and the [threat model](threat-model.md).
- Method: documents and the public header only. The SRT implementation was not read and
  nothing was run. Statements about SRT are what its documents claim at that tag.

## Finding

Session authentication and ACP1 prove that both ends of a connection hold the same
passphrase, and ACP1 additionally protects that connection's runtime control traffic. Neither
carries a device, tenant, service or stream identity. They are a possible lower layer for the
draft's authorization model, not an implementation of it.

## What SRT provides at v0.3.2

**Session authentication** (`SRTO_ROBOTWEAX_SESSIONAUTH`, supported, off by default). A
handshake proof from a passphrase-derived key, bound to fresh nonces from both peers, both
socket IDs and their roles. The listener does not publish a connection before it has verified
the caller's final proof. Key-rotation messages and FEC parity are authenticated. It requires
a passphrase and enforced encryption, has no fallback, and does not interoperate with
Haivision peers when enabled.

**ACP1** (`SRTO_ROBOTWEAX_ACP1_REQUIRED`, experimental, build option
`ROBOTWEAX_SRT_ENABLE_EXPERIMENTAL_ACP1`, off by default). Adds an authenticated envelope
around runtime controls (ACK, ACKACK, NAK, DROPREQ, KEEPALIVE, SHUTDOWN, key rotation) with
separate keys per direction and a 64-position replay window. It covers caller/listener,
rendezvous and Broadcast/Backup groups, each with its own session-authentication version.
Its document calls the wire values provisional and states that no independent cryptographic
review has been done. The support decision is open in
[Robotweax/srt issue 190](https://github.com/Robotweax/srt/issues/190).

**Not authentication.** `SRTO_ROBOTWEAX_PEER_IDENTITY` is a self-reported implementation
label; the header says it has "no authentication or capability meaning".

## Comparison with the draft

| Draft requirement | SRT at v0.3.2 | Verdict |
| --- | --- | --- |
| `fips_peer_id`, `device_id`, `service_id`, `tenant_id` and `stream_id` kept distinct | None is carried or bound in the handshake | missing |
| Mapping signed by an approved issuer | Symmetric passphrase only; no signature and no issuer | missing |
| Explicit service and stream pattern | Stream ID is outside the proof: "unauthenticated routing input, not proof of a peer's identity or authorization" | missing; see the first risk below |
| Actions `publish`, `subscribe`, `relay`, `observe`, `administer` | Caller/listener (or initiator/responder) role is bound; that is connection direction, not media direction | missing |
| Versioned, time-bounded, anti-rollback bundles | No credential lifetime. Strict version negotiation prevents a protocol downgrade only | missing |
| Reject replayed bundles | Replay protection covers handshake proofs, key rotation, FEC parity and (ACP1) controls, not policy bundles | different layer |
| Deny when no grant matches; fail closed | Required mode has no fallback; missing prerequisites fail setup with `SRT_ESECFAIL`; nothing is published before the final proof | matches |
| Revocation; least privilege for a compromised authorized peer | "Shared-secret holders can impersonate one another"; no forward secrecy | conflicts when one passphrase is shared |
| Record the decision reason without a secret | `SRTO_ROBOTWEAX_ACP1_ACTIVE` is "an observation, not an authorization token" | audit input only |

## What Fabric could use

1. **The listen callback as the policy decision point.** Since SRT v0.3.0 a listen callback
   may set session authentication, enforced encryption and the passphrase on the provisional
   child and may reject it. A Fabric grant could be evaluated there, before any media flows.
2. **Fail-closed admission.** A connection that completes with ACP1 required proves the peer
   holds the configured secret. That satisfies threat-model invariant 1 ("no media stream is
   accepted solely because a FIPS connection exists") only when the secret itself is scoped;
   see the proposal below.
3. **Control-plane integrity on a direct path.** On a direct-SRT path without FIPS, ACP1 is
   the only protection of ACK, NAK and shutdown against an on-path attacker.

## Risks if it is used as-is

1. **Stream ID looks like authorization and is not.** A policy that selects by Stream ID and
   then accepts any holder of a shared passphrase lets every holder claim every stream.
2. **A shared passphrase defeats per-device revocation.** Removing one device means changing
   the secret on all of them.
3. **Source DATA is not covered.** AES-CTR payload stays malleable with or without ACP1;
   payload integrity needs AES-GCM as a separate setting.
4. **Compatibility.** ACP1 peers cannot connect to Haivision peers or to peers with session
   authentication alone.
5. **Packet budget.** Each control packet grows by 60 bytes, and ACP1 requires an MSS of at
   least 256. Media payload is unchanged by ACP1, but the AES-GCM that risk 3 calls for costs
   16 bytes: 1123 instead of 1139 bytes per the
   [profile's accounting](../protocols/srt-over-fips-profile-v0.md). The faulted-diamond
   fixture's 1128-byte datagrams would not fit.
6. **Pinning an experiment.** Fabric would depend on a default-off prototype with provisional
   wire values, and the SRT Telemetry incident peer has no option to enable it today.

## Proposal for discussion (not in either document)

Derive one SRT passphrase per device and stream from the device credential, for example from
`tenant_id`, `device_id`, `service_id`, `stream_id` and the policy version, and have the
listen callback select that passphrase after evaluating the grant. A completed handshake then
shows possession of a secret that only that device should hold for that stream, and revoking
a device removes its derived secrets without touching the others. Identity, issuer,
lifetime, revocation transport and the offline window stay in Fabric; SRT only verifies
possession. Whether the derivation input should include `fips_peer_id` depends on whether a
direct-SRT path without FIPS must use the same credential (OD-05).

This is unreviewed. It inherits SRT's stated limits: a 2048-iteration PBKDF, so the derived
secret must be high-entropy, and no forward secrecy.

## What this means for the open decisions

- **OD-03 (first SRT crypto profile):** session authentication with AES-GCM is a candidate
  that uses only supported options. Adding ACP1 is a candidate only after issue 190 is
  decided. Either one needs the packet budget re-qualified at 1123 bytes (OD-04).
- **OD-07 (device credential, revocation, offline policy):** not addressed by SRT. The
  credential format, issuer and revocation still have to be designed in Fabric; the proposal
  above is one way to connect that design to an SRT connection.
- **Upstream:** authenticating the Stream ID inside the session-authentication proof would
  remove risk 1 at the source. ACP1's document lists the incomplete handshake transcript as a
  known limit, so the natural place to raise it is the review tracked in issue 190.

## Not established here

No experiment has run with session authentication or ACP1 over `fips0`. Handshake behavior
during a FIPS reparent, CPU cost, and control overhead on the 1203-byte inner MTU are
unmeasured. Nothing in this note is evidence for a gate.
