"""Load signed application policy and combine it with core/user ownership."""

try:
    import ujson as json
except ImportError:
    import json

import app_update
import credential_store
import device_config
import update_support


def load_required_json(filename, recover_previous=False):
    try:
        if recover_previous:
            data = update_support.load_json_with_backup(filename)
        else:
            with open(filename, 'rb') as settings_file:
                data = json.loads(settings_file.read())
    except OSError as exc:
        raise RuntimeError(
            'Required JSON settings file not found: ' + filename + ' - ' + str(exc)
        )
    except ValueError as exc:
        raise RuntimeError('Invalid JSON in settings file: ' + filename + ' - ' + str(exc))
    if not isinstance(data, dict):
        raise RuntimeError('Invalid JSON settings file: ' + filename + ' must contain an object')
    return data


def _section(config, key):
    value = config.get(key, {})
    if not isinstance(value, dict):
        raise RuntimeError('Invalid app_settings.json: ' + key + ' must be an object')
    return value


def _reject_unknown(config, allowed, path):
    for key in config:
        if key not in allowed:
            raise RuntimeError('Invalid app_settings.json: unknown ' + path + '.' + str(key))


def _matches_type(value, expected_type):
    if isinstance(expected_type, tuple):
        return any(_matches_type(value, item) for item in expected_type)
    if expected_type is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected_type)


def _optional(config, key, expected_type, default, path):
    if key not in config:
        return default
    value = config[key]
    if not _matches_type(value, expected_type):
        raise RuntimeError('Invalid app_settings.json: ' + path + ' has the wrong type')
    return value


def _bounded(value, path, minimum=None, maximum=None):
    if minimum is not None and value < minimum:
        raise RuntimeError(
            'Invalid app_settings.json: ' + path + ' must be at least ' +
            str(minimum)
        )
    if maximum is not None and value > maximum:
        raise RuntimeError(
            'Invalid app_settings.json: ' + path + ' must not exceed ' +
            str(maximum)
        )
    return value


def _application_file(name):
    root = app_update.application_root()
    return root + '/' + name if root else name


APP_SETTINGS_FILE = _application_file('app_settings.json')
_settings = load_required_json(APP_SETTINGS_FILE)
_reject_unknown(_settings, ('ha', 'web_portal', 'local_display'), 'section')
_ha = _section(_settings, 'ha')
_web_portal = _section(_settings, 'web_portal')
local_display = _section(_settings, 'local_display')

_reject_unknown(_ha, (
    'discovery_cleanup_legacy_identity',
    'discovery_cleanup_legacy',
    'discovery_cleanup_legacy_count',
    'system_diagnostics',
), 'ha')
_reject_unknown(_web_portal, (
    'enabled',
    'log_refresh_s',
    'value_refresh_s',
    'log_buffer_lines',
    'log_line_max_chars',
    'updates_enabled',
    'firmware_updates_enabled',
    'release_manifest_url',
    'release_check_interval_s',
    'session_timeout_s',
), 'web_portal')

try:
    _runtime_config = credential_store.load(require_provisioned=True)
    _preferences = _runtime_config.get('preferences', {})
except Exception:
    _preferences = {}

module_settings_file = device_config.MODULE_SETTINGS_FILE
watchdog_timeout_ms = device_config.WATCHDOG_TIMEOUT_MS
wifi_recovery_enabled = device_config.WIFI_RECOVERY_ENABLED
wifi_recovery_timeout_s = device_config.WIFI_RECOVERY_TIMEOUT_S
network_trial_timeout_s = device_config.NETWORK_TRIAL_TIMEOUT_S
status_led_pin = device_config.STATUS_LED_PIN
status_led_type = device_config.STATUS_LED_TYPE

web_portal_host = device_config.WEB_PORTAL_HOST
web_portal_port = device_config.WEB_PORTAL_PORT
web_portal_cert_path = device_config.WEB_PORTAL_CERT_PATH
web_portal_key_path = device_config.WEB_PORTAL_KEY_PATH
web_portal_update_max_bytes = device_config.WEB_PORTAL_UPDATE_MAX_BYTES
web_portal_firmware_update_max_bytes = (
    device_config.WEB_PORTAL_FIRMWARE_UPDATE_MAX_BYTES
)
web_portal_allow_protected_updates = (
    device_config.WEB_PORTAL_ALLOW_PROTECTED_UPDATES
)

web_portal_enabled = _optional(
    _web_portal, 'enabled', bool, True, 'web_portal.enabled'
)
web_portal_updates_enabled = _optional(
    _web_portal, 'updates_enabled', bool, True, 'web_portal.updates_enabled'
)
web_portal_firmware_updates_enabled = _optional(
    _web_portal, 'firmware_updates_enabled', bool, True,
    'web_portal.firmware_updates_enabled'
)
release_manifest_url = _optional(
    _web_portal, 'release_manifest_url', str, '', 'web_portal.release_manifest_url'
)
release_check_interval_s = _optional(
    _web_portal, 'release_check_interval_s', int, 21600,
    'web_portal.release_check_interval_s'
)
_bounded(release_check_interval_s, 'web_portal.release_check_interval_s', 300)
web_portal_session_timeout_s = _optional(
    _web_portal, 'session_timeout_s', int, 28800, 'web_portal.session_timeout_s'
)
_bounded(web_portal_session_timeout_s, 'web_portal.session_timeout_s', 300, 86400)
web_portal_log_refresh_s = _optional(
    _web_portal, 'log_refresh_s', int, 5, 'web_portal.log_refresh_s'
)
_bounded(web_portal_log_refresh_s, 'web_portal.log_refresh_s', 1)
web_portal_value_refresh_s = _optional(
    _web_portal, 'value_refresh_s', int, 0, 'web_portal.value_refresh_s'
)
_bounded(web_portal_value_refresh_s, 'web_portal.value_refresh_s', 0)
web_log_buffer_lines = _optional(
    _web_portal, 'log_buffer_lines', int, 100, 'web_portal.log_buffer_lines'
)
_bounded(web_log_buffer_lines, 'web_portal.log_buffer_lines', 0)
web_log_line_max_chars = _optional(
    _web_portal, 'log_line_max_chars', int, 300, 'web_portal.log_line_max_chars'
)
_bounded(web_log_line_max_chars, 'web_portal.log_line_max_chars', 1)

ntp_servers = _preferences.get(
    'ntp_servers', ('pool.ntp.org', 'time.google.com')
)
loglevel = _preferences.get('loglevel', 'INFO')
ha_discovery = _preferences.get('ha_discovery', True) is True
release_auto_download = _preferences.get('release_auto_download', False) is True
release_auto_activate = _preferences.get('release_auto_activate', False) is True

ha_discovery_cleanup_legacy_identity = _optional(
    _ha, 'discovery_cleanup_legacy_identity', bool, False,
    'ha.discovery_cleanup_legacy_identity'
)
ha_discovery_cleanup_legacy = _optional(
    _ha, 'discovery_cleanup_legacy', bool, False, 'ha.discovery_cleanup_legacy'
)
ha_discovery_cleanup_legacy_count = _optional(
    _ha, 'discovery_cleanup_legacy_count', int, 64,
    'ha.discovery_cleanup_legacy_count'
)
_bounded(
    ha_discovery_cleanup_legacy_count,
    'ha.discovery_cleanup_legacy_count', 0
)
ha_system_diagnostics = _optional(
    _ha, 'system_diagnostics', bool, False, 'ha.system_diagnostics'
)

ha_device_info = dict(device_config.DEVICE_INFO)
_application_state = app_update.update_status()
if _application_state.get('status') in ('trial', 'committing'):
    _application_version = str(_application_state.get('version', ''))
else:
    _application_version = app_update.running_version('')
if _application_version:
    ha_device_info['sw'] = _application_version


def service_ca_path(service, exists=None):
    if service not in ('mqtt', 'release'):
        raise ValueError('unknown TLS service: ' + str(service))
    return device_config.TRUST_CA_PATH


def service_ca_bytes(service, required=False):
    path = service_ca_path(service)
    try:
        with open(path, 'rb') as stream:
            value = stream.read()
        if not value:
            raise ValueError('trusted CA certificate is empty')
        return value
    except Exception as exc:
        if required:
            raise RuntimeError(
                str(service).upper() + ' trusted CA is unavailable: ' + str(exc)
            )
        return b''
