import uos

EXCLUDE_FILES = {"__init__.py", "loader.py", "base.py", "sensor.py", "template.py"}

# Registry for device types
_DEVICE_TYPES = {}


def _discover_modules():
    modules = []
    try:
        files = uos.listdir("device_modules")
    except OSError:
        return modules

    try:
        package = __package__
    except NameError:
        package = None

    if not package:
        package = __name__.rsplit('.', 1)[0] if '.' in __name__ else 'device_modules'

    for filename in files:
        if not filename.endswith(".py") or filename in EXCLUDE_FILES:
            continue

        module_name = filename[:-3]
        try:
            module = __import__(package + "." + module_name, None, None, [module_name])
        except Exception as exc:
            try:
                module = __import__(module_name)
            except Exception:
                print('device_modules.loader: failed to import', module_name, exc)
                continue

        if hasattr(module, 'supports') and callable(module.supports):
            modules.append(module)
            # Register device type(s) if module provides them
            if hasattr(module, 'DEVICE_TYPE'):
                _DEVICE_TYPES[module_name] = module.DEVICE_TYPE
            # Also check for additional device types (e.g., switch handled by sensor module)
            if hasattr(module, 'SWITCH_DEVICE_TYPE'):
                _DEVICE_TYPES[module_name + '_switch'] = module.SWITCH_DEVICE_TYPE
        else:
            print('device_modules.loader: module does not expose supports()', module_name)

    return modules


_MODULES = _discover_modules()


def _find_module_for_device(device):
    for module in _MODULES:
        try:
            if module.supports(device):
                return module
        except Exception:
            continue
    return None


def get_device_types():
    """Return list of registered device types for Home Assistant."""
    return list(_DEVICE_TYPES.values())


def setup_device(device, index):
    module = _find_module_for_device(device)
    if not module:
        print('device_modules.loader: no module found for device', device.get('uuid'))
        return None

    device_char = module.setup(device, index)
    if hasattr(module, 'create_driver') and callable(module.create_driver):
        device_char['driver'] = module.create_driver(device, device_char)
    elif hasattr(module, 'Driver'):
        device_char['driver'] = module.Driver(device, device_char)

    return device_char
