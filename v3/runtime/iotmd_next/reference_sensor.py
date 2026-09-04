"""Small resource-owning reference sensor for the v3 driver contract."""


class ReferenceSensorError(RuntimeError):
    pass


class ReferenceSensor:
    DRIVER = 'reference-sensor'

    def __init__(self, resources, configuration, reader=None):
        self._resources = resources
        self._configuration = configuration
        self._reader = reader if reader is not None else self._default_reader
        self._handle = None
        self._samples = 0
        self._value = None
        settings = configuration['settings']
        self._scale = settings.get('scale', 1)
        self._offset = settings.get('offset', 0)
        if (not isinstance(self._scale, (int, float)) or
                isinstance(self._scale, bool) or
                not isinstance(self._offset, (int, float)) or
                isinstance(self._offset, bool)):
            raise ReferenceSensorError('reference sensor scaling is invalid')

    @staticmethod
    def _default_reader(identifier):
        # A deterministic contract fixture, not a claim of physical sensing.
        return 0

    def start(self):
        resource = self._configuration['resources'][0]
        self._handle = self._resources.claim(
            resource['kind'], resource['identifier'],
            self._configuration['id']
        )

    def stop(self):
        if self._handle is not None:
            self._resources.release(self._handle)
            self._handle = None

    def poll(self):
        if self._handle is None:
            raise ReferenceSensorError('reference sensor is not started')
        raw = self._reader(self._configuration['resources'][0]['identifier'])
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise ReferenceSensorError('reference sensor sample is invalid')
        self._value = raw * self._scale + self._offset
        self._samples += 1

    def snapshot(self):
        return {
            'driver': self.DRIVER,
            'started': self._handle is not None,
            'samples': self._samples,
            'value': self._value,
        }
