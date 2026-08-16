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


NAMESPACE = 'ham_config'
SCHEMA_VERSION = 4
MAX_CONFIG_BYTES = 4096
NETWORK_TRIAL_KEY = 'nettrial'
MAX_NETWORK_TRIAL_BYTES = 8192
FACTORY_RESET_KEY = 'factoryreset'
MIN_PASSWORD_LENGTH = 16
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


def _text(value, label, minimum=0, maximum=256):
    if not isinstance(value, str) or len(value) < minimum or len(value) > maximum:
        raise ValueError(label + ' has an invalid length')
    if '\x00' in value:
        raise ValueError(label + ' contains a null character')
    return value


def _ipv4(value, label, required=False):
    value = _text(str(value or '').strip(), label, 1 if required else 0, 15)
    if not value:
        return ''
    parts = value.split('.')
    if len(parts) != 4:
        raise ValueError(label + ' must be an IPv4 address')
    octets = []
    for part in parts:
        if not part or any(character not in '0123456789' for character in part):
            raise ValueError(label + ' must be an IPv4 address')
        number = int(part)
        if number < 0 or number > 255 or str(number) != part:
            raise ValueError(label + ' must be an IPv4 address')
        octets.append(number)
    return '.'.join(str(number) for number in octets)


def _ipv4_integer(value):
    result = 0
    for part in value.split('.'):
        result = (result << 8) | int(part)
    return result


def _validate_wifi_ipv4(wifi):
    dhcp = wifi.get('dhcp', True)
    if not isinstance(dhcp, bool):
        raise ValueError('DHCP setting must be true or false')
    required = not dhcp
    address = _ipv4(wifi.get('ip_address', ''), 'IP address', required)
    subnet = _ipv4(wifi.get('subnet_mask', ''), 'subnet mask', required)
    gateway = _ipv4(wifi.get('gateway', ''), 'default gateway', required)
    dns = _ipv4(wifi.get('dns_server', ''), 'DNS server', required)
    if not required:
        return
    mask = _ipv4_integer(subnet)
    inverse = mask ^ 0xffffffff
    if mask == 0 or mask == 0xffffffff or inverse & (inverse + 1):
        raise ValueError('subnet mask must be a contiguous IPv4 network mask')
    address_value = _ipv4_integer(address)
    gateway_value = _ipv4_integer(gateway)
    if address_value & mask != gateway_value & mask:
        raise ValueError('IP address and default gateway must use the same subnet')
    host = address_value & inverse
    if host == 0 or host == inverse:
        raise ValueError('IP address cannot be the subnet network or broadcast address')
    gateway_host = gateway_value & inverse
    if gateway_host == 0 or gateway_host == inverse:
        raise ValueError('default gateway cannot be the subnet network or broadcast address')
    if gateway_value == address_value:
        raise ValueError('default gateway cannot be the device IP address')
    if address in ('0.0.0.0', '255.255.255.255') or dns == '0.0.0.0':
        raise ValueError('static network addresses cannot use an unspecified address')


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


def validate(config, require_provisioned=False):
    if not isinstance(config, dict):
        raise ValueError('credential configuration must be an object')
    if int(config.get('schema', 0)) != SCHEMA_VERSION:
        raise ValueError('unsupported credential configuration schema')
    provisioned = config.get('provisioned') is True
    if require_provisioned and not provisioned:
        raise ValueError('device setup is incomplete')

    wifi = config.get('wifi', {})
    mqtt = config.get('mqtt', {})
    portal = config.get('portal', {})
    recovery = config.get('recovery', {})
    release = config.get('release', {})
    certificate = config.get('certificate', {})
    preferences = config.get('preferences', {})
    for value, label in (
        (wifi, 'wifi'), (mqtt, 'mqtt'), (portal, 'portal'),
        (recovery, 'recovery'), (release, 'release'),
        (certificate, 'certificate'), (preferences, 'preferences')
    ):
        if not isinstance(value, dict):
            raise ValueError(label + ' credentials must be an object')

    _text(config.get('device_name', ''), 'device name', 1, 64)
    _text(wifi.get('ssid', ''), 'Wi-Fi SSID', 1, 32)
    wifi_password = _text(wifi.get('password', ''), 'Wi-Fi password', 0, 64)
    if wifi_password and len(wifi_password) < 8:
        raise ValueError('Wi-Fi password must contain at least 8 characters')
    if len(wifi_password) == 64:
        try:
            int(wifi_password, 16)
        except ValueError:
            raise ValueError('a 64-character Wi-Fi password must be hexadecimal')
    _validate_wifi_ipv4(wifi)
    mqtt_configured = mqtt.get('configured') is True
    mqtt_server = _text(mqtt.get('server', ''), 'MQTT server', 1 if mqtt_configured else 0, 253)
    if bool(mqtt_server) != mqtt_configured:
        raise ValueError('MQTT configured state does not match the broker hostname')
    port = mqtt.get('port', 0)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError('MQTT port must be between 1 and 65535')
    _text(mqtt.get('username', ''), 'MQTT username', 0, 128)
    _text(mqtt.get('password', ''), 'MQTT password', 0, 256)
    if mqtt.get('ssl') is not True:
        raise ValueError('MQTT TLS is mandatory')

    _text(portal.get('username', ''), 'portal username', 1, 32)
    if portal.get('transport', 'auto') not in ('auto', 'https', 'http'):
        raise ValueError('portal transport must be auto, https or http')
    portal_port = portal.get('port')
    if (
        portal_port is not None and (
            not isinstance(portal_port, int) or isinstance(portal_port, bool) or
            not 1 <= portal_port <= 65535 or portal_port == 80
        )
    ):
        raise ValueError('portal port must be blank or 1..65535 excluding reserved port 80')
    _text(recovery.get('ap_password', ''), 'recovery AP password', MIN_PASSWORD_LENGTH, 63)
    import credential_security
    credential_security.validate_password_strength(recovery.get('ap_password', ''))
    credential_security.parse_password_verifier(portal.get('password_verifier', ''))
    credential_security.parse_password_verifier(recovery.get('password_verifier', ''))
    if release.get('channel') not in ('stable', 'beta'):
        raise ValueError('release channel must be stable or beta')
    if release.get('install_mode') not in ('download', 'upload'):
        raise ValueError('application installation mode is invalid')
    if preferences.get('loglevel') not in ('ERROR', 'INFO', 'DEBUG'):
        raise ValueError('user log level must be ERROR, INFO or DEBUG')
    ntp_servers = preferences.get('ntp_servers')
    if (
        not isinstance(ntp_servers, list) or not ntp_servers or
        any(not isinstance(server, str) or not server or len(server) > 253
            for server in ntp_servers)
    ):
        raise ValueError('user NTP servers must be a non-empty list of hostnames')
    for name in ('ha_discovery', 'release_auto_download', 'release_auto_activate'):
        if not isinstance(preferences.get(name), bool):
            raise ValueError('user preference ' + name + ' must be true or false')
    certificate_mode = certificate.get('mode', 'manual')
    if certificate_mode not in ('self_signed', 'manual', 'acme'):
        raise ValueError('certificate mode must be self_signed, manual or acme')
    directory_url = _text(
        certificate.get('directory_url', ''), 'ACME directory URL',
        1 if certificate_mode == 'acme' else 0, 512
    )
    hostname = _text(
        certificate.get('hostname', ''), 'certificate hostname',
        1 if certificate_mode == 'acme' else 0, 253
    )
    if directory_url and not directory_url.startswith('https://'):
        raise ValueError('ACME directory URL must use HTTPS')
    if hostname and (
        hostname.startswith('.') or hostname.endswith('.') or '..' in hostname or
        any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.' for character in hostname)
    ):
        raise ValueError('certificate hostname is invalid')
    if certificate_mode == 'acme' and not hostname.lower().endswith('.local'):
        raise ValueError('automated certificate hostname must use the .local mDNS domain')
    return config


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
            return validate(config, require_provisioned)
        except Exception:
            continue
    if require_provisioned:
        raise RuntimeError('device setup is incomplete or unreadable')
    return {}


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
            'transport': values.get('portal_transport', 'auto'),
            'port': (
                int(values.get('portal_port'))
                if str(values.get('portal_port', '')).strip() else None
            ),
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
            'ha_discovery': bool(values.get('ha_discovery', True)),
            'release_auto_download': bool(
                values.get('release_auto_download', False)
            ),
            'release_auto_activate': bool(
                values.get('release_auto_activate', False)
            ),
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
    save(config)
    return config['portal']['password_verifier']


def public_settings():
    """Return portal-editable settings without returning stored secrets."""
    config = load(require_provisioned=True)
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
        'portal_transport': config['portal'].get('transport', 'auto'),
        'portal_port': config['portal'].get('port'),
        'release_channel': config['release']['channel'],
        'certificate_mode': config['certificate']['mode'],
        'acme_directory_url': config['certificate']['directory_url'],
        'certificate_hostname': config['certificate']['hostname'],
        'loglevel': config['preferences']['loglevel'],
        'ntp_servers': list(config['preferences']['ntp_servers']),
        'ha_discovery': config['preferences']['ha_discovery'],
        'release_auto_download': config['preferences']['release_auto_download'],
        'release_auto_activate': config['preferences']['release_auto_activate'],
    }


def update_operational_settings(values, network_trial=False):
    """Atomically update user-serviceable configuration in encrypted NVS."""
    config = load(require_provisioned=True)
    previous = json.loads(json.dumps(config))
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
        config['portal']['username'] = values['portal_username']
    if 'portal_transport' in values:
        config['portal']['transport'] = values['portal_transport']
    if 'portal_port' in values:
        value = values['portal_port']
        config['portal']['port'] = (
            int(value) if str(value).strip() else None
        )
    if 'release_channel' in values:
        config['release']['channel'] = values['release_channel']
    if 'loglevel' in values:
        config['preferences']['loglevel'] = values['loglevel']
    if 'ntp_servers' in values:
        config['preferences']['ntp_servers'] = list(values['ntp_servers'])
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
