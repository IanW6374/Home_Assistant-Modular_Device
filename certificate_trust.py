"""Explicit removal operations for replaceable certificate trust material."""

try:
    import uos as os
except ImportError:
    import os


TRUST_LABELS = {
    'mqtt-ca': 'MQTT broker CA',
    'release-ca': 'Release server CA',
    'syslog-ca': 'Syslog server CA',
    'management-suite-key': 'Management Suite signing key',
}


def remove(kind, fingerprint, api_ca_store, paths):
    """Remove one exact trust object and return whether API trust changed."""
    kind = str(kind or '')
    if kind == 'api-client-ca':
        if not api_ca_store.revoke(str(fingerprint or '').strip().lower()):
            raise ValueError('Device API client issuer CA was not found')
        return 'Device API client issuer CA removed', True
    if kind not in TRUST_LABELS or kind not in paths:
        raise ValueError('certificate trust type cannot be removed')
    path = str(paths[kind])
    try:
        os.remove(path)
    except OSError:
        raise ValueError(TRUST_LABELS[kind] + ' is not installed')
    return TRUST_LABELS[kind] + ' removed', False
