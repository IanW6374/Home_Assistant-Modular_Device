# Security policy

## Supported versions

Security fixes are provided for the current stable release. Release candidates
and development snapshots are supported only while they remain the active test
line. Older releases should be upgraded before a report is investigated.

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue, discussion, log,
diagnostic archive, or support bundle. Use this repository's private GitHub
security-advisory reporting facility when available. Otherwise contact the
repository owner privately and request a secure reporting channel.

Include the affected version and hardware, the minimum reproduction steps,
expected impact, and whether update-signing, Secure Boot, flash encryption,
portal authentication, API mutual TLS, certificate material, or recovery mode
is involved. Remove passwords, private keys, certificates containing private
identifiers, and live network addresses.

The maintainer will acknowledge a report, assess severity and affected
versions, coordinate a fix and release, and credit the reporter if requested.
Please allow a reasonable remediation period before coordinated disclosure.

## Operational security

- Keep update-signing and Secure Boot private keys offline and backed up.
- Use HTTPS and mutual TLS; explicit HTTP mode is for isolated trusted networks.
- Treat encrypted complete backups as sensitive even though they are
  password-protected.
- Do not publish factory setup passwords, device credentials, private keys,
  diagnostics, or unredacted logs.
- Never bypass signature, anti-rollback, clean-tree, dependency-pin, or secure
  firmware-build checks for a production release.
