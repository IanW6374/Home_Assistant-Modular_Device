"""Versioned, bounded configuration contract for the v3 application kernel."""

CONTRACT_VERSION = 1
MAX_MODULES = 8
MAX_SETTINGS = 12


class ConfigurationError(ValueError):
    pass


def _exact(value, name, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ConfigurationError(name + ' has invalid fields')
    return value


def _name(value, name, maximum=32):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ConfigurationError(name + ' is invalid')
    for character in value:
        if not (
                character in 'abcdefghijklmnopqrstuvwxyz' or
                character in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' or
                character in '0123456789_.:-'):
            raise ConfigurationError(name + ' is invalid')
    return value


def _integer(value, name, minimum, maximum):
    if (not isinstance(value, int) or isinstance(value, bool) or
            value < minimum or value > maximum):
        raise ConfigurationError(name + ' is invalid')
    return value


def _setting(value, name):
    if value is None or value is True or value is False:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value or value < -1000000000000 or value > 1000000000000:
            raise ConfigurationError(name + ' is invalid')
        return value
    if isinstance(value, str) and len(value) <= 64:
        return value
    raise ConfigurationError(name + ' is invalid')


def validate_configuration(value):
    _exact(value, 'configuration', ('contract_version', 'device', 'services',
                                    'modules'))
    if value['contract_version'] != CONTRACT_VERSION:
        raise ConfigurationError('configuration version is unsupported')
    device = _exact(value['device'], 'device', ('name',))
    _name(device['name'], 'device name', 32)
    services = _exact(
        value['services'], 'services', ('poll_interval_ms', 'max_failures')
    )
    _integer(services['poll_interval_ms'], 'poll interval', 100, 60000)
    _integer(services['max_failures'], 'maximum failures', 1, 10)
    modules = value['modules']
    if not isinstance(modules, list) or len(modules) > MAX_MODULES:
        raise ConfigurationError('modules are invalid')
    identifiers = set()
    for index, module in enumerate(modules):
        label = 'module ' + str(index)
        _exact(module, label, ('id', 'driver', 'enabled', 'resource',
                               'settings'))
        identifier = _name(module['id'], label + ' id', 32)
        if identifier in identifiers:
            raise ConfigurationError('module id is duplicated')
        identifiers.add(identifier)
        _name(module['driver'], label + ' driver', 32)
        if module['enabled'] is not True and module['enabled'] is not False:
            raise ConfigurationError(label + ' enabled must be boolean')
        resource = _exact(
            module['resource'], label + ' resource', ('kind', 'identifier')
        )
        _name(resource['kind'], label + ' resource kind', 12)
        _name(resource['identifier'], label + ' resource identifier', 32)
        settings = module['settings']
        if not isinstance(settings, dict) or len(settings) > MAX_SETTINGS:
            raise ConfigurationError(label + ' settings are invalid')
        for key in settings:
            _name(key, label + ' setting name', 32)
            _setting(settings[key], label + ' setting ' + key)
    return value


def _copy_v1(value):
    return {
        'contract_version': value['contract_version'],
        'device': dict(value['device']),
        'services': dict(value['services']),
        'modules': [
            {
                'id': item['id'],
                'driver': item['driver'],
                'enabled': item['enabled'],
                'resource': dict(item['resource']),
                'settings': dict(item['settings']),
            }
            for item in value['modules']
        ],
    }


def migrate_configuration(value):
    """Return a validated copy and migration description without mutation."""
    if not isinstance(value, dict):
        raise ConfigurationError('configuration must be a mapping')
    source_version = value.get('contract_version', value.get('version'))
    if source_version == CONTRACT_VERSION:
        migrated = _copy_v1(validate_configuration(value))
    elif source_version == 0:
        _exact(value, 'legacy configuration', ('version', 'device_name',
                                               'modules'))
        migrated = {
            'contract_version': CONTRACT_VERSION,
            'device': {'name': value['device_name']},
            'services': {'poll_interval_ms': 1000, 'max_failures': 3},
            'modules': [],
        }
        for item in value['modules']:
            _exact(item, 'legacy module', ('name', 'driver', 'resource',
                                           'settings'))
            resource = _exact(
                item['resource'], 'legacy resource', ('kind', 'identifier')
            )
            migrated['modules'].append({
                'id': item['name'],
                'driver': item['driver'],
                'enabled': True,
                'resource': dict(resource),
                'settings': dict(item['settings']),
            })
        validate_configuration(migrated)
    else:
        raise ConfigurationError('configuration version is unsupported')
    return {
        'from_version': source_version,
        'to_version': CONTRACT_VERSION,
        'changed': source_version != CONTRACT_VERSION,
        'configuration': migrated,
    }
