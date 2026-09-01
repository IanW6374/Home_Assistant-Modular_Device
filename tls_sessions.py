"""Opaque TLS-session seam for runtimes that may support resumption later."""


class TLSSessionHandle:
    """Do not expose a port-specific SSL session object to services."""

    def __init__(self, native=None, supported=False):
        self._native = native
        self.supported = bool(supported and native is not None)

    def clear(self):
        self._native = None
        self.supported = False


async def open_tls_connection(asyncio_module, host, port, context,
                              server_hostname=None, session=None):
    """Open TLS while accepting a future session handle.

    MicroPython 1.29 does not expose a stable uasyncio session-resumption
    argument.  The handle is therefore intentionally ignored there.
    """
    del session
    try:
        return await asyncio_module.open_connection(
            host, port, ssl=context,
            server_hostname=server_hostname or host
        )
    except TypeError:
        return await asyncio_module.open_connection(host, port, ssl=context)
