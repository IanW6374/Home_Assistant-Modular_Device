"""Pure activation-health policy for application and firmware trials."""


def evaluate(capabilities, free_heap, minimum_free_heap=0,
             required_services=None, service_states=None,
             watchdog_required=False, watchdog_ready=False):
    """Return hard activation failures separately from degraded conditions.

    Only local facilities needed to repair the device are hard gates. External
    dependencies such as MQTT, NTP, Home Assistant and remote syslog belong in
    ``service_states`` but should not be listed in ``required_services``.
    """
    capabilities = capabilities or {}
    features = capabilities.get('features', {}) or {}
    required_services = tuple(required_services or ())
    service_states = dict(service_states or {})
    failures = []
    degraded = []

    if minimum_free_heap and (
        free_heap is None or int(free_heap) < int(minimum_free_heap)
    ):
        failures.append(
            'free heap ' + str(free_heap if free_heap is not None else 'unknown') +
            ' is below activation minimum ' + str(int(minimum_free_heap))
        )

    if capabilities.get('platform') == 'esp32-s3' and not features.get('psram'):
        failures.append('required PSRAM capability is unavailable')

    healthy_values = ('ready', 'online', 'listening', 'disabled')
    for name in required_services:
        state = str(service_states.get(name, 'unknown'))
        if state not in healthy_values:
            failures.append(str(name) + ' service is ' + state)

    if watchdog_required and not watchdog_ready:
        failures.append('configured watchdog is unavailable')

    for name, state in service_states.items():
        if name in required_services:
            continue
        state = str(state)
        if state not in healthy_values and state not in ('not-configured', 'stopped'):
            degraded.append(str(name) + ' service is ' + state)

    return {
        'healthy': not failures,
        'failures': failures,
        'degraded': degraded,
        'free_heap': free_heap,
        'minimum_free_heap': int(minimum_free_heap or 0),
    }

