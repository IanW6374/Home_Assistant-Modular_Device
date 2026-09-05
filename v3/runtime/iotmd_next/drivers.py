"""V3 driver service boundary and catalog for the supported v2.5 set."""

SUPPORTED_DRIVER_TYPES = {
    'dht11': ('sensor:dht11',),
    'ems': ('sensor:EMS-Boiler',),
    'grove_ac_voltage': ('sensor:Grove-AC-Voltage',),
    'hcsr04': ('sensor:hcsr04',),
    'light': ('light:brightness', 'light:onoff', 'light:rgb'),
    'max31865_pt1000': ('sensor:MAX31865-PT1000',),
    'modbus_transport': ('sensor:RS485-Modbus-Multiport',),
    'rs485_modbus': ('sensor:RS485-Modbus',),
    'switch_dimmer': ('switch:dimmer',),
    'switch_onoff': ('switch:onoff',),
    'whes': ('sensor:WHES',),
}


class DriverError(RuntimeError):
    pass


def driver_catalog():
    return [
        {'driver': name, 'types': list(SUPPORTED_DRIVER_TYPES[name])}
        for name in sorted(SUPPORTED_DRIVER_TYPES)
    ]


class DriverService:
    """Own resources while delegating hardware behavior to an injected backend."""

    def __init__(self, resources, configuration, backend):
        name = configuration['driver']
        if name not in SUPPORTED_DRIVER_TYPES:
            raise DriverError('driver is not in the supported catalog')
        for operation in ('start', 'stop', 'poll', 'snapshot'):
            if not callable(getattr(backend, operation, None)):
                raise DriverError('driver backend is incomplete')
        self._resources = resources
        self._configuration = configuration
        self._backend = backend
        self._handles = []
        self._polls = 0

    def start(self):
        try:
            for resource in self._configuration['resources']:
                handle = self._resources.claim(
                    resource['kind'], resource['identifier'],
                    self._configuration['id'], resource['shared'],
                    resource['signature']
                )
                self._resources.construct(handle, resource['parameters'])
                self._handles.append(handle)
            self._backend.start(
                tuple(self._handles), dict(self._configuration['settings'])
            )
        except Exception:
            self._resources.release_owner(self._configuration['id'])
            self._handles = []
            raise

    def stop(self):
        try:
            self._backend.stop()
        finally:
            self._resources.release_owner(self._configuration['id'])
            self._handles = []

    def poll(self):
        try:
            self._backend.poll()
        except Exception:
            for handle in self._handles:
                self._resources.recover(handle)
            raise
        self._polls += 1

    def snapshot(self):
        value = self._backend.snapshot()
        if not isinstance(value, dict) or len(value) > 8:
            raise DriverError('driver snapshot is invalid')
        state = str(value.get('state', 'unknown'))[:32]
        return {
            'driver': self._configuration['driver'],
            'state': state,
            'resources': len(self._handles),
            'polls': self._polls,
        }


def build_driver_factories(resources, backends):
    if not isinstance(backends, dict):
        raise DriverError('driver backends are invalid')
    result = {}

    def make_factory(name):
        def factory(configuration):
            backend_factory = backends.get(name)
            if not callable(backend_factory):
                raise DriverError('driver backend is unavailable')
            return DriverService(resources, configuration, backend_factory(configuration))
        return factory

    for name in SUPPORTED_DRIVER_TYPES:
        result[name] = make_factory(name)
    return result
