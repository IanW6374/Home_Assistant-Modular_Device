"""Load signed application policy and combine it with core/user ownership."""

try:
    import ujson as json
except ImportError:
    import json

import app_update
import credential_store
import device_config
import update_support
import timezone_rules


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
    'session_timeout_s',
), 'web_portal')

try:
    _runtime_config = credential_store.load(require_provisioned=True)
    _preferences = _runtime_config.get('preferences', {})
    _portal_preferences = _runtime_config.get('portal', {})
    _mqtt_preferences = _runtime_config.get('mqtt', {})
    syslog = _runtime_config.get('syslog', {})
except Exception:
    _preferences = {}
    _portal_preferences = {}
    _mqtt_preferences = {}
    syslog = {}

module_settings_file = device_config.MODULE_SETTINGS_FILE
watchdog_timeout_ms = device_config.WATCHDOG_TIMEOUT_MS
minimum_activation_heap_bytes = getattr(
    device_config, 'MINIMUM_ACTIVATION_HEAP_BYTES', 0
)
wifi_recovery_enabled = device_config.WIFI_RECOVERY_ENABLED
wifi_recovery_timeout_s = device_config.WIFI_RECOVERY_TIMEOUT_S
network_trial_timeout_s = device_config.NETWORK_TRIAL_TIMEOUT_S
status_led_pin = device_config.STATUS_LED_PIN
status_led_type = device_config.STATUS_LED_TYPE

web_portal_host = device_config.WEB_PORTAL_HOST
web_portal_port = device_config.WEB_PORTAL_PORT
web_portal_cert_path = device_config.WEB_PORTAL_CERT_PATH
web_portal_key_path = device_config.WEB_PORTAL_KEY_PATH
api_server_cert_path = device_config.API_SERVER_CERT_PATH
api_server_key_path = device_config.API_SERVER_KEY_PATH
web_portal_update_max_bytes = device_config.WEB_PORTAL_UPDATE_MAX_BYTES
web_portal_firmware_update_max_bytes = (
    device_config.WEB_PORTAL_FIRMWARE_UPDATE_MAX_BYTES
)
web_portal_allow_protected_updates = (
    device_config.WEB_PORTAL_ALLOW_PROTECTED_UPDATES
)
device_api_host = getattr(device_config, 'DEVICE_API_HOST', '0.0.0.0')
device_api_port = getattr(device_config, 'DEVICE_API_PORT', 8444)
device_api_max_body_bytes = getattr(
    device_config, 'DEVICE_API_MAX_BODY_BYTES', 8192
)
api_client_registry_path = getattr(
    device_config, 'API_CLIENT_REGISTRY_PATH', '/certs/api-clients.json'
)
api_client_ca_directory = getattr(
    device_config, 'API_CLIENT_CA_DIRECTORY', '/certs/trust/api-clients'
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
release_check_schedule = str(_preferences.get('release_check_schedule', 'disabled'))
release_check_time = str(_preferences.get('release_check_time', '03:00'))
release_check_weekday = int(_preferences.get('release_check_weekday', 0))
_policy_web_portal_session_timeout_s = _optional(
    _web_portal, 'session_timeout_s', int, 3600, 'web_portal.session_timeout_s'
)
_bounded(_policy_web_portal_session_timeout_s, 'web_portal.session_timeout_s', 300, 86400)
web_portal_session_timeout_s = _preferences.get(
    'portal_session_timeout_s',
    _portal_preferences.get('session_timeout_s', _policy_web_portal_session_timeout_s)
)
web_portal_log_refresh_s = _optional(
    _web_portal, 'log_refresh_s', int, 5, 'web_portal.log_refresh_s'
)
_bounded(web_portal_log_refresh_s, 'web_portal.log_refresh_s', 1)
web_portal_value_refresh_s = _optional(
    _web_portal, 'value_refresh_s', int, 0, 'web_portal.value_refresh_s'
)
_bounded(web_portal_value_refresh_s, 'web_portal.value_refresh_s', 0)
_policy_web_log_buffer_lines = _optional(
    _web_portal, 'log_buffer_lines', int, 100, 'web_portal.log_buffer_lines'
)
_bounded(_policy_web_log_buffer_lines, 'web_portal.log_buffer_lines', 0)
web_log_buffer_lines = _preferences.get(
    'log_buffer_lines', _policy_web_log_buffer_lines
)
_bounded(web_log_buffer_lines, 'preferences.log_buffer_lines', 0, 500)
web_log_line_max_chars = _optional(
    _web_portal, 'log_line_max_chars', int, 300, 'web_portal.log_line_max_chars'
)
_bounded(web_log_line_max_chars, 'web_portal.log_line_max_chars', 1)

ntp_servers = _preferences.get(
    'ntp_servers', ('pool.ntp.org', 'time.google.com')
)
timezone_name = _preferences.get('timezone_name', 'UTC')
timezone_rules.configure(timezone_name)
timezone_offset_minutes = timezone_rules.offset_minutes(timezone_name)
syslog_ca_path = getattr(device_config, 'SYSLOG_CA_PATH', '/certs/trust/syslog-ca.der')
loglevel = _preferences.get('loglevel', 'INFO')
ha_discovery = _preferences.get('ha_discovery', True) is True
ha_discovery_prefix = str(
    _preferences.get('ha_discovery_prefix', 'homeassistant')
).strip().strip('/') or 'homeassistant'
mqtt_enabled = _mqtt_preferences.get(
    'enabled', _mqtt_preferences.get('configured', False)
) is True
mqtt_base_topic = str(
    _mqtt_preferences.get('base_topic', 'iotmd')
).strip().strip('/') or 'iotmd'
mqtt_state_topic = str(_mqtt_preferences.get(
    'state_topic', '{base}/{device_id}/{module_id}/state'
)).strip().strip('/')
mqtt_command_topic = str(_mqtt_preferences.get(
    'command_topic', '{base}/{device_id}/{module_id}/set'
)).strip().strip('/')
mqtt_response_topic = str(_mqtt_preferences.get(
    'response_topic', '{base}/{device_id}/{module_id}/response'
)).strip().strip('/')
mqtt_availability_topic = str(_mqtt_preferences.get(
    'availability_topic', '{base}/{device_id}/availability'
)).strip().strip('/')
mqtt_qos = int(_mqtt_preferences.get('qos', 0))
mqtt_retain_state = _mqtt_preferences.get('retain_state', False) is True
mqtt_command_subscriptions = _mqtt_preferences.get(
    'command_subscriptions', True
) is True
release_auto_download = _preferences.get('release_auto_download', False) is True
release_auto_activate = _preferences.get('release_auto_activate', False) is True

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
    paths = {
        'mqtt': getattr(device_config, 'MQTT_CA_PATH', device_config.TRUST_CA_PATH),
        'release': getattr(device_config, 'RELEASE_CA_PATH', device_config.TRUST_CA_PATH),
        'api_client': getattr(device_config, 'API_CLIENT_CA_PATH', ''),
    }
    if service not in paths:
        raise ValueError('unknown TLS service: ' + str(service))
    path = paths[service]
    checker = exists
    if checker is None:
        def checker(candidate):
            try:
                with open(candidate, 'rb'):
                    return True
            except OSError:
                return False
    if service in ('mqtt', 'release') and not checker(path):
        # Existing RC1 installations migrate without losing trust.  Once a
        # service-specific CA is installed it becomes independent.
        return device_config.TRUST_CA_PATH
    return path


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
