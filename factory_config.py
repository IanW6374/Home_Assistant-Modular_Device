"""Non-secret first-boot product catalogue frozen into the core firmware."""

# Set this to the production HTTPS release endpoint before building factory
# firmware. It can receive a ``channel`` query value, or use a static-host
# template such as ``https://updates.example/{channel}/latest.json``.
# The result is the same release object used by normal portal updates.
SETUP_RELEASE_MANIFEST_URL = ''
SETUP_TRUST_CA_CERT_PATH = '/certs/trust/home-rca-root.der'
# Compatibility alias for factory integrations built against the earlier name.
SETUP_CA_CERT_PATH = SETUP_TRUST_CA_CERT_PATH
