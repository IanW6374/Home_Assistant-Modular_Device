"""Portal lifecycle adapter; page rendering remains a replaceable transport."""


class PortalService:
    def __init__(self, starter, listener_reloader=None):
        self._starter = starter
        self._listener_reloader = listener_reloader
        self.server = None

    async def start(self, *args, **kwargs):
        self.server = await self._starter(*args, **kwargs)
        return self.server

    async def reload_listener(self):
        if self._listener_reloader is None:
            raise RuntimeError('portal listener reload is unavailable')
        self.server = await self._listener_reloader()
        return self.server
