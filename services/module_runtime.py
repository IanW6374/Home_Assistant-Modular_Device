"""Adapter that isolates module runtime operations from transports and UI."""


class ModuleRuntime:
    def __init__(self, broker, loader):
        self.broker = broker
        self.loader = loader

    def inventory(self):
        return {
            'drivers': self.loader.driver_catalog(),
            'modules': self.broker.catalog(),
        }

    def state(self, uuid):
        return self.broker.state(str(uuid))

    def diagnostics(self, uuid):
        return self.broker.diagnostics(str(uuid))

    def command(self, uuid, command, source='service', identity=''):
        return self.broker.submit(
            str(uuid), command, str(source), str(identity)[:64]
        )
