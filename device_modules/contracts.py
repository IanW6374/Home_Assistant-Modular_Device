"""Stable IoT-MD v2 driver metadata and conformance checks."""

from .driver_index import DRIVER_VERSIONS


DRIVER_API_VERSION = 2
ALLOWED_CAPABILITIES = (
    'state', 'commands', 'calibration', 'diagnostics', 'discovery', 'local-input'
)

LIFECYCLE_METHODS = (
    'get_state_payload', 'diagnostics_payload'
)


def _type_keys(module):
    result = []
    for attribute in ('DEVICE_TYPE', 'SWITCH_DEVICE_TYPE'):
        device_type = getattr(module, attribute, None)
        if not isinstance(device_type, dict):
            continue
        device_class = str(device_type.get('class', ''))
        subclasses = device_type.get('subclass', {})
        names = subclasses.keys() if isinstance(subclasses, dict) else subclasses
        for name in names:
            result.append(device_class + ':' + str(name))
    return sorted(result)


def metadata_for(module_name, module):
    declared = getattr(module, 'DRIVER_METADATA', None)
    if declared is not None:
        metadata = dict(declared)
    else:
        capabilities = ['state', 'diagnostics', 'discovery']
        driver_class = getattr(module, 'Driver', None)
        if driver_class and (
            hasattr(driver_class, 'handle_set') or hasattr(driver_class, 'set')
        ):
            capabilities.append('commands')
        if driver_class and hasattr(driver_class, 'set_calibration'):
            capabilities.append('calibration')
        metadata = {
            'name': str(module_name),
            'api_version': DRIVER_API_VERSION,
            'version': int(getattr(
                module, 'MODULE_VERSION', DRIVER_VERSIONS.get(module_name, 0)
            )),
            'types': _type_keys(module),
            'capabilities': capabilities,
            'configuration_schema': getattr(module, 'CONFIGURATION_SCHEMA', {}),
        }
    return validate_metadata(metadata)


def validate_driver_instance(driver):
    """Validate the minimum transport-neutral lifecycle of a live driver."""
    missing = [
        name for name in LIFECYCLE_METHODS
        if not callable(getattr(driver, name, None))
    ]
    if missing:
        raise ValueError('driver lifecycle methods are missing: ' + ', '.join(missing))
    if not (
        callable(getattr(driver, 'set', None)) or
        callable(getattr(driver, 'handle_set', None))
    ):
        raise ValueError('driver command lifecycle method is missing')
    return driver


def validate_metadata(metadata):
    if not isinstance(metadata, dict):
        raise ValueError('driver metadata must be an object')
    allowed = {
        'name', 'api_version', 'version', 'types', 'capabilities',
        'configuration_schema'
    }
    unknown = set(metadata) - allowed
    if unknown:
        raise ValueError('unknown driver metadata field: ' + sorted(unknown)[0])
    name = str(metadata.get('name', ''))
    if (
        not name or len(name) > 64 or
        any(character not in 'abcdefghijklmnopqrstuvwxyz0123456789_'
            for character in name)
    ):
        raise ValueError('driver name is invalid')
    if metadata.get('api_version') != DRIVER_API_VERSION:
        raise ValueError('driver API version is not supported')
    version = metadata.get('version')
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise ValueError('driver version must be a positive integer')
    types = metadata.get('types')
    if (
        not isinstance(types, list) or not types or
        any(not isinstance(value, str) or ':' not in value for value in types)
    ):
        raise ValueError('driver types are invalid')
    capabilities = metadata.get('capabilities')
    if (
        not isinstance(capabilities, list) or
        any(value not in ALLOWED_CAPABILITIES for value in capabilities)
    ):
        raise ValueError('driver capabilities are invalid')
    schema = metadata.get('configuration_schema')
    if not isinstance(schema, dict):
        raise ValueError('driver configuration schema must be an object')
    return {
        'name': name,
        'api_version': DRIVER_API_VERSION,
        'version': version,
        'types': list(types),
        'capabilities': sorted(set(capabilities)),
        'configuration_schema': schema,
    }
