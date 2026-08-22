"""Versioned configuration backup, validation and encrypted full recovery."""

try:
    import ujson as json
except ImportError:
    import json

try:
    import time
except ImportError:
    time = None

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import uos as os
except ImportError:
    import os


FORMAT_VERSION = 3
MAX_IMPORT_BYTES = 128 * 1024
SECURE_FORMAT = 'hamd-secure-backup'
SECURE_FORMAT_VERSION = 1
SECURE_KDF_ITERATIONS = 120000
SECURE_SALT_BYTES = 16
SECURE_NONCE_BYTES = 12
SECURE_TAG_BYTES = 16
IMPORTABLE_SETTINGS = (
    'device_name', 'wifi_ssid', 'wifi_dhcp', 'wifi_ip_address',
    'wifi_subnet_mask', 'wifi_gateway', 'wifi_dns_server',
    'mqtt_server', 'mqtt_port', 'mqtt_username',
    'portal_username', 'portal_transport', 'portal_port',
    'portal_session_timeout_s', 'release_channel', 'loglevel', 'ntp_servers',
    'timezone_offset_minutes', 'timezone_name', 'log_buffer_lines', 'ha_discovery',
    'certificate_mode', 'acme_directory_url', 'certificate_hostname',
    'release_auto_download', 'release_auto_activate',
    'release_check_schedule', 'release_check_time', 'release_check_weekday',
    'api_enabled', 'api_port',
    'syslog_enabled', 'syslog_host', 'syslog_port', 'syslog_transport',
)


def export_configuration(public_settings, module_settings, metadata=None):
    settings = {}
    for key in IMPORTABLE_SETTINGS:
        if key in public_settings:
            settings[key] = public_settings[key]
    return {
        'format_version': FORMAT_VERSION,
        'created_at': int(time.time()) if time else 0,
        'metadata': metadata or {},
        'settings': settings,
        'module_settings': module_settings,
        'secrets_included': False,
    }


def parse_import(payload):
    if isinstance(payload, bytes):
        if len(payload) > MAX_IMPORT_BYTES:
            raise ValueError('configuration import exceeds the size limit')
        payload = payload.decode()
    if isinstance(payload, str):
        if len(payload.encode()) > MAX_IMPORT_BYTES:
            raise ValueError('configuration import exceeds the size limit')
        candidate = json.loads(payload)
    else:
        candidate = payload
    if not isinstance(candidate, dict):
        raise ValueError('configuration backup must contain an object')
    version = candidate.get('format_version', 0)
    if not isinstance(version, int) or isinstance(version, bool) or version != FORMAT_VERSION:
        raise ValueError('unsupported configuration backup format')
    if candidate.get('secrets_included') is not False:
        raise ValueError('configuration backup must explicitly exclude secrets')
    allowed = {
        'format_version', 'created_at', 'metadata', 'settings',
        'module_settings', 'secrets_included'
    }
    unknown = set(candidate) - allowed
    if unknown:
        raise ValueError('unknown configuration backup field: ' + sorted(unknown)[0])
    settings = candidate.get('settings', {})
    modules = candidate.get('module_settings')
    if not isinstance(settings, dict):
        raise ValueError('configuration settings must be an object')
    unknown_settings = set(settings) - set(IMPORTABLE_SETTINGS)
    if unknown_settings:
        raise ValueError('setting is not importable: ' + sorted(unknown_settings)[0])
    if modules is not None and not isinstance(modules, dict):
        raise ValueError('module settings must be an object')
    return {'settings': dict(settings), 'module_settings': modules}


def _secure_crypto():
    try:
        import _hamd_crypto
    except ImportError:
        raise RuntimeError(
            'encrypted backups require compatible HAMD core firmware'
        )
    for name in ('pbkdf2_sha256', 'aes_gcm_encrypt', 'aes_gcm_decrypt'):
        if not hasattr(_hamd_crypto, name):
            raise RuntimeError(
                'encrypted backups require a newer HAMD core firmware'
            )
    return _hamd_crypto


def _password_bytes(password):
    password = str(password or '')
    # Match the portal password floor without requiring a particular mixture;
    # long passphrases are suitable encryption keys after PBKDF2.
    if len(password) < 16 or len(password) > 256:
        raise ValueError('backup password must contain 16 to 256 characters')
    return password.encode()


def export_secure_configuration(credentials, module_settings, files, password,
                                metadata=None, random_bytes=None):
    """Return a password-encrypted, authenticated full-device backup envelope."""
    random_bytes = random_bytes or os.urandom
    salt = bytes(random_bytes(SECURE_SALT_BYTES))
    nonce = bytes(random_bytes(SECURE_NONCE_BYTES))
    if len(salt) != SECURE_SALT_BYTES or len(nonce) != SECURE_NONCE_BYTES:
        raise RuntimeError('cryptographic random source returned an invalid result')
    encoded_files = {}
    for path, payload in (files or {}).items():
        if not isinstance(path, str) or not path:
            raise ValueError('backup file path is invalid')
        encoded_files[path] = binascii.hexlify(bytes(payload)).decode()
    content = {
        'format_version': SECURE_FORMAT_VERSION,
        'created_at': int(time.time()) if time else 0,
        'metadata': metadata or {},
        'credentials': credentials,
        'module_settings': module_settings,
        'files': encoded_files,
    }
    plaintext = json.dumps(content, separators=(',', ':')).encode()
    if len(plaintext) > MAX_IMPORT_BYTES:
        raise ValueError('complete configuration exceeds the backup size limit')
    crypto = _secure_crypto()
    key = crypto.pbkdf2_sha256(
        _password_bytes(password), salt, SECURE_KDF_ITERATIONS
    )
    encrypted = crypto.aes_gcm_encrypt(key, nonce, plaintext, SECURE_FORMAT.encode())
    if len(encrypted) < SECURE_TAG_BYTES:
        raise RuntimeError('encrypted backup result is invalid')
    return {
        'format': SECURE_FORMAT,
        'format_version': SECURE_FORMAT_VERSION,
        'kdf': 'pbkdf2-sha256',
        'iterations': SECURE_KDF_ITERATIONS,
        'salt': binascii.hexlify(salt).decode(),
        'cipher': 'aes-256-gcm',
        'nonce': binascii.hexlify(nonce).decode(),
        'ciphertext': binascii.hexlify(encrypted[:-SECURE_TAG_BYTES]).decode(),
        'tag': binascii.hexlify(encrypted[-SECURE_TAG_BYTES:]).decode(),
    }


def parse_secure_import(payload, password):
    """Authenticate and decrypt a full-device backup without exposing secrets."""
    if isinstance(payload, bytes):
        if len(payload) > MAX_IMPORT_BYTES * 3:
            raise ValueError('encrypted backup exceeds the size limit')
        payload = payload.decode()
    envelope = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(envelope, dict):
        raise ValueError('encrypted backup must contain an object')
    if (
        envelope.get('format') != SECURE_FORMAT or
        envelope.get('format_version') != SECURE_FORMAT_VERSION or
        envelope.get('kdf') != 'pbkdf2-sha256' or
        envelope.get('cipher') != 'aes-256-gcm'
    ):
        raise ValueError('encrypted backup format is not supported')
    try:
        iterations = int(envelope.get('iterations', 0))
        salt = binascii.unhexlify(envelope.get('salt', ''))
        nonce = binascii.unhexlify(envelope.get('nonce', ''))
        ciphertext = binascii.unhexlify(envelope.get('ciphertext', ''))
        tag = binascii.unhexlify(envelope.get('tag', ''))
    except Exception:
        raise ValueError('encrypted backup encoding is invalid')
    if (
        iterations != SECURE_KDF_ITERATIONS or len(salt) != SECURE_SALT_BYTES or
        len(nonce) != SECURE_NONCE_BYTES or len(tag) != SECURE_TAG_BYTES
    ):
        raise ValueError('encrypted backup parameters are invalid')
    crypto = _secure_crypto()
    key = crypto.pbkdf2_sha256(_password_bytes(password), salt, iterations)
    try:
        plaintext = crypto.aes_gcm_decrypt(
            key, nonce, ciphertext + tag, SECURE_FORMAT.encode()
        )
    except Exception:
        raise ValueError('encrypted backup authentication failed')
    try:
        content = json.loads(plaintext)
    except Exception:
        raise ValueError('encrypted backup contents are invalid')
    if (
        not isinstance(content, dict) or
        content.get('format_version') != SECURE_FORMAT_VERSION or
        not isinstance(content.get('credentials'), dict) or
        not isinstance(content.get('module_settings'), dict) or
        not isinstance(content.get('files'), dict)
    ):
        raise ValueError('encrypted backup contents are incomplete')
    decoded_files = {}
    try:
        for path, encoded in content['files'].items():
            if not isinstance(path, str) or not path:
                raise ValueError
            decoded_files[path] = binascii.unhexlify(encoded)
    except Exception:
        raise ValueError('encrypted backup file data is invalid')
    content['files'] = decoded_files
    return content


def _network_preview(config):
    wifi = (config or {}).get('wifi', {}) or {}
    name = str(wifi.get('ssid', '') or 'Not configured')
    mode = 'DHCP' if wifi.get('dhcp', True) else (
        'Static ' + str(wifi.get('ip_address', '') or 'address not set')
    )
    credential = 'stored password' if wifi.get('password') else 'no password'
    return name + ' · ' + mode + ' · ' + credential


def _mqtt_preview(config):
    mqtt = (config or {}).get('mqtt', {}) or {}
    server = str(mqtt.get('server', '') or 'Not configured')
    if mqtt.get('server'):
        server += ':' + str(mqtt.get('port', 8883))
    credential = 'stored credential' if mqtt.get('password') else 'no stored password'
    return server + ' · ' + credential


def _portal_preview(config):
    portal = (config or {}).get('portal', {}) or {}
    transport = str(portal.get('transport', 'auto'))
    port = portal.get('port')
    port = (8080 if transport == 'http' else 8443) if port is None else port
    timeout_minutes = int(portal.get('session_timeout_s', 3600) or 3600) // 60
    return (
        str(portal.get('username', '') or 'No user') + ' · ' + transport.upper() +
        ':' + str(port) + ' · ' + str(timeout_minutes) + ' min timeout'
    )


def _time_preview(config):
    preferences = (config or {}).get('preferences', {}) or {}
    servers = preferences.get('ntp_servers', ()) or ()
    return (
        str(preferences.get('timezone_name', 'UTC')) + ' · ' +
        ', '.join(str(server) for server in servers)
    )


def _logging_preview(config):
    preferences = (config or {}).get('preferences', {}) or {}
    syslog = (config or {}).get('syslog', {}) or {}
    remote = 'remote syslog off'
    if syslog.get('enabled'):
        remote = (
            str(syslog.get('transport', 'udp')).upper() + ' to ' +
            str(syslog.get('host', '')) + ':' + str(syslog.get('port', 514))
        )
    return (
        str(preferences.get('loglevel', 'INFO')) + ' · ' +
        str(preferences.get('log_buffer_lines', 200)) + ' lines · ' + remote
    )


def _api_preview(config):
    api = (config or {}).get('api', {}) or {}
    return (
        ('Enabled' if api.get('enabled') else 'Disabled') + ' · port ' +
        str(api.get('port', 8444)) + ' · mutual TLS'
    )


def _module_preview(modules):
    devices = (modules or {}).get('devices', ()) or ()
    labels = [
        str(device.get('name') or device.get('uuid') or 'Unnamed')
        for device in devices if isinstance(device, dict)
    ]
    text = str(len(devices)) + ' module(s)'
    if labels:
        text += ': ' + ', '.join(labels[:8])
        if len(labels) > 8:
            text += ', …'
    return text


def _protected_files_preview(files):
    labels = {
        'portal_certificate': 'portal certificate',
        'portal_private_key': 'portal private key',
        'mqtt_ca': 'MQTT CA', 'release_ca': 'release CA',
        'syslog_ca': 'syslog CA', 'acme_account_key': 'ACME account key',
        'acme_state': 'ACME state', 'api_client_registry': 'API clients',
    }
    names = []
    for name in sorted((files or {}).keys()):
        names.append(
            labels.get(name, 'API client CA' if name.startswith('api_client_ca_') else name)
        )
    return (
        str(len(names)) + ' protected file(s)' +
        (': ' + ', '.join(names) if names else '')
    )


def _secret_preview(config):
    config = config or {}
    portal = config.get('portal', {}) or {}
    recovery = config.get('recovery', {}) or {}
    required = (
        portal.get('password_verifier'),
        recovery.get('password_verifier'), recovery.get('ap_password')
    )
    return 'Protected credentials present' if all(required) else 'Required credential missing'


def _preview_row(path, before, after, missing=False):
    return {
        'path': path,
        'before': before,
        'after': after,
        'state': 'missing' if missing else ('same' if before == after else 'changed'),
    }


def secure_restore_preview(current_credentials, current_modules, current_files,
                           backup_content, current_device_id=''):
    """Describe a complete restore without returning any stored secret value."""
    target = backup_content.get('credentials', {}) or {}
    target_modules = backup_content.get('module_settings', {}) or {}
    target_files = backup_content.get('files', {}) or {}
    metadata = backup_content.get('metadata', {}) or {}
    source_id = str(metadata.get('device_id', '') or 'Not recorded')
    device_name = str(target.get('device_name', '') or 'Missing from backup')
    secret_after = _secret_preview(target)
    rows = [
        _preview_row(
            'Backup source device', str(current_device_id or 'Current device'),
            source_id, source_id == 'Not recorded'
        ),
        _preview_row(
            'Device name', str((current_credentials or {}).get('device_name', '')),
            device_name, device_name == 'Missing from backup'
        ),
        _preview_row(
            'Wi-Fi network', _network_preview(current_credentials),
            _network_preview(target), not bool((target.get('wifi', {}) or {}).get('ssid'))
        ),
        _preview_row(
            'MQTT connection', _mqtt_preview(current_credentials),
            _mqtt_preview(target)
        ),
        _preview_row(
            'Portal access', _portal_preview(current_credentials),
            _portal_preview(target),
            not bool((target.get('portal', {}) or {}).get('username'))
        ),
        _preview_row(
            'Time and NTP', _time_preview(current_credentials), _time_preview(target)
        ),
        _preview_row(
            'Logging', _logging_preview(current_credentials), _logging_preview(target)
        ),
        _preview_row(
            'Device API', _api_preview(current_credentials), _api_preview(target)
        ),
        _preview_row(
            'Module configuration', _module_preview(current_modules),
            _module_preview(target_modules)
        ),
        _preview_row(
            'Certificates, keys and trust', _protected_files_preview(current_files),
            _protected_files_preview(target_files), not bool(target_files)
        ),
        _preview_row(
            'Secret credentials', _secret_preview(current_credentials), secret_after,
            secret_after == 'Required credential missing'
        ),
    ]
    return {'changes': rows, 'change_count': len(rows)}


def _diff(before, after, prefix=''):
    changes = []
    keys = sorted(set(before or {}) | set(after or {}))
    for key in keys:
        path = prefix + '.' + str(key) if prefix else str(key)
        old = (before or {}).get(key)
        new = (after or {}).get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            changes.extend(_diff(old, new, path))
        elif old != new:
            changes.append(_preview_row(
                path, old, new, new is None or new == ''
            ))
    return changes


def prepare_import(payload, current_settings, current_modules,
                   settings_validator, module_validator):
    parsed = parse_import(payload)
    settings = parsed['settings']
    modules = parsed['module_settings']
    settings_validator(settings)
    if modules is not None:
        errors = module_validator(modules)
        if errors:
            raise ValueError('module configuration rejected: ' + '; '.join(errors[:20]))
    target_settings = dict(current_settings)
    target_settings.update(settings)
    changes = _diff(current_settings, target_settings, 'settings')
    if modules is not None:
        changes.extend(_diff(current_modules, modules, 'module_settings'))
    return {
        'settings': settings,
        'module_settings': modules,
        'changes': changes,
        'change_count': len(changes),
    }
