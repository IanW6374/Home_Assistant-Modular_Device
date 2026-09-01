"""Transport-neutral view models consumed by the embedded portal renderer."""


OVERVIEW_FIELDS = (
    ('device_name', 'Device'),
    ('device_state', 'Device state'),
    ('network_transport', 'Network transport'),
    ('wifi_ip', 'Wi-Fi address'),
    ('mqtt', 'MQTT'),
    ('api', 'Device API'),
    ('syslog', 'Remote syslog'),
    ('hardware_resources', 'Hardware resources'),
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


def enrich_runtime_status(status, runtime_inventory, boot_snapshot,
                          capabilities):
    """Attach lifecycle and platform diagnostics without transport coupling."""
    status = dict(status or {})
    lifecycle = (runtime_inventory or {}).get('lifecycle', {})
    boot_snapshot = boot_snapshot or {}
    status.update({
        'device_state': lifecycle.get(
            'device_state', boot_snapshot.get('device_state', 'booting')
        ),
        'device_state_reason': lifecycle.get(
            'device_state_reason', boot_snapshot.get('reason', '')
        ),
        'boot_stage': boot_snapshot.get('stage', 'unknown'),
        'boot_health': boot_snapshot,
        'platform_capabilities': capabilities or {},
    })
    return status


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


def module_summaries(output_devices, device_objects, failed_modules):
    """Build transport-neutral state and diagnostic summaries for modules."""
    summaries = []
    for device_char in output_devices:
        if device_char.get('uuid') == '0000':
            continue
        device = next(
            (item for item in device_objects
             if item.get('uuid') == device_char.get('uuid')),
            None
        )
        if not device:
            continue
        driver = device_char.get('driver')
        state = {}
        diagnostics = {}
        calibratable = False
        if driver:
            try:
                raw_state = driver.get_state_payload()
            except Exception as exc:
                raw_state = {'error': str(exc)}
            diagnostic_keys = set()
            for entity_id in device.get('entities', {}):
                entity = device['entities'][str(entity_id)]
                key = entity.get('key', entity.get('class', str(entity_id)))
                if entity.get('entity_category') == 'diagnostic':
                    diagnostic_keys.add(key)
            for key in raw_state:
                target = diagnostics if key in diagnostic_keys else state
                target[key] = raw_state[key]
            if hasattr(driver, 'diagnostics_payload'):
                try:
                    health = driver.diagnostics_payload()
                except Exception:
                    health = {}
                for key in health:
                    diagnostics['module_' + key] = health[key]
            calibratable = (
                hasattr(driver, 'set_calibration') and
                device.get('type', {}).get('subclass') == 'Grove-AC-Voltage'
            )
        debug_frames = None
        if driver and hasattr(driver, 'debug_frames_enabled'):
            try:
                debug_frames = bool(driver.debug_frames_enabled())
            except Exception:
                debug_frames = None
        summaries.append({
            'uuid': device.get('uuid', ''),
            'name': device.get('name', ''),
            'type': device.get('type', {}).get(
                'subclass', device.get('type', {}).get('class', '')
            ),
            'state': state,
            'diagnostics': diagnostics,
            'calibratable': calibratable,
            'debug_frames': debug_frames,
        })
    for failed in failed_modules:
        device = next(
            (item for item in device_objects
             if item.get('uuid') == failed.get('uuid')),
            None
        )
        if not device:
            continue
        summaries.append({
            'uuid': device.get('uuid', ''),
            'name': device.get('name', ''),
            'type': device.get('type', {}).get(
                'subclass', device.get('type', {}).get('class', '')
            ),
            'state': {},
            'diagnostics': {
                'module_last_ok': False,
                'module_last_error': (
                    'Setup failed: ' +
                    str(failed.get('setup_error', 'unknown error'))
                ),
            },
            'calibratable': False,
            'debug_frames': None,
        })
    return summaries
