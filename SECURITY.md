# Security policy

## Supported version

Security fixes are provided for the latest v2 production release. Upgrade an
older device before requesting investigation unless the upgrade itself is the
reported issue.

## Reporting

Use this repository's private GitHub Security Advisory facility. Do not place
vulnerabilities, credentials, certificates, private keys, diagnostics or
unredacted logs in a public issue.

Include the affected version and hardware, minimum reproduction steps, impact
and whether the issue involves signing, Secure Boot, flash encryption, portal
authentication, API mutual TLS or recovery.

## Operator responsibilities

- Keep release-signing and Secure Boot private keys offline and backed up.
- Use HTTPS and mutual TLS; HTTP is for isolated recovery scenarios only.
- Treat encrypted complete backups as sensitive key material.
- Never publish setup passwords, credentials, factory images or private keys.
- Do not bypass signature, anti-rollback, clean-tree or secure-build checks.

See [security operations](docs/SECURITY_OPERATIONS.md) for rotation and incident
response.
