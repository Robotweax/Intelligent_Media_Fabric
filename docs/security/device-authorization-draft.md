# Device and stream authorization draft

- Status: proposed, Phase 0 contract input
- Schema: `schema/policy/device-authorization.schema.json`

## Separation of identities

The system keeps four identifiers distinct:

1. `fips_peer_id`: cryptographic network peer identity;
2. `device_id`: Robotweax-managed hardware or software installation;
3. `service_id`: an advertised or consumed service;
4. `tenant_id` and `stream_id`: authorization and media ownership scope.

No identifier is silently substituted for another. A mapping is explicit, signed by an approved
issuer, versioned, time-bounded, and auditable.

## Default policy

- deny when no matching grant exists;
- deny cross-tenant publication and subscription;
- scope actions to `publish`, `subscribe`, `relay`, `observe`, or `administer`;
- require an explicit service and stream pattern;
- reject expired, not-yet-valid, malformed, replayed, or anti-rollback-violating bundles; and
- record the policy version and decision reason without recording a secret.

The draft schema is not a production credential format. Cryptographic envelope, issuer hierarchy,
revocation transport, offline behavior, and key storage require later ADRs and adversarial tests.
