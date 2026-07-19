import json


DEVICE_SETTINGS_FILE = 'device_settings.json'


def load_required_json(filename):
    try:
        with open(filename, 'rb') as settings_file:
            data = json.loads(settings_file.read())
    except OSError as exc:
        raise RuntimeError('Required JSON settings file not found: ' + filename + ' - ' + str(exc))
    except ValueError as exc:
        raise RuntimeError('Invalid JSON in settings file: ' + filename + ' - ' + str(exc))

    if not isinstance(data, dict):
        raise RuntimeError('Invalid JSON settings file: ' + filename + ' must contain a JSON object')

    return data


def _section(config, key, required=False):
    if key not in config:
        if required:
            raise RuntimeError('Invalid device_settings.json: missing ' + key)
        return {}
    section = config[key]
    if not isinstance(section, dict):
        raise RuntimeError('Invalid device_settings.json: ' + key + ' must be dict')
    return section


def _reject_unknown(config, allowed, path):
    for key in config:
        if key not in allowed:
            raise RuntimeError('Invalid device_settings.json: unknown ' + path + '.' + str(key))


def _require(config, key, expected_type, path):
    if key not in config:
        raise RuntimeError('Invalid device_settings.json: missing ' + path)
    _validate_type(config, key, expected_type, path)
    return config[key]


def _optional(config, key, expected_type, default, path):
    if key not in config:
        return default
    _validate_type(config, key, expected_type, path)
    return config[key]


def _validate_type(config, key, expected_type, path):
    value = config[key]
    if not _matches_type(value, expected_type):
        raise RuntimeError(
            'Invalid device_settings.json: ' + path +
            ' must be ' + _type_label(expected_type)
        )


def _matches_type(value, expected_type):
    if isinstance(expected_type, tuple):
        for item in expected_type:
            if _matches_type(value, item):
                return True
        return False
    if expected_type is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected_type)


def _type_label(expected_type):
    if isinstance(expected_type, tuple):
        labels = []
        for item in expected_type:
            labels.append(_type_label(item))
        return ' or '.join(labels)
    if expected_type is type(None):
        return 'null'
    return expected_type.__name__


def _validate_ntp_servers(value):
    if not isinstance(value, list) or not value:
        raise RuntimeError('Invalid device_settings.json: device.ntp_servers must be a non-empty list')
    for server in value:
        if not isinstance(server, str) or not server:
            raise RuntimeError('Invalid device_settings.json: device.ntp_servers entries must be non-empty strings')


def _validate_loglevel(value):
    if value not in ('ERROR', 'INFO', 'DEBUG'):
        raise RuntimeError('Invalid device_settings.json: device.loglevel must be ERROR, INFO, or DEBUG')


_settings = load_required_json(DEVICE_SETTINGS_FILE)
_reject_unknown(_settings, ('device', 'ha', 'web_portal', 'local_display'), 'section')
_device = _section(_settings, 'device', True)
_ha = _section(_settings, 'ha')
_web_portal = _section(_settings, 'web_portal')
local_display = _section(_settings, 'local_display')

_reject_unknown(_device, (
    'name',
    'module_settings_file',
    'ca_cert_path',
    'loglevel',
    'watchdog_timeout_ms',
    'status_led_pin',
    'status_led_type',
    'ntp_servers',
    'wifi_recovery_enabled',
    'wifi_recovery_timeout_s'
), 'device')
_reject_unknown(_ha, (
    'discovery',
    'discovery_cleanup_legacy_identity',
    'discovery_cleanup_legacy',
    'discovery_cleanup_legacy_count',
    'system_diagnostics',
    'device_info'
), 'ha')
_reject_unknown(_web_portal, (
    'enabled',
    'https',
    'host',
    'port',
    'cert_path',
    'key_path',
    'log_refresh_s',
    'value_refresh_s',
    'log_buffer_lines',
    'log_line_max_chars',
    'updates_enabled',
    'update_max_bytes',
    'allow_protected_updates',
    'firmware_updates_enabled',
    'firmware_update_max_bytes',
    'release_manifest_url',
    'release_channel',
    'release_check_interval_s',
    'release_auto_download',
    'release_auto_activate',
    'session_timeout_s'
), 'web_portal')
_reject_unknown(local_display, (
    'enabled',
    'type',
    'width',
    'height',
    'spi',
    'sck',
    'mosi',
    'cs',
    'dc',
    'rst',
    'baudrate',
    'rotate',
    'refresh_ms',
    'button_poll_ms',
    'long_press_ms',
    'button_a',
    'button_b',
    'button_active_low',
    'button_a_short',
    'button_a_long',
    'button_b_short',
    'button_b_long'
), 'local_display')

module_settings_file = _require(_device, 'module_settings_file', str, 'device.module_settings_file')
ca_cert_path = _require(_device, 'ca_cert_path', str, 'device.ca_cert_path')
ha_device_name = _require(_device, 'name', str, 'device.name')

ntp_servers = _optional(_device, 'ntp_servers', list, ['pool.ntp.org'], 'device.ntp_servers')
_validate_ntp_servers(ntp_servers)

ha_device_info = _optional(_ha, 'device_info', dict, {}, 'ha.device_info')
loglevel = _optional(_device, 'loglevel', str, 'INFO', 'device.loglevel')
_validate_loglevel(loglevel)
watchdog_timeout_ms = _optional(_device, 'watchdog_timeout_ms', int, 0, 'device.watchdog_timeout_ms')
wifi_recovery_enabled = _optional(_device, 'wifi_recovery_enabled', bool, False, 'device.wifi_recovery_enabled')
wifi_recovery_timeout_s = _optional(_device, 'wifi_recovery_timeout_s', int, 900, 'device.wifi_recovery_timeout_s')
status_led_pin = _optional(_device, 'status_led_pin', (int, str, type(None)), None, 'device.status_led_pin')
status_led_type = _optional(_device, 'status_led_type', str, 'auto', 'device.status_led_type')
if status_led_type not in ('auto', 'digital', 'neopixel'):
    raise RuntimeError('Invalid device_settings.json: device.status_led_type must be auto, digital, or neopixel')

ha_discovery = _optional(_ha, 'discovery', bool, False, 'ha.discovery')
ha_discovery_cleanup_legacy_identity = _optional(_ha, 'discovery_cleanup_legacy_identity', bool, False, 'ha.discovery_cleanup_legacy_identity')
ha_discovery_cleanup_legacy = _optional(_ha, 'discovery_cleanup_legacy', bool, False, 'ha.discovery_cleanup_legacy')
ha_discovery_cleanup_legacy_count = _optional(_ha, 'discovery_cleanup_legacy_count', int, 64, 'ha.discovery_cleanup_legacy_count')
ha_system_diagnostics = _optional(_ha, 'system_diagnostics', bool, False, 'ha.system_diagnostics')

web_portal_enabled = _optional(_web_portal, 'enabled', bool, False, 'web_portal.enabled')
web_portal_https = _optional(_web_portal, 'https', bool, False, 'web_portal.https')
web_portal_host = _optional(_web_portal, 'host', str, '0.0.0.0', 'web_portal.host')
web_portal_port = _optional(_web_portal, 'port', (int, type(None)), None, 'web_portal.port')
web_portal_cert_path = _optional(_web_portal, 'cert_path', str, '/certs/web.crt.der', 'web_portal.cert_path')
web_portal_key_path = _optional(_web_portal, 'key_path', str, '/certs/web.key.der', 'web_portal.key_path')
web_portal_updates_enabled = _optional(_web_portal, 'updates_enabled', bool, False, 'web_portal.updates_enabled')
web_portal_update_max_bytes = _optional(_web_portal, 'update_max_bytes', int, 2097152, 'web_portal.update_max_bytes')
web_portal_allow_protected_updates = _optional(_web_portal, 'allow_protected_updates', bool, False, 'web_portal.allow_protected_updates')
web_portal_firmware_updates_enabled = _optional(_web_portal, 'firmware_updates_enabled', bool, False, 'web_portal.firmware_updates_enabled')
web_portal_firmware_update_max_bytes = _optional(_web_portal, 'firmware_update_max_bytes', int, 4194304, 'web_portal.firmware_update_max_bytes')
release_manifest_url = _optional(_web_portal, 'release_manifest_url', str, '', 'web_portal.release_manifest_url')
release_channel = _optional(_web_portal, 'release_channel', str, 'stable', 'web_portal.release_channel')
release_check_interval_s = _optional(_web_portal, 'release_check_interval_s', int, 21600, 'web_portal.release_check_interval_s')
release_auto_download = _optional(_web_portal, 'release_auto_download', bool, False, 'web_portal.release_auto_download')
release_auto_activate = _optional(_web_portal, 'release_auto_activate', bool, False, 'web_portal.release_auto_activate')
web_portal_session_timeout_s = _optional(_web_portal, 'session_timeout_s', int, 28800, 'web_portal.session_timeout_s')
web_portal_log_refresh_s = _optional(
    _web_portal,
    'log_refresh_s',
    int,
    5,
    'web_portal.log_refresh_s'
)
web_portal_value_refresh_s = _optional(_web_portal, 'value_refresh_s', int, 0, 'web_portal.value_refresh_s')
web_log_buffer_lines = _optional(_web_portal, 'log_buffer_lines', int, 100, 'web_portal.log_buffer_lines')
web_log_line_max_chars = _optional(_web_portal, 'log_line_max_chars', int, 300, 'web_portal.log_line_max_chars')
