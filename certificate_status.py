"""Certificate inventory and lifecycle alerts for the device application."""


def installed_details(manager, paths, api_ca_store, client_registry, config,
                      migration_pending=False):
    api_server = manager.certificate_lifecycle(paths['api_server'])
    api_server['migration_pending'] = bool(migration_pending)
    return {
        'portal': manager.certificate_lifecycle(paths['portal']),
        'api_server': api_server,
        'trusted_ca': manager.certificate_lifecycle(paths['mqtt_ca']),
        'mqtt_ca': manager.certificate_lifecycle(paths['mqtt_ca']),
        'release_ca': manager.certificate_lifecycle(paths['release_ca']),
        'api_client_ca': {'installed': False},
        'api_client_cas': api_ca_store.list(),
        'api_clients': client_registry.list_clients(),
        'syslog_ca': manager.certificate_lifecycle(paths['syslog_ca']),
        'acme_settings': dict(config),
    }


def _alert(name, details, previous, log_output, health):
    level = details.get('expiry_level')
    if level not in ('warning', 'critical', 'expired') or previous.get(name) == level:
        previous[name] = level
        return
    days = details.get('days_remaining')
    message = name + ' certificate '
    message += 'expired' if level == 'expired' else 'expires in ' + str(days) + ' days'
    log_output('Local', 'Certificate lifecycle', {'log': message}, 'ERROR')
    health.record_event(
        'certificate_' + level, message,
        {'certificate': name, 'days_remaining': days}, force=True
    )
    previous[name] = level


async def alert_monitor(manager, paths, api_ca_store, client_registry,
                        log_output, health, sleep):
    previous = {}
    while True:
        for name, path in paths.items():
            _alert(name, manager.certificate_lifecycle(path), previous, log_output, health)
        for ca in api_ca_store.list():
            fingerprint = str(ca.get('fingerprint', ''))
            _alert('api_ca_' + fingerprint, ca, previous, log_output, health)
        for client in client_registry.list_clients():
            fingerprint = str(client.get('fingerprint', ''))
            details = dict(client)
            details['label'] = str(client.get('label', fingerprint[:12]))
            _alert('api_client_' + fingerprint, details, previous, log_output, health)
        await sleep(21600)
