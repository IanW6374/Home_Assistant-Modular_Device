"""Greenfield application kernel composition and bounded diagnostics."""

from .configuration import migrate_configuration
from .reference_sensor import ReferenceSensor
from .resources import ResourceManager
from .supervisor import ServiceRegistry

MAX_EVENTS = 32


class KernelError(RuntimeError):
    pass


class EventJournal:
    def __init__(self, maximum=MAX_EVENTS):
        self._maximum = maximum
        self._sequence = 0
        self._items = []

    def add(self, code, source, severity):
        self._sequence += 1
        self._items.append({
            'sequence': self._sequence,
            'code': str(code)[:48],
            'source': str(source)[:32],
            'severity': str(severity)[:12],
        })
        if len(self._items) > self._maximum:
            self._items.pop(0)

    def snapshot(self):
        return [dict(item) for item in self._items]


class ApplicationKernel:
    def __init__(self, platform, driver_factories=None, service_factories=None,
                 domain_factories=None):
        self._platform = platform
        self._events = EventJournal()
        self._resources = ResourceManager(platform)
        self._drivers = driver_factories or {
            ReferenceSensor.DRIVER: self._reference_factory,
        }
        self._service_factories = service_factories or {}
        self._domain_factories = domain_factories or {}
        self._configuration = None
        self._supervisor = None
        self._state = 'idle'

    def _reference_factory(self, configuration):
        return ReferenceSensor(self._resources, configuration)

    def boot(self, configuration):
        if self._state == 'running':
            raise KernelError('kernel is already running')
        self._state = 'validating'
        try:
            plan = migrate_configuration(configuration)
            self._configuration = plan['configuration']
            service_settings = self._configuration['services']
            self._supervisor = ServiceRegistry(
                self._events, service_settings['max_failures']
            )
            for transport in self._configuration['transports']:
                if not transport['enabled']:
                    continue
                factory = self._service_factories.get(transport['adapter'])
                if factory is None:
                    raise KernelError('transport adapter is unavailable')
                self._supervisor.register(
                    transport['id'], factory(transport),
                    transport['dependencies'], transport['critical']
                )
            for name in ('identity', 'fleet'):
                domain = self._configuration[name]
                if not domain['enabled']:
                    continue
                factory = self._domain_factories.get(name)
                if factory is None:
                    raise KernelError(name + ' service is unavailable')
                self._supervisor.register(
                    name, factory(domain), domain['dependencies'],
                    domain['critical']
                )
            for module in self._configuration['modules']:
                if not module['enabled']:
                    continue
                factory = self._drivers.get(module['driver'])
                if factory is None:
                    raise KernelError('module driver is unavailable')
                self._supervisor.register(module['id'], factory(module))
            self._supervisor.start_all()
            failed = [
                item for item in self._supervisor.snapshot()
                if item['state'] == 'failed'
            ]
            if failed:
                raise KernelError('module start failed')
            self._state = 'running'
            self._events.add('kernel_started', 'kernel', 'info')
            return plan
        except Exception:
            if self._supervisor is not None:
                self._supervisor.stop_all()
            if self._configuration is not None:
                for module in self._configuration['modules']:
                    self._resources.release_owner(module['id'])
            self._state = 'recovery'
            self._events.add('kernel_boot_failed', 'kernel', 'error')
            raise

    def poll(self):
        if self._state != 'running':
            raise KernelError('kernel is not running')
        self._supervisor.poll()

    def restart_service(self, name):
        if self._state != 'running':
            raise KernelError('kernel is not running')
        self._supervisor.restart(name)

    def shutdown(self):
        if self._supervisor is not None:
            self._supervisor.stop_all()
        if self._configuration is not None:
            for module in self._configuration['modules']:
                self._resources.release_owner(module['id'])
        self._state = 'stopped'
        self._events.add('kernel_stopped', 'kernel', 'info')

    def snapshot(self):
        services = [] if self._supervisor is None else self._supervisor.snapshot()
        failed = len([item for item in services if item['state'] == 'failed'])
        degraded = len([
            item for item in services if item['state'] == 'degraded'
        ])
        if self._state == 'recovery' or failed:
            health_state = 'failed'
        elif degraded:
            health_state = 'degraded'
        elif self._state == 'running':
            health_state = 'healthy'
        else:
            health_state = 'inactive'
        return {
            'contract_version': 1,
            'kernel_state': self._state,
            'device': '' if self._configuration is None else
                self._configuration['device']['name'],
            'health': {
                'state': health_state,
                'services_total': len(services),
                'services_degraded': degraded,
                'services_failed': failed,
            },
            'services': services,
            'resources': self._resources.snapshot(),
            'events': self._events.snapshot(),
        }

    def support_snapshot(self):
        capabilities = self._platform.capabilities()
        return {
            'contract_version': 1,
            'platform_abi': capabilities['abi_version'],
            'board': dict(capabilities['board']),
            'kernel': self.snapshot(),
        }
