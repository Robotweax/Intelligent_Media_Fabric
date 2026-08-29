# Security policy

## Project status

Robotweax Intelligent Media Fabric is private, pre-alpha research software. No release is currently
supported for production, broadcast-critical, safety-critical, or compliance-regulated use.

## Reporting a vulnerability

Report suspected vulnerabilities privately through the repository's GitHub Security Advisory
workflow or directly to the repository administrators. Do not disclose credentials, private keys,
customer data, exploit details, or sensitive logs in an issue or pull request.

Include, where safe:

- the affected revision and dependency pins;
- deployment and network assumptions;
- a minimal reproduction;
- security impact;
- whether a credential, tenant boundary, media payload, or control path is exposed; and
- suggested containment steps.

Do not test against systems or networks without explicit authorization.

## Security boundaries

- FIPS means Free Internetworking Peering System in this project. It is not a FIPS 140 validation.
- A successful encrypted connection does not by itself prove device or tenant authorization.
- Local FIPS control and native sockets require OS and filesystem access controls.
- Secrets, private keys, bearer tokens, and customer payloads must not enter retained evidence.
- A development dependency or commit is not a security support commitment.
- Silent downgrade is a qualification failure.

The current threat model is in [docs/security/threat-model.md](docs/security/threat-model.md).
