"""Encrypted-NVS backed device credentials.

Production firmware enables both flash encryption and ESP-IDF NVS encryption.
Credentials therefore live in NVS rather than in an importable Python source
file.  Two slots plus an independently committed selector make updates
resilient to power loss.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    import esp32
except ImportError:
    esp32 = None

from credential_schema import (
    MAX_PORTAL_USERS, MIN_PASSWORD_LENGTH, PORTAL_ROLES,
    SCHEMA_VERSION, SUPPORTED_TIMEZONES, _validate_wifi_ipv4, validate,
)


NAMESPACE = 'ham_config'
MAX_CONFIG_BYTES = 8192
NETWORK_TRIAL_KEY = 'nettrial'
MAX_NETWORK_TRIAL_BYTES = 8192
FACTORY_RESET_KEY = 'factoryreset'
_memory_values = {}

class _MemoryNVS:
    """CPython test backend; production always uses ``esp32.NVS``."""

    def set_blob(self, key, value):
        _memory_values[key] = bytes(value)

    def get_blob(self, key, buffer):
        if key not in _memory_values:
            raise OSError('NVS key not found')
        value = _memory_values[key]
        if len(value) > len(buffer):
            raise OSError('NVS buffer is too small')
        buffer[:len(value)] = value
        return len(value)

    def set_i32(self, key, value):
        _memory_values[key] = int(value)

    def get_i32(self, key):
        if key not in _memory_values:
            raise OSError('NVS key not found')
        return int(_memory_values[key])

    def erase_key(self, key):
        if key not in _memory_values:
            raise OSError('NVS key not found')
        del _memory_values[key]

    def commit(self):
        return None


def _nvs():
    if esp32 is None:
        return _MemoryNVS()
    return esp32.NVS(NAMESPACE)


def _read_blob(store, key, maximum=MAX_CONFIG_BYTES):
    buffer = bytearray(maximum)
    length = store.get_blob(key, buffer)
    if length <= 0 or length > maximum:
        raise ValueError('invalid credential blob length')
    return bytes(buffer[:length])


def _write_blob(store, key, value):
    store.set_blob(key, bytes(value))
    store.commit()


def _erase(store, key):
    try:
        store.erase_key(key)
    except OSError:
        pass

def configure_station(station, wifi):
    """Apply DHCP or a validated static IPv4 tuple before Wi-Fi connects."""
    wifi = wifi or {}
    _validate_wifi_ipv4(wifi)
    station.active(True)
    if wifi.get('dhcp', True):
        ipconfig = getattr(station, 'ipconfig', None)
        if ipconfig:
            ipconfig(dhcp4=True)
        else:
            station.ifconfig('dhcp')
    else:
        station.ifconfig((
            wifi.get('ip_address', ''), wifi.get('subnet_mask', ''),
            wifi.get('gateway', ''), wifi.get('dns_server', '')
        ))
    return station

def load(require_provisioned=False):
    store = _nvs()
    candidates = []
    try:
        active = store.get_i32('active')
        if active in (0, 1):
            candidates.append(active)
    except OSError:
        pass
    candidates.extend(slot for slot in (0, 1) if slot not in candidates)
    for slot in candidates:
        try:
            config = json.loads(_read_blob(store, 'cfg' + str(slot)).decode())
            if int(config.get('schema', 0)) == 4:
                config = _migrate_v4(config)
            if int(config.get('schema', 0)) == 5:
                config = _migrate_v5(config)
            if int(config.get('schema', 0)) == 6:
                config = _migrate_v6(config)
            return validate(config, require_provisioned)
        except Exception:
            continue
    if require_provisioned:
        raise RuntimeError('device setup is incomplete or unreadable')
    return {}


def _migrate_v4(config):
    config = json.loads(json.dumps(config))
    config['schema'] = 5
    config['api'] = {
        'enabled': False,
        'port': getattr(__import__('device_config'), 'DEVICE_API_PORT', 8444),
        'auth': 'mtls',
    }
    return config


def _migrate_v5(config):
    config = json.loads(json.dumps(config))
    config['schema'] = SCHEMA_VERSION
    portal = config.setdefault('portal', {})
    # RC4 and earlier stored eight hours as the implicit default. Preserve
    # explicit non-default choices while moving untouched devices to 60 min.
    if int(portal.get('session_timeout_s', 28800)) == 28800:
        portal['session_timeout_s'] = 3600
    return config


def _migrate_v6(config):
    config = json.loads(json.dumps(config))
    config['schema'] = SCHEMA_VERSION
    portal = config.setdefault('portal', {})
    portal['users'] = [{
        'username': portal.get('username', 'admin'),
        'password_verifier': portal.get('password_verifier', ''),
        'role': 'administrator',
        'enabled': True,
    }]
    return config


def save(config):
    validate(config)
    encoded = json.dumps(config, separators=(',', ':')).encode()
    if len(encoded) > MAX_CONFIG_BYTES:
        raise ValueError('credential configuration exceeds encrypted NVS capacity')
    store = _nvs()
    try:
        active = store.get_i32('active')
    except OSError:
        active = 1
    target = 1 if active == 0 else 0
    store.set_blob('cfg' + str(target), encoded)
    store.commit()
    store.set_i32('active', target)
    store.commit()
    return config


def _network_snapshot(config):
    wifi = config.get('wifi', {}) if isinstance(config, dict) else {}
    return {
        'ssid': wifi.get('ssid', ''),
        'password': wifi.get('password', ''),
        'dhcp': wifi.get('dhcp', True),
        'ip_address': wifi.get('ip_address', ''),
        'subnet_mask': wifi.get('subnet_mask', ''),
        'gateway': wifi.get('gateway', ''),
        'dns_server': wifi.get('dns_server', ''),
    }


def _read_network_trial():
    try:
        value = json.loads(
            _read_blob(_nvs(), NETWORK_TRIAL_KEY, MAX_NETWORK_TRIAL_BYTES).decode()
        )
        if (
            not isinstance(value, dict) or int(value.get('version', 0)) != 1 or
            not isinstance(value.get('previous'), dict) or
            not isinstance(value.get('candidate_wifi'), dict)
        ):
            raise ValueError('network trial record is invalid')
        return value
    except Exception:
        return {}


def _write_network_trial(value):
    encoded = json.dumps(value, separators=(',', ':')).encode()
    if len(encoded) > MAX_NETWORK_TRIAL_BYTES:
        raise ValueError('network rollback record exceeds encrypted NVS capacity')
    _write_blob(_nvs(), NETWORK_TRIAL_KEY, encoded)


def _clear_network_trial():
    store = _nvs()
    _erase(store, NETWORK_TRIAL_KEY)
    store.commit()


def begin_network_trial(previous, candidate):
    """Commit candidate network settings while retaining a rollback generation."""
    validate(previous, require_provisioned=True)
    validate(candidate, require_provisioned=True)
    if _network_snapshot(previous) == _network_snapshot(candidate):
        save(candidate)
        return False
    trial = {
        'version': 1,
        'attempts': 0,
        'previous': previous,
        'candidate_wifi': _network_snapshot(candidate),
    }
    _write_network_trial(trial)
    try:
        save(candidate)
    except Exception:
        _clear_network_trial()
        raise
    return True


def network_trial_pending():
    trial = _read_network_trial()
    if not trial:
        return False
    try:
        return _network_snapshot(load(require_provisioned=True)) == trial['candidate_wifi']
    except Exception:
        return False


def prepare_network_trial_boot():
    """Allow one candidate boot; restore the previous generation after any reset."""
    trial = _read_network_trial()
    if not trial:
        return 'none'
    current = load(require_provisioned=True)
    if _network_snapshot(current) != trial['candidate_wifi']:
        _clear_network_trial()
        return 'cleared'
    if int(trial.get('attempts', 0)) >= 1:
        rollback_network_trial()
        return 'rolled_back'
    trial['attempts'] = 1
    _write_network_trial(trial)
    return 'trial'


def confirm_network_trial():
    trial = _read_network_trial()
    if not trial:
        return False
    if _network_snapshot(load(require_provisioned=True)) != trial['candidate_wifi']:
        return False
    _clear_network_trial()
    return True


def rollback_network_trial():
    trial = _read_network_trial()
    if not trial:
        return False
    previous = trial.get('previous')
    validate(previous, require_provisioned=True)
    save(previous)
    _clear_network_trial()
    return True


def is_provisioned():
    try:
        return load(require_provisioned=True).get('provisioned') is True
    except Exception:
        return False


def build_configuration(values, portal_password, recovery_password):
    """Validate setup fields and replace plaintext login passwords with verifiers."""
    import credential_security
    try:
        import uos as os
    except ImportError:
        import os
    recovery_ap_password = values.get('recovery_ap_password', '')
    if len(set((portal_password, recovery_password, recovery_ap_password))) != 3:
        raise ValueError('portal, recovery console and recovery AP passwords must all differ')
    if not hasattr(os, 'urandom'):
        raise RuntimeError('cryptographic random source is unavailable')
    portal_verifier = credential_security.password_verifier(
        portal_password, os.urandom(credential_security.PASSWORD_SALT_BYTES)
    )
    recovery_verifier = credential_security.password_verifier(
        recovery_password, os.urandom(credential_security.PASSWORD_SALT_BYTES)
    )
    config = {
        'schema': SCHEMA_VERSION,
        'provisioned': False,
        'device_name': values.get('device_name', ''),
        'wifi': {
            'ssid': values.get('wifi_ssid', ''),
            'password': values.get('wifi_password', ''),
            'dhcp': bool(values.get('wifi_dhcp', True)),
            'ip_address': values.get('wifi_ip_address', ''),
            'subnet_mask': values.get('wifi_subnet_mask', ''),
            'gateway': values.get('wifi_gateway', ''),
            'dns_server': values.get('wifi_dns_server', ''),
        },
        'mqtt': {
            'server': values.get('mqtt_server', ''),
            'port': int(values.get('mqtt_port', 8883)),
            'username': values.get('mqtt_username', ''),
            'password': values.get('mqtt_password', ''),
            'ssl': bool(values.get('mqtt_ssl', False)),
            'configured': bool(values.get('mqtt_server', '')),
        },
        'portal': {
            'username': values.get('portal_username', ''),
            'password_verifier': portal_verifier,
            'users': [{
                'username': values.get('portal_username', ''),
                'password_verifier': portal_verifier,
                'role': 'administrator',
                'enabled': True,
            }],
            'transport': values.get('portal_transport', 'auto'),
            'port': (
                int(values.get('portal_port'))
                if str(values.get('portal_port', '')).strip() else None
            ),
            'session_timeout_s': int(values.get('portal_session_timeout_s', 3600)),
        },
        'recovery': {
            'ap_password': values.get('recovery_ap_password', ''),
            'password_verifier': recovery_verifier,
        },
        'release': {
            'channel': values.get('channel', 'stable'),
            'install_mode': values.get('install_mode', 'upload'),
        },
        'certificate': {
            'mode': values.get('certificate_mode', 'manual'),
            'directory_url': values.get('acme_directory_url', ''),
            'hostname': values.get('certificate_hostname', ''),
        },
        'preferences': {
            'loglevel': values.get('loglevel', 'INFO'),
            'ntp_servers': values.get(
                'ntp_servers', ['pool.ntp.org', 'time.google.com']
            ),
            'timezone_offset_minutes': int(values.get('timezone_offset_minutes', 0)),
            'timezone_name': values.get('timezone_name', 'UTC'),
            'log_buffer_lines': int(values.get('log_buffer_lines', 200)),
            'ha_discovery': bool(values.get('ha_discovery', True)),
            'release_auto_download': bool(
                values.get('release_auto_download', False)
            ),
            'release_auto_activate': bool(
                values.get('release_auto_activate', False)
            ),
            'release_check_schedule': str(
                values.get('release_check_schedule', 'disabled')
            ),
            'release_check_time': str(values.get('release_check_time', '03:00')),
            'release_check_weekday': int(values.get('release_check_weekday', 0)),
        },
        'api': {
            'enabled': bool(values.get('api_enabled', False)),
            'port': int(values.get('api_port', 8444)),
            'auth': 'mtls',
        },
        'syslog': {
            'enabled': bool(values.get('syslog_enabled', False)),
            'host': str(values.get('syslog_host', '')).strip(),
            'port': int(values.get('syslog_port', 514)),
            'transport': str(values.get('syslog_transport', 'udp')),
        },
    }
    return validate(config)


def mark_provisioned(config=None):
    config = config or load()
    config['provisioned'] = True
    return save(config)


def update_portal_password(password):
    import credential_security
    try:
        import uos as os
    except ImportError:
        import os
    config = load(require_provisioned=True)
    if password == config['recovery']['ap_password']:
        raise ValueError('administrator and recovery passwords must be different')
    config['portal']['password_verifier'] = credential_security.password_verifier(
        password, os.urandom(credential_security.PASSWORD_SALT_BYTES)
    )
    primary_name = str(config['portal'].get('username', '')).lower()
    for user in config['portal'].get('users', ()):
        if str(user.get('username', '')).lower() == primary_name:
            user['password_verifier'] = config['portal']['password_verifier']
            break
    save(config)
    return config['portal']['password_verifier']


def public_settings():
    """Return portal-editable settings without returning stored secrets."""
    config = load(require_provisioned=True)
    portal_transport = config['portal'].get('transport', 'auto')
    portal_port = config['portal'].get('port')
    if portal_port is None:
        portal_port = 8080 if portal_transport == 'http' else 8443
    syslog = config.get('syslog', {})
    return {
        'device_name': config['device_name'],
        'wifi_ssid': config['wifi']['ssid'],
        'wifi_password_set': bool(config['wifi']['password']),
        'wifi_dhcp': config['wifi'].get('dhcp', True),
        'wifi_ip_address': config['wifi'].get('ip_address', ''),
        'wifi_subnet_mask': config['wifi'].get('subnet_mask', ''),
        'wifi_gateway': config['wifi'].get('gateway', ''),
        'wifi_dns_server': config['wifi'].get('dns_server', ''),
        'network_trial_pending': network_trial_pending(),
        'mqtt_configured': config['mqtt'].get('configured') is True,
        'mqtt_server': config['mqtt']['server'],
        'mqtt_port': config['mqtt']['port'],
        'mqtt_username': config['mqtt']['username'],
        'mqtt_password_set': bool(config['mqtt']['password']),
        'portal_username': config['portal']['username'],
        'portal_transport': portal_transport,
        'portal_port': portal_port,
        'portal_session_timeout_s': config['portal'].get('session_timeout_s', 3600),
        'release_channel': config['release']['channel'],
        'certificate_mode': config['certificate']['mode'],
        'acme_directory_url': config['certificate']['directory_url'],
        'certificate_hostname': config['certificate']['hostname'],
        'loglevel': config['preferences']['loglevel'],
        'ntp_servers': list(config['preferences']['ntp_servers']),
        'timezone_offset_minutes': config['preferences'].get('timezone_offset_minutes', 0),
        'timezone_name': config['preferences'].get('timezone_name', 'UTC'),
        'log_buffer_lines': config['preferences'].get('log_buffer_lines', 200),
        'ha_discovery': config['preferences']['ha_discovery'],
        'release_auto_download': config['preferences']['release_auto_download'],
        'release_auto_activate': config['preferences']['release_auto_activate'],
        'release_check_schedule': config['preferences'].get(
            'release_check_schedule', 'disabled'
        ),
        'release_check_time': config['preferences'].get('release_check_time', '03:00'),
        'release_check_weekday': config['preferences'].get('release_check_weekday', 0),
        'api_enabled': config.get('api', {}).get('enabled', False),
        'api_port': config.get('api', {}).get('port', 8444),
        'api_auth': config.get('api', {}).get('auth', 'mtls'),
        'syslog_enabled': syslog.get('enabled', False),
        'syslog_host': syslog.get('host', ''),
        'syslog_port': syslog.get('port', 514),
        'syslog_transport': syslog.get('transport', 'udp'),
    }


def _apply_operational_settings(config, values):
    if 'device_name' in values:
        config['device_name'] = values['device_name']
    if 'wifi_ssid' in values:
        config['wifi']['ssid'] = values['wifi_ssid']
    if 'wifi_password' in values:
        config['wifi']['password'] = values['wifi_password']
    if 'wifi_dhcp' in values:
        config['wifi']['dhcp'] = bool(values['wifi_dhcp'])
    for field in ('ip_address', 'subnet_mask', 'gateway', 'dns_server'):
        key = 'wifi_' + field
        if key in values:
            config['wifi'][field] = values[key]
    if 'mqtt_server' in values:
        config['mqtt']['server'] = values['mqtt_server']
        config['mqtt']['configured'] = bool(values['mqtt_server'])
    if 'mqtt_port' in values:
        config['mqtt']['port'] = int(values['mqtt_port'])
    if 'mqtt_username' in values:
        config['mqtt']['username'] = values['mqtt_username']
    if 'mqtt_password' in values:
        config['mqtt']['password'] = values['mqtt_password']
    if 'portal_username' in values:
        old_username = str(config['portal'].get('username', '')).lower()
        config['portal']['username'] = values['portal_username']
        for user in config['portal'].get('users', ()):
            if str(user.get('username', '')).lower() == old_username:
                user['username'] = values['portal_username']
                break
    if 'portal_transport' in values:
        config['portal']['transport'] = values['portal_transport']
    if 'portal_port' in values:
        value = values['portal_port']
        config['portal']['port'] = (
            int(value) if value is not None and str(value).strip() else None
        )
    if 'portal_session_timeout_s' in values:
        config['portal']['session_timeout_s'] = int(values['portal_session_timeout_s'])
    if 'release_channel' in values:
        config['release']['channel'] = values['release_channel']
    if any(key in values for key in (
        'certificate_mode', 'acme_directory_url', 'certificate_hostname'
    )):
        certificate = config.setdefault('certificate', {})
        if 'certificate_mode' in values:
            certificate['mode'] = str(values['certificate_mode'])
        if 'acme_directory_url' in values:
            certificate['directory_url'] = str(values['acme_directory_url']).strip()
        if 'certificate_hostname' in values:
            certificate['hostname'] = str(values['certificate_hostname']).strip()
    if 'loglevel' in values:
        config['preferences']['loglevel'] = values['loglevel']
    if 'ntp_servers' in values:
        config['preferences']['ntp_servers'] = list(values['ntp_servers'])
    if 'timezone_offset_minutes' in values:
        config['preferences']['timezone_offset_minutes'] = int(
            values['timezone_offset_minutes']
        )
    if 'timezone_name' in values:
        config['preferences']['timezone_name'] = str(values['timezone_name'])
    if 'log_buffer_lines' in values:
        config['preferences']['log_buffer_lines'] = int(values['log_buffer_lines'])
    if 'ha_discovery' in values:
        config['preferences']['ha_discovery'] = bool(values['ha_discovery'])
    if 'release_auto_download' in values:
        config['preferences']['release_auto_download'] = bool(
            values['release_auto_download']
        )
    if 'release_auto_activate' in values:
        config['preferences']['release_auto_activate'] = bool(
            values['release_auto_activate']
        )
    if 'release_check_schedule' in values:
        config['preferences']['release_check_schedule'] = str(
            values['release_check_schedule']
        )
    if 'release_check_time' in values:
        config['preferences']['release_check_time'] = str(values['release_check_time'])
    if 'release_check_weekday' in values:
        config['preferences']['release_check_weekday'] = int(
            values['release_check_weekday']
        )
    if 'api_enabled' in values:
        config['api']['enabled'] = bool(values['api_enabled'])
    if 'api_port' in values:
        config['api']['port'] = int(values['api_port'])
    if any(key in values for key in (
        'syslog_enabled', 'syslog_host', 'syslog_port', 'syslog_transport'
    )):
        syslog = config.setdefault('syslog', {})
        if 'syslog_enabled' in values:
            syslog['enabled'] = bool(values['syslog_enabled'])
        if 'syslog_host' in values:
            syslog['host'] = str(values['syslog_host']).strip()
        if 'syslog_port' in values:
            syslog['port'] = int(values['syslog_port'])
        if 'syslog_transport' in values:
            syslog['transport'] = str(values['syslog_transport'])
    return validate(config, require_provisioned=True)


def preview_operational_settings(values):
    """Validate an operational update without writing encrypted NVS."""
    config = json.loads(json.dumps(load(require_provisioned=True)))
    return _apply_operational_settings(config, values)


def update_operational_settings(values, network_trial=False):
    """Atomically update user-serviceable configuration in encrypted NVS."""
    config = load(require_provisioned=True)
    previous = json.loads(json.dumps(config))
    config = _apply_operational_settings(config, values)
    if network_trial:
        begin_network_trial(previous, config)
    else:
        save(config)
    return public_settings()


def update_certificate_settings(mode, directory_url='', hostname=''):
    config = load()
    current = config.get('certificate', {})
    if not hostname:
        hostname = current.get('hostname', '')
    config['certificate'] = {
        'mode': str(mode),
        'directory_url': str(directory_url).strip(),
        'hostname': str(hostname).strip(),
    }
    save(config)
    return config['certificate']


def bootstrap_key():
    try:
        value = _read_blob(_nvs(), 'bootkey', 64).decode()
        if MIN_PASSWORD_LENGTH <= len(value) <= 63:
            return value
    except Exception:
        pass
    return ''


def update_verification_key():
    try:
        value = _read_blob(_nvs(), 'verifykey', 64)
        if len(value) == 64:
            return value
    except Exception:
        pass
    return b''


def erase_bootstrap_key():
    store = _nvs()
    _erase(store, 'bootkey')
    store.commit()


def request_factory_reset(setup_password):
    """Arm an idempotent reset while retaining the OTA verification identity."""
    import credential_security
    setup_password = str(setup_password or '')
    credential_security.validate_password_strength(setup_password)
    if len(setup_password) > 63:
        raise ValueError('setup access-point password must not exceed 63 characters')
    store = _nvs()
    store.set_blob('bootkey', setup_password.encode())
    store.commit()
    store.set_i32(FACTORY_RESET_KEY, 1)
    store.commit()
    return True


def factory_reset_pending():
    try:
        return _nvs().get_i32(FACTORY_RESET_KEY) == 1
    except OSError:
        return False


def complete_factory_reset():
    """Erase user configuration after frozen recovery has cleared user files."""
    if not factory_reset_pending():
        return False
    store = _nvs()
    for key in ('cfg0', 'cfg1', 'active', NETWORK_TRIAL_KEY):
        _erase(store, key)
    store.commit()
    _erase(store, FACTORY_RESET_KEY)
    store.commit()
    return True


def _reset_memory_backend():
    """Test helper; unavailable data is never silently created on-device."""
    _memory_values.clear()
