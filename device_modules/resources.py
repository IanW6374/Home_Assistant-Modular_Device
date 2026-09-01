"""Preflight hardware-resource allocation for configured device modules."""


class ResourceConflict(ValueError):
    pass


class ResourceManager:
    """Reserve exclusive resources and consistently configured shared buses."""

    def __init__(self, providers=None):
        self._resources = {}
        self._logical = {}
        self._providers = dict(providers or {})
        self._instances = {}

    def reserve(self, kind, identifier, owner, shared=False, signature=None,
                logical_name=None):
        key = str(kind) + ':' + str(identifier)
        owner = str(owner)
        current = self._resources.get(key)
        if current is None:
            self._resources[key] = {
                'kind': str(kind), 'id': str(identifier),
                'owners': [owner], 'shared': bool(shared),
                'signature': signature,
                'logical_names': [],
            }
            current = self._resources[key]
        elif not current['shared'] or not shared:
            raise ResourceConflict(
                key + ' is owned by ' + ', '.join(current['owners']) +
                '; requested by ' + owner
            )
        elif current.get('signature') != signature:
            raise ResourceConflict(
                key + ' has incompatible shared-bus configuration for ' + owner
            )
        elif owner not in current['owners']:
            current['owners'].append(owner)
        if logical_name:
            logical_name = str(logical_name)
            existing = self._logical.get(logical_name)
            if existing is not None and existing != key:
                raise ResourceConflict(
                    'logical resource ' + logical_name + ' already maps to ' + existing
                )
            self._logical[logical_name] = key
            if logical_name not in current['logical_names']:
                current['logical_names'].append(logical_name)
        return key

    def reserve_device(self, device):
        if not isinstance(device, dict):
            raise ValueError('device resource declaration must be an object')
        owner = str(device.get('uuid') or device.get('name') or 'unknown')
        declarations = resources_for_device(device)
        for declaration in declarations:
            self.reserve(
                declaration['kind'], declaration['id'], owner,
                declaration.get('shared', False), declaration.get('signature'),
                owner + '.' + declaration.get(
                    'name', declaration['kind'] + '.' + str(declaration['id'])
                )
            )
        return declarations

    def register_provider(self, kind, provider):
        if not callable(provider):
            raise ValueError('resource provider must be callable')
        self._providers[str(kind)] = provider

    def scope(self, owner):
        return ResourceScope(self, owner)

    def acquire(self, logical_name, owner, factory=None):
        key = self._logical.get(str(logical_name), str(logical_name))
        resource = self._resources.get(key)
        if resource is None:
            raise KeyError('unknown hardware resource ' + str(logical_name))
        if str(owner) not in resource['owners']:
            raise PermissionError(
                str(owner) + ' does not own hardware resource ' + str(logical_name)
            )
        if key not in self._instances:
            provider = factory or self._providers.get(resource['kind'])
            if provider is None:
                raise RuntimeError(
                    'no provider registered for hardware resource ' + resource['kind']
                )
            self._instances[key] = provider(dict(resource))
        return self._instances[key]

    def bindings_for(self, owner):
        owner = str(owner)
        return {
            name: key for name, key in self._logical.items()
            if owner in self._resources[key]['owners']
        }

    def snapshot(self):
        return [
            {
                'kind': value['kind'], 'id': value['id'],
                'owners': list(value['owners']), 'shared': value['shared'],
                'logical_names': list(value.get('logical_names', ())),
            }
            for _, value in sorted(self._resources.items())
        ]


class ResourceScope:
    """Owner-bound injection interface passed to resource-aware drivers."""

    def __init__(self, manager, owner):
        self.manager = manager
        self.owner = str(owner)

    def acquire(self, logical_name, factory=None):
        return self.manager.acquire(logical_name, self.owner, factory)

    def bindings(self):
        return self.manager.bindings_for(self.owner)


def _gpio(declarations, value, role, shared=False):
    if isinstance(value, int) and not isinstance(value, bool):
        declarations.append({
            'kind': 'gpio', 'id': value, 'shared': bool(shared),
            'signature': role if shared else None,
            'name': role,
        })


def resources_for_device(device):
    """Return deterministic resources from the v2 module configuration model."""
    declarations = []

    for section_name in ('rs485', 'ems'):
        section = device.get(section_name)
        if not isinstance(section, dict):
            continue
        ports = section.get('ports')
        if isinstance(ports, dict):
            for port_name in sorted(ports):
                port = ports[port_name]
                if not isinstance(port, dict):
                    continue
                uart = port.get('uart')
                if uart is not None:
                    declarations.append({
                        'kind': 'uart', 'id': uart,
                        'name': section_name + '.' + str(port_name) + '.uart',
                    })
                for field in ('tx', 'rx', 'de'):
                    _gpio(
                        declarations, port.get(field),
                        section_name + '.' + str(port_name) + '.' + field
                    )
            continue
        uart = section.get('uart')
        if uart is not None:
            declarations.append({
                'kind': 'uart', 'id': uart,
                'name': section_name + '.uart',
            })
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
            'name': 'max31865.spi',
        })
        for field in ('sck', 'mosi', 'miso'):
            _gpio(
                declarations, spi.get(field),
                'spi.' + str(bus) + '.' + field, shared=True
            )
        _gpio(declarations, spi.get('cs'), 'max31865.cs')

    voltage = device.get('ac_voltage')
    if isinstance(voltage, dict):
        pin = voltage.get('adc_pin')
        if pin is not None:
            declarations.append({
                'kind': 'adc', 'id': pin, 'name': 'ac_voltage.adc'
            })
            _gpio(declarations, pin, 'ac_voltage.adc.gpio')

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
