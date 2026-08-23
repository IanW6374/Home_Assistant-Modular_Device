"""Transport-neutral view models consumed by the embedded portal renderer."""


OVERVIEW_FIELDS = (
    ('device_name', 'Device'),
    ('wifi_ip', 'Wi-Fi address'),
    ('mqtt', 'MQTT'),
    ('api', 'Device API'),
    ('uptime_s', 'Uptime (s)'),
    ('running_version', 'Application version'),
    ('firmware_running_version', 'Core version'),
    ('base_version', 'MicroPython version'),
)


def overview_metrics(status):
    status = status or {}
    return [
        {'key': key, 'label': label, 'value': status.get(key, 'unknown')}
        for key, label in OVERVIEW_FIELDS
    ]


def update_check_summary(status):
    """Normalise scheduler state before HTML rendering or API serialisation."""
    status = status or {}
    check = str(status.get(
        'release_automatic_check_status',
        status.get('release_check_status', 'Not checked')
    ) or 'Not checked')
    checked = str(status.get(
        'release_automatic_last_checked',
        status.get('release_last_checked', '')
    ) or '')
    return {
        'status': check,
        'checked': checked,
        'text': check + (' — ' + checked if checked else ''),
        'tone': (
            'warn' if check.lower().startswith('check failed') else
            ('good' if check not in ('Not checked', 'Checking') else '')
        ),
    }
