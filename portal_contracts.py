"""Explicit dependency contract between portal transport and application."""


class PortalDependencies:
    def __init__(self, settings, handlers):
        if not isinstance(settings, dict):
            raise ValueError('portal settings must be an object')
        if not isinstance(handlers, dict):
            raise ValueError('portal handlers must be an object')
        self.settings = dict(settings)
        self._handlers = dict(handlers)

    def get(self, name, default=None):
        return self._handlers.get(str(name), default)

    def require(self, name):
        handler = self.get(name)
        if handler is None:
            raise RuntimeError('required portal handler is unavailable: ' + str(name))
        return handler

    def capabilities(self):
        return sorted(name for name, value in self._handlers.items() if value is not None)
