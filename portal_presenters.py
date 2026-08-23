"""Shared labels and small presentation primitives for portal views."""

from portal_http import html_escape


FRIENDLY_LABELS = {
    'device_name': 'Device name', 'wifi_ip': 'Wi-Fi address',
    'mqtt': 'MQTT status', 'config': 'Configuration',
    'loglevel': 'Log level', 'uptime_s': 'Uptime (s)',
    'discovery_count': 'HA discovery count',
    'update_status': 'Update status', 'update_version': 'Staged version',
    'running_version': 'Application version',
    'base_version': 'MicroPython version', 'platform': 'Platform',
    'runtime_version': 'MicroPython version',
    'firmware_update_availability': 'OTA firmware availability',
    'heap_free_bytes': 'Free heap (bytes)',
    'heap_allocated_bytes': 'Allocated heap (bytes)',
    'storage_free_bytes': 'Free storage (bytes)',
    'storage_total_bytes': 'Total storage (bytes)',
    'active_slot': 'Active app slot', 'previous_slot': 'Previous app slot',
    'recovery_api': 'Recovery API', 'signed_updates': 'Signed updates',
    'release_channel': 'Release channel',
    'release_available_version': 'Available release',
    'release_check_status': 'Last automatic check',
    'module_last_ok': 'Last operation OK',
    'module_last_error': 'Last error',
    'module_last_read_ms': 'Read duration (ms)',
    'module_last_publish_age_s': 'HA publish age (s)',
    'module_consecutive_errors': 'Consecutive errors',
    'rs485_last_ok': 'RS485 last request OK',
    'rs485_last_operation': 'RS485 last operation',
    'rs485_last_address': 'RS485 last address',
    'rs485_last_error': 'RS485 last error',
    'rs485_last_latency_ms': 'RS485 latency (ms)',
    'ems_last_ok': 'EMS last frame OK',
    'ems_last_type': 'EMS last frame type',
    'ems_last_src': 'EMS last source', 'ems_last_error': 'EMS last error',
    'ems_frames': 'Valid EMS frames', 'ems_crc_errors': 'EMS CRC errors',
    'ems_breaks': 'Detected EMS breaks',
    'ems_rx_overflows': 'EMS receive overflows',
    'ems_bus_protocol': 'Detected EMS bus protocol',
    'adc_rms': 'ADC RMS', 'adc_midpoint': 'ADC midpoint',
    'adc_min': 'ADC minimum', 'adc_max': 'ADC maximum',
    'ac_voltage_error': 'AC voltage error', 'rtd_raw': 'RTD raw value',
    'fault_code': 'Fault code',
}

DIAGNOSTIC_HELP = {
    'module_last_ok': 'Whether the most recent operation completed successfully.',
    'module_last_error': 'Last operation error. Empty means no current error is recorded.',
    'module_last_read_ms': 'How long the most recent read took, in milliseconds. Some event-driven modules do not use this value.',
    'module_last_publish_age_s': 'Seconds since state was last published to Home Assistant over MQTT.',
    'module_consecutive_errors': 'Number of failed operations since the last successful operation.',
    'rs485_last_ok': 'Whether the most recent RS485 request completed successfully.',
    'rs485_last_operation': 'Operation type for the most recent RS485 request.',
    'rs485_last_address': 'Register address used by the most recent RS485 request.',
    'rs485_last_error': 'Last RS485 request error. Empty means no current error is recorded.',
    'rs485_last_latency_ms': 'How long the most recent RS485 request took, in milliseconds.',
}


def friendly_label(key):
    key = str(key)
    if key in FRIENDLY_LABELS:
        return FRIENDLY_LABELS[key]
    if key.startswith('module_'):
        key = key[len('module_'):]
    return key.replace('_', ' ').replace('.', ' ')


def render_label(key):
    return html_escape(friendly_label(key))


def render_badge(label, tone='neutral'):
    return (
        '<span class="badge ' + html_escape(tone) + '">' +
        html_escape(label) + '</span>'
    )


def diagnostic_help(key):
    return DIAGNOSTIC_HELP.get(
        key, 'Diagnostic value for module troubleshooting.'
    )
