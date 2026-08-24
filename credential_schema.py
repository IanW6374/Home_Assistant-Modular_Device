"""Validation schema for encrypted device configuration."""

SCHEMA_VERSION = 7
MAX_PORTAL_USERS = 8
PORTAL_ROLES = ('viewer', 'operator', 'administrator')
MIN_PASSWORD_LENGTH = 16
SUPPORTED_TIMEZONES = (
    'UTC', 'Europe/London', 'Europe/Paris', 'Europe/Athens',
    'America/New_York', 'America/Chicago', 'America/Denver',
    'America/Los_Angeles', 'America/Phoenix', 'America/Sao_Paulo',
    'Africa/Johannesburg', 'Asia/Dubai', 'Asia/Kolkata', 'Asia/Shanghai',
    'Asia/Singapore', 'Asia/Tokyo', 'Australia/Perth',
    'Australia/Adelaide', 'Australia/Sydney', 'Pacific/Auckland',
)

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

def validate(config, require_provisioned=False):
    import credential_security
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
    api = config.get('api', {})
    syslog = config.get('syslog', {})
    for value, label in (
        (wifi, 'wifi'), (mqtt, 'mqtt'), (portal, 'portal'),
        (recovery, 'recovery'), (release, 'release'),
        (certificate, 'certificate'), (preferences, 'preferences'),
        (api, 'api'), (syslog, 'syslog')
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
    users = portal.get('users')
    if not isinstance(users, list) or not users or len(users) > MAX_PORTAL_USERS:
        raise ValueError('portal users must contain 1..' + str(MAX_PORTAL_USERS) + ' records')
    usernames = set()
    administrators = 0
    for user in users:
        if not isinstance(user, dict) or set(user) != {
            'username', 'password_verifier', 'role', 'enabled'
        }:
            raise ValueError('portal user record is invalid')
        user_name = _text(user.get('username', ''), 'portal username', 1, 32)
        folded = user_name.lower()
        if folded in usernames:
            raise ValueError('portal usernames must be unique')
        usernames.add(folded)
        if user.get('role') not in PORTAL_ROLES:
            raise ValueError('portal user role is invalid')
        if not isinstance(user.get('enabled'), bool):
            raise ValueError('portal user enabled state must be boolean')
        credential_security.parse_password_verifier(user.get('password_verifier', ''))
        if user.get('role') == 'administrator' and user.get('enabled'):
            administrators += 1
    if administrators < 1:
        raise ValueError('at least one enabled portal administrator is required')
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
    release_schedule = preferences.get('release_check_schedule', 'disabled')
    if release_schedule not in ('disabled', 'daily', 'weekly'):
        raise ValueError('automatic update check schedule is invalid')
    release_time = str(preferences.get('release_check_time', '03:00'))
    try:
        release_hour, release_minute = [int(part) for part in release_time.split(':')]
    except Exception:
        raise ValueError('automatic update check time must use HH:MM')
    if not 0 <= release_hour <= 23 or not 0 <= release_minute <= 59:
        raise ValueError('automatic update check time is invalid')
    release_weekday = preferences.get('release_check_weekday', 0)
    if (
        not isinstance(release_weekday, int) or isinstance(release_weekday, bool) or
        not 0 <= release_weekday <= 6
    ):
        raise ValueError('automatic update check weekday is invalid')
    timezone_offset = preferences.get('timezone_offset_minutes', 0)
    if (
        not isinstance(timezone_offset, int) or isinstance(timezone_offset, bool) or
        not -720 <= timezone_offset <= 840
    ):
        raise ValueError('time-zone offset must be between UTC-12:00 and UTC+14:00')
    timezone_name = preferences.get('timezone_name', 'UTC')
    if timezone_name not in SUPPORTED_TIMEZONES:
        raise ValueError('selected time zone is not supported')
    log_buffer_lines = preferences.get('log_buffer_lines', 200)
    if (
        not isinstance(log_buffer_lines, int) or isinstance(log_buffer_lines, bool) or
        not 0 <= log_buffer_lines <= 500
    ):
        raise ValueError('log entry limit must be between 0 and 500')
    session_timeout_s = portal.get('session_timeout_s', 3600)
    if (
        not isinstance(session_timeout_s, int) or isinstance(session_timeout_s, bool) or
        not 300 <= session_timeout_s <= 86400
    ):
        raise ValueError('portal timeout must be between 300 and 86400 seconds')
    if not isinstance(syslog.get('enabled', False), bool):
        raise ValueError('syslog enabled setting must be true or false')
    if not isinstance(
        syslog.get('audit_enabled', syslog.get('enabled', False)), bool
    ):
        raise ValueError('syslog audit setting must be true or false')
    syslog_host = _text(
        syslog.get('host', ''), 'syslog server',
        1 if (
            syslog.get('enabled', False) or
            syslog.get('audit_enabled', syslog.get('enabled', False))
        ) else 0, 253
    )
    syslog_port = syslog.get('port', 6514 if syslog.get('transport') == 'tls' else 514)
    if (
        not isinstance(syslog_port, int) or isinstance(syslog_port, bool) or
        not 1 <= syslog_port <= 65535
    ):
        raise ValueError('syslog port must be between 1 and 65535')
    if syslog.get('transport', 'udp') not in ('udp', 'tls'):
        raise ValueError('syslog transport must be udp or tls')
    if (
        syslog.get('enabled') or
        syslog.get('audit_enabled', syslog.get('enabled', False))
    ) and not syslog_host:
        raise ValueError('syslog server is required when remote logging is enabled')
    if not isinstance(api.get('enabled', False), bool):
        raise ValueError('device API enabled setting must be true or false')
    api_port = api.get('port', 8444)
    if (
        not isinstance(api_port, int) or isinstance(api_port, bool) or
        not 1 <= api_port <= 65535 or api_port == 80 or
        (api.get('enabled', False) and api_port == portal_port)
    ):
        raise ValueError('device API port must be 1..65535 and differ from the portal port')
    if api.get('auth', 'mtls') != 'mtls':
        raise ValueError('device API authentication must be mtls')
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
