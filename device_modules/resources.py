"""Preflight hardware-resource allocation for configured device modules."""


class ResourceConflict(ValueError):
    pass


class ResourceManager:
    """Reserve exclusive resources and consistently configured shared buses."""

    def __init__(self):
        self._resources = {}

    def reserve(self, kind, identifier, owner, shared=False, signature=None):
        key = str(kind) + ':' + str(identifier)
        owner = str(owner)
        current = self._resources.get(key)
        if current is None:
            self._resources[key] = {
                'kind': str(kind), 'id': str(identifier),
                'owners': [owner], 'shared': bool(shared),
                'signature': signature,
            }
            return key
        if not current['shared'] or not shared:
            raise ResourceConflict(
                key + ' is owned by ' + ', '.join(current['owners']) +
                '; requested by ' + owner
            )
        if current.get('signature') != signature:
            raise ResourceConflict(
                key + ' has incompatible shared-bus configuration for ' + owner
            )
        if owner not in current['owners']:
            current['owners'].append(owner)
        return key

    def reserve_device(self, device):
        if not isinstance(device, dict):
            raise ValueError('device resource declaration must be an object')
        owner = str(device.get('uuid') or device.get('name') or 'unknown')
        declarations = resources_for_device(device)
        for declaration in declarations:
            self.reserve(
                declaration['kind'], declaration['id'], owner,
                declaration.get('shared', False), declaration.get('signature')
            )
        return declarations

    def snapshot(self):
        return [
            {
                'kind': value['kind'], 'id': value['id'],
                'owners': list(value['owners']), 'shared': value['shared']
            }
            for _, value in sorted(self._resources.items())
        ]


def _gpio(declarations, value, role, shared=False):
    if isinstance(value, int) and not isinstance(value, bool):
        declarations.append({
            'kind': 'gpio', 'id': value, 'shared': bool(shared),
            'signature': role if shared else None,
        })


def resources_for_device(device):
    """Return deterministic resources from the v2 module configuration model."""
    declarations = []

    for section_name in ('rs485', 'ems'):
        section = device.get(section_name)
        if not isinstance(section, dict):
            continue
        uart = section.get('uart')
        if uart is not None:
            declarations.append({'kind': 'uart', 'id': uart})
        for field in ('tx', 'rx', 'de'):
            _gpio(declarations, section.get(field), section_name + '.' + field)

    spi = device.get('max31865')
    if isinstance(spi, dict):
        bus = spi.get('spi', 0)
        signature = tuple(spi.get(name) for name in (
            'sck', 'mosi', 'miso', 'baudrate', 'polarity', 'phase', 'bits',
            'firstbit'
        ))
        declarations.append({
            'kind': 'spi', 'id': bus, 'shared': True,
            'signature': signature,
        })
        for field in ('sck', 'mosi', 'miso'):
            _gpio(declarations, spi.get(field), 'spi.' + str(bus), shared=True)
        _gpio(declarations, spi.get('cs'), 'max31865.cs')

    voltage = device.get('ac_voltage')
    if isinstance(voltage, dict):
        pin = voltage.get('adc_pin')
        if pin is not None:
            declarations.append({'kind': 'adc', 'id': pin})
            _gpio(declarations, pin, 'ac_voltage.adc')

    gpio = device.get('gpio')
    if isinstance(gpio, dict):
        for direction in ('input', 'output'):
            mapping = gpio.get(direction)
            if isinstance(mapping, dict):
                for pin in mapping.values():
                    _gpio(declarations, pin, 'gpio.' + direction)

    return declarations


def validate_resources(devices):
    manager = ResourceManager()
    errors = []
    for device in devices or ():
        try:
            manager.reserve_device(device)
        except (ValueError, ResourceConflict) as exc:
            errors.append(str(exc))
    return errors, manager
