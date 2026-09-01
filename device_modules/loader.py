try:
    from .logging import log_output
    from .driver_index import DRIVER_MODULES
    from .contracts import metadata_for, validate_driver_instance
    from .resources import validate_resources
except ImportError:
    from logging import log_output
    from driver_index import DRIVER_MODULES
    from contracts import metadata_for, validate_driver_instance
    from resources import validate_resources


_DEVICE_TYPES = {}
_MODULES = []
_DRIVER_METADATA = {}
_RESOURCE_MANAGER = None


def _import_driver(module_name):
    try:
        package = __package__
    except NameError:
        package = None
    if not package:
        package = __name__.rsplit('.', 1)[0] if '.' in __name__ else 'device_modules'
    return __import__(package + '.' + module_name, None, None, [module_name])


def _load_for_devices(devices):
    required = []
    for device in devices or ():
        device_type = device.get('type', {}) if isinstance(device, dict) else {}
        key = str(device_type.get('class', '')) + ':' + str(device_type.get('subclass', ''))
        module_name = DRIVER_MODULES.get(key)
        if not module_name:
            raise ValueError('no packaged driver for configured type ' + key)
        if module_name not in required:
            required.append(module_name)

    modules = []
    types = {}
    metadata = {}
    for module_name in required:
        try:
            module = _import_driver(module_name)
        except Exception as exc:
            raise RuntimeError(
                'could not load configured device driver "' + module_name + '" - ' + str(exc)
            )
        if not hasattr(module, 'supports') or not callable(module.supports):
            raise RuntimeError('configured module "' + module_name + '" is not a device driver')
        metadata[module_name] = metadata_for(module_name, module)
        modules.append(module)
        if hasattr(module, 'DEVICE_TYPE'):
            types[module_name] = module.DEVICE_TYPE
        if hasattr(module, 'SWITCH_DEVICE_TYPE'):
            types[module_name + '_switch'] = module.SWITCH_DEVICE_TYPE
    return modules, types, metadata


def device_types_for_devices(devices):
    """Validate/import drivers without changing the active runtime driver set."""
    _modules, types, _metadata = _load_for_devices(devices)
    return list(types.values())


def configured_driver_names(devices):
    names = []
    for device in devices or ():
        device_type = device.get('type', {}) if isinstance(device, dict) else {}
        key = str(device_type.get('class', '')) + ':' + str(device_type.get('subclass', ''))
        name = DRIVER_MODULES.get(key)
        if not name:
            raise ValueError('no packaged driver for configured type ' + key)
        if name not in names:
            names.append(name)
    return names


def configure_for_devices(devices):
    """Import only drivers referenced by the installed module configuration."""
    global _MODULES, _DEVICE_TYPES, _DRIVER_METADATA, _RESOURCE_MANAGER
    errors, manager = validate_resources(devices)
    if errors:
        raise ValueError('hardware resource conflict: ' + '; '.join(errors))
    _MODULES, _DEVICE_TYPES, _DRIVER_METADATA = _load_for_devices(devices)
    _RESOURCE_MANAGER = manager
    return list(_DEVICE_TYPES.values())


def resource_catalog():
    """Return the preflight allocation used by the active driver set."""
    return _RESOURCE_MANAGER.snapshot() if _RESOURCE_MANAGER else []


def resource_manager():
    """Return the central allocator for resource-aware driver factories."""
    return _RESOURCE_MANAGER


def _find_module_for_device(device):
    for module in _MODULES:
        try:
            if module.supports(device):
                return module
        except Exception as exc:
            log_output(
                'Local',
                'Device loader',
                {
                    'log': 'Could not check device support in "' +
                           str(getattr(module, '__name__', 'unknown')) + '" for ' +
                           str(device.get('uuid')) + ' ' +
                           str(device.get('name')) + ' ' + str(exc)
                },
                'ERROR'
            )
    return None


def get_device_types():
    """Return device types for the configured and imported drivers."""
    return list(_DEVICE_TYPES.values())


def driver_catalog():
    """Return bounded v2 metadata for only the currently loaded drivers."""
    return [dict(_DRIVER_METADATA[name]) for name in sorted(_DRIVER_METADATA)]


def setup_device(device, index):
    module = _find_module_for_device(device)
    if not module:
        message = (
            'No driver found for configured device ' +
            str(device.get('uuid')) + ' ' + str(device.get('name')) + ' ' +
            str(device.get('type'))
        )
        log_output(
            'Local', 'Device loader',
            {'log': message},
            'ERROR'
        )
        return {
            'uuid': device.get('uuid', ''),
            'index': index,
            'setup_error': message,
        }
    try:
        resources = _RESOURCE_MANAGER.scope(device.get('uuid', ''))
        if (
            hasattr(module, 'setup_with_resources') and
            callable(module.setup_with_resources)
        ):
            device_char = module.setup_with_resources(device, index, resources)
        else:
            device_char = module.setup(device, index)
        if (
            hasattr(module, 'create_driver_with_resources') and
            callable(module.create_driver_with_resources)
        ):
            device_char['driver'] = module.create_driver_with_resources(
                device, device_char, resources
            )
        elif hasattr(module, 'create_driver') and callable(module.create_driver):
            device_char['driver'] = module.create_driver(device, device_char)
        elif hasattr(module, 'Driver'):
            device_char['driver'] = module.Driver(device, device_char)
        if device_char.get('driver') is not None:
            validate_driver_instance(device_char['driver'])
    except Exception as exc:
        message = str(exc)
        log_output(
            'Local', 'Device loader',
            {'log': 'Could not set up device driver "' +
             str(getattr(module, '__name__', 'unknown')) + '" for ' +
             str(device.get('uuid')) + ' ' + str(device.get('name')) + ' ' + message},
            'ERROR'
        )
        return {
            'uuid': device.get('uuid', ''),
            'index': index,
            'setup_error': message,
        }
    return device_char
