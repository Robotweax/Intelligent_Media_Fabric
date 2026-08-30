# Threat model

- Status: Phase 0 draft
- Scope: external FIPS daemon, Robotweax SRT endpoints, local observation adapters, retained evidence
- Last updated: 2026-08-30

## Assets

- device identity and private keys;
- tenant and stream authorization policy;
- contribution-media payload and timing;
- FIPS peer, route, managed-transit, and discovery/Nostr-relay metadata;
- SRT session metadata and telemetry;
- desired-state bundles and operator actions;
- retained qualification evidence; and
- software, dependency, and build provenance.

## Trust boundaries

```text
Internet / untrusted underlay
        |
FIPS peer and managed-transit boundary
        |
Host network namespace and fips0
        |
SRT process and local adapters
        |
Media Fabric service identity
        |
Evidence store / future control plane
        |
Operator and tenant boundary
```

Encryption at one boundary does not imply authorization at another. In particular, a cryptographic
FIPS peer identity is an input to Robotweax policy, not a complete device, service, stream, or tenant
authorization decision.

## Threat actors and required controls

| Actor or condition | Primary risk | Initial controls and gates |
| --- | --- | --- |
| Unauthenticated Internet source | traffic injection, scanning, resource exhaustion | FIPS authentication, firewalling, bounded queues, rate limits |
| Unauthorized FIPS node | peer access mistaken for media authorization | default-deny Robotweax policy, explicit service and stream grants |
| Compromised authorized peer | payload injection, topology discovery | least privilege, revocation, stream-scoped authorization, audit events |
| Malicious managed FIPS transit node | metadata observation, replay, drop, delay | end-to-end cryptographic guarantees, replay tests, transit node treated as untrusted |
| Local unprivileged process | control-socket abuse, metadata access | dedicated service users, filesystem permissions, socket ownership |
| Local privileged operator | key extraction, policy override | hardware-backed keys where possible, audited break-glass procedure |
| Compromised control plane | malicious desired state across fleet | signed bundles, RBAC, MFA, staged rollout, last-known-good rollback |
| Stolen device key | durable impersonation | rotation, revocation, bounded credential lifetime, incident procedure |
| Manipulated policy bundle | cross-tenant or stream access | signature, version, issuer, audience, expiry, anti-rollback checks |
| Discovery or Nostr-relay replay | stale or attacker-selected connectivity | freshness bounds, sequence/event identity, route epochs |
| Cross-tenant confusion | disclosure or unauthorized publication | tenant IDs in every authorization decision, negative isolation tests |
| Media traffic exhaustion | queue growth, latency collapse, host starvation | queue high-water marks, admission control, bounded recording, stop gates |
| Evidence poisoning | false Go decision | immutable provenance, scenario digest, independent downstream validation |

## Mandatory security invariants

1. No media stream is accepted solely because a FIPS connection exists.
2. Missing policy, identity, measurement, or provenance fails closed or remains explicitly
   unavailable.
3. No private key, bearer token, password, customer payload, or raw environment is persisted in a
   qualification result.
4. A downgrade or alternate path is explicit and observable.
5. Route changes increment a route epoch and preserve their reason and evidence quality.
6. A result cannot be `passed` when downstream payload validation is required but absent.
7. Control and native sockets are accessible only to the dedicated service identity.
8. FIPS naming must never imply FIPS 140 certification.

## Evidence-lab risks

Experiment commands are data and therefore a code-execution boundary. The harness executes argument
arrays without a shell, rejects suspicious environment-variable names, bounds runtime and captured
output, and records hashes rather than raw output. Scenarios must still be reviewed before execution.

Network impairment, namespace, TUN, and packet-capture work can require elevated privileges. Those
capabilities are outside the initial harness and must be isolated to dedicated lab hosts with an
explicit operator action and teardown procedure.

## Open security decisions

- device credential representation and issuer;
- key storage for software-only, appliance, and OEM deployments;
- revocation and offline authorization window;
- private discovery and Nostr relay operation;
- control-plane trust root and desired-state signing;
- evidence retention and deletion policy;
- independent review scope before a broadcast-critical pilot; and
- security-update SLA for pinned FIPS builds.
