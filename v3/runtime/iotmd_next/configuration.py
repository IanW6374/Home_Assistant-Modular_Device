"""Versioned, bounded configuration contract for the v3 application kernel."""

CONTRACT_VERSION = 3
MAX_MODULES = 8
MAX_SETTINGS = 12
MAX_TRANSPORTS = 8
MAX_DEPENDENCIES = 4
MAX_RESOURCES = 8
IDENTITY_METHODS = (
    'self-signed', 'automatic-iot-ca', 'iot-ca-authorization',
    'private-ca-acme', 'manual-package',
)


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


def _boolean(value, name):
    if value is not True and value is not False:
        raise ConfigurationError(name + ' must be boolean')
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


def _validate_common(value):
    device = _exact(value['device'], 'device', ('name',))
    _name(device['name'], 'device name', 32)
    services = _exact(
        value['services'], 'services', ('poll_interval_ms', 'max_failures')
    )
    _integer(services['poll_interval_ms'], 'poll interval', 100, 60000)
    _integer(services['max_failures'], 'maximum failures', 1, 10)


def _validate_settings(settings, label):
    if not isinstance(settings, dict) or len(settings) > MAX_SETTINGS:
        raise ConfigurationError(label + ' settings are invalid')
    for key in settings:
        _name(key, label + ' setting name', 32)
        _setting(settings[key], label + ' setting ' + key)


def _resource(value, label):
    resource = _exact(value, label, ('kind', 'identifier'))
    _name(resource['kind'], label + ' kind', 12)
    _name(resource['identifier'], label + ' identifier', 32)
    return resource


def _validate_v1_modules(modules, identifiers=None):
    if not isinstance(modules, list) or len(modules) > MAX_MODULES:
        raise ConfigurationError('modules are invalid')
    identifiers = identifiers if identifiers is not None else set()
    for index, module in enumerate(modules):
        label = 'module ' + str(index)
        _exact(module, label, ('id', 'driver', 'enabled', 'resource', 'settings'))
        identifier = _name(module['id'], label + ' id', 32)
        if identifier in identifiers:
            raise ConfigurationError('service id is duplicated')
        identifiers.add(identifier)
        _name(module['driver'], label + ' driver', 32)
        _boolean(module['enabled'], label + ' enabled')
        _resource(module['resource'], label + ' resource')
        _validate_settings(module['settings'], label)
    return identifiers


def _validate_v1(value):
    _exact(value, 'configuration', ('contract_version', 'device', 'services',
                                    'modules'))
    if value['contract_version'] != 1:
        raise ConfigurationError('configuration version is unsupported')
    _validate_common(value)
    _validate_v1_modules(value['modules'])
    return value


def _validate_dependencies(dependencies, label, identifier, known):
    if (not isinstance(dependencies, list) or
            len(dependencies) > MAX_DEPENDENCIES):
        raise ConfigurationError(label + ' dependencies are invalid')
    for dependency in dependencies:
        _name(dependency, label + ' dependency', 32)
        if dependency == identifier or dependency not in known:
            raise ConfigurationError(label + ' dependency is invalid')


def _validate_transports(transports, known, identifiers):
    if not isinstance(transports, list) or len(transports) > MAX_TRANSPORTS:
        raise ConfigurationError('transports are invalid')
    for index, transport in enumerate(transports):
        label = 'transport ' + str(index)
        _exact(transport, label, ('id', 'adapter', 'enabled', 'critical',
                                  'dependencies', 'settings'))
        identifier = _name(transport['id'], label + ' id', 32)
        if identifier in identifiers:
            raise ConfigurationError('service id is duplicated')
        identifiers.add(identifier)
        _name(transport['adapter'], label + ' adapter', 32)
        _boolean(transport['enabled'], label + ' enabled')
        _boolean(transport['critical'], label + ' critical')
        _validate_dependencies(
            transport['dependencies'], label, identifier, known
        )
        _validate_settings(transport['settings'], label)


def _validate_v2(value):
    _exact(value, 'configuration', ('contract_version', 'device', 'services',
                                    'transports', 'modules'))
    if value['contract_version'] != 2:
        raise ConfigurationError('configuration version is unsupported')
    _validate_common(value)
    transports = value['transports']
    known = set()
    for index, transport in enumerate(transports):
        if not isinstance(transport, dict):
            raise ConfigurationError('transport ' + str(index) + ' has invalid fields')
        identifier = _name(transport.get('id'), 'transport id', 32)
        if identifier in known:
            raise ConfigurationError('service id is duplicated')
        known.add(identifier)
    identifiers = set()
    _validate_transports(transports, known, identifiers)
    _validate_v1_modules(value['modules'], identifiers)
    return value


def validate_configuration(value):
    _exact(value, 'configuration', (
        'contract_version', 'device', 'services', 'transports', 'identity',
        'fleet', 'modules',
    ))
    if value['contract_version'] != CONTRACT_VERSION:
        raise ConfigurationError('configuration version is unsupported')
    _validate_common(value)

    identity = _exact(value['identity'], 'identity', (
        'enabled', 'method', 'critical', 'dependencies', 'renewal_check_s',
    ))
    _boolean(identity['enabled'], 'identity enabled')
    if identity['method'] not in IDENTITY_METHODS:
        raise ConfigurationError('identity method is invalid')
    _boolean(identity['critical'], 'identity critical')
    _integer(identity['renewal_check_s'], 'identity renewal check', 60, 86400)

    fleet = _exact(value['fleet'], 'fleet', (
        'enabled', 'critical', 'dependencies', 'cohort', 'poll_interval_s',
    ))
    _boolean(fleet['enabled'], 'fleet enabled')
    _boolean(fleet['critical'], 'fleet critical')
    _name(fleet['cohort'], 'fleet cohort', 32)
    _integer(fleet['poll_interval_s'], 'fleet poll interval', 10, 86400)

    transports = value['transports']
    if not isinstance(transports, list) or len(transports) > MAX_TRANSPORTS:
        raise ConfigurationError('transports are invalid')
    known = set()
    for index, transport in enumerate(transports):
        if not isinstance(transport, dict):
            raise ConfigurationError('transport ' + str(index) + ' has invalid fields')
        identifier = _name(transport.get('id'), 'transport id', 32)
        if identifier in known:
            raise ConfigurationError('service id is duplicated')
        known.add(identifier)
    if identity['enabled']:
        if 'identity' in known:
            raise ConfigurationError('service id is duplicated')
        known.add('identity')
    if fleet['enabled']:
        if 'fleet' in known:
            raise ConfigurationError('service id is duplicated')
        known.add('fleet')

    identifiers = set()
    _validate_transports(transports, known, identifiers)
    if identity['enabled']:
        identifiers.add('identity')
        _validate_dependencies(
            identity['dependencies'], 'identity', 'identity', known
        )
    if fleet['enabled']:
        identifiers.add('fleet')
        _validate_dependencies(fleet['dependencies'], 'fleet', 'fleet', known)

    modules = value['modules']
    if not isinstance(modules, list) or len(modules) > MAX_MODULES:
        raise ConfigurationError('modules are invalid')
    for index, module in enumerate(modules):
        label = 'module ' + str(index)
        _exact(module, label, ('id', 'driver', 'enabled', 'resources', 'settings'))
        identifier = _name(module['id'], label + ' id', 32)
        if identifier in identifiers:
            raise ConfigurationError('service id is duplicated')
        identifiers.add(identifier)
        _name(module['driver'], label + ' driver', 32)
        _boolean(module['enabled'], label + ' enabled')
        resources = module['resources']
        if (not isinstance(resources, list) or not resources or
                len(resources) > MAX_RESOURCES):
            raise ConfigurationError(label + ' resources are invalid')
        seen = set()
        for resource_index, resource in enumerate(resources):
            _resource(resource, label + ' resource ' + str(resource_index))
            key = (resource['kind'], resource['identifier'])
            if key in seen:
                raise ConfigurationError(label + ' resource is duplicated')
            seen.add(key)
        _validate_settings(module['settings'], label)
    return value


def _copy_v1_module(item):
    return {
        'id': item['id'], 'driver': item['driver'],
        'enabled': item['enabled'], 'resource': dict(item['resource']),
        'settings': dict(item['settings']),
    }


def _copy_transport(item):
    return {
        'id': item['id'], 'adapter': item['adapter'],
        'enabled': item['enabled'], 'critical': item['critical'],
        'dependencies': list(item['dependencies']),
        'settings': dict(item['settings']),
    }


def _copy_v3(value):
    return {
        'contract_version': CONTRACT_VERSION,
        'device': dict(value['device']),
        'services': dict(value['services']),
        'transports': [_copy_transport(item) for item in value['transports']],
        'identity': {
            'enabled': value['identity']['enabled'],
            'method': value['identity']['method'],
            'critical': value['identity']['critical'],
            'dependencies': list(value['identity']['dependencies']),
            'renewal_check_s': value['identity']['renewal_check_s'],
        },
        'fleet': {
            'enabled': value['fleet']['enabled'],
            'critical': value['fleet']['critical'],
            'dependencies': list(value['fleet']['dependencies']),
            'cohort': value['fleet']['cohort'],
            'poll_interval_s': value['fleet']['poll_interval_s'],
        },
        'modules': [{
            'id': item['id'], 'driver': item['driver'],
            'enabled': item['enabled'],
            'resources': [dict(resource) for resource in item['resources']],
            'settings': dict(item['settings']),
        } for item in value['modules']],
    }


def _v1_from_v0(value):
    _exact(value, 'legacy configuration', ('version', 'device_name', 'modules'))
    previous = {
        'contract_version': 1,
        'device': {'name': value['device_name']},
        'services': {'poll_interval_ms': 1000, 'max_failures': 3},
        'modules': [],
    }
    for item in value['modules']:
        _exact(item, 'legacy module', ('name', 'driver', 'resource', 'settings'))
        resource = _resource(item['resource'], 'legacy module resource')
        previous['modules'].append({
            'id': item['name'], 'driver': item['driver'], 'enabled': True,
            'resource': dict(resource), 'settings': dict(item['settings']),
        })
    return _validate_v1(previous)


def _v2_from_earlier(value, source_version):
    if source_version == 2:
        previous = _validate_v2(value)
        return {
            'contract_version': 2,
            'device': dict(previous['device']),
            'services': dict(previous['services']),
            'transports': [_copy_transport(item) for item in previous['transports']],
            'modules': [_copy_v1_module(item) for item in previous['modules']],
        }
    previous = _v1_from_v0(value) if source_version == 0 else _validate_v1(value)
    return {
        'contract_version': 2,
        'device': dict(previous['device']),
        'services': dict(previous['services']),
        'transports': [],
        'modules': [_copy_v1_module(item) for item in previous['modules']],
    }


def migrate_configuration(value):
    """Return a validated copy and migration description without mutation."""
    if not isinstance(value, dict):
        raise ConfigurationError('configuration must be a mapping')
    source_version = value.get('contract_version', value.get('version'))
    if source_version == CONTRACT_VERSION:
        migrated = _copy_v3(validate_configuration(value))
    elif source_version in (0, 1, 2):
        previous = _v2_from_earlier(value, source_version)
        migrated = {
            'contract_version': CONTRACT_VERSION,
            'device': dict(previous['device']),
            'services': dict(previous['services']),
            'transports': [_copy_transport(item) for item in previous['transports']],
            'identity': {
                'enabled': False, 'method': 'self-signed', 'critical': True,
                'dependencies': [], 'renewal_check_s': 3600,
            },
            'fleet': {
                'enabled': False, 'critical': False, 'dependencies': [],
                'cohort': 'default', 'poll_interval_s': 300,
            },
            'modules': [{
                'id': item['id'], 'driver': item['driver'],
                'enabled': item['enabled'],
                'resources': [dict(item['resource'])],
                'settings': dict(item['settings']),
            } for item in previous['modules']],
        }
        validate_configuration(migrated)
    else:
        raise ConfigurationError('configuration version is unsupported')
    return {
        'from_version': source_version,
        'to_version': CONTRACT_VERSION,
        'changed': source_version != CONTRACT_VERSION,
        'configuration': migrated,
    }
