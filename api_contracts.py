"""Transport-neutral request and response contracts for the Device API."""


class APIRequest:
    """A protocol request independent of HTTP, Wi-Fi, Ethernet, or USB."""

    def __init__(self, method, path, body=b'', identity=None, client=None,
                 transport='unknown', peer='unknown'):
        self.method = str(method).upper()
        self.path = str(path)
        self.body = body if body is not None else b''
        self.identity = identity
        self.client = client
        self.transport = str(transport)
        self.peer = str(peer)


class APIResponse:
    """A protocol response that a concrete transport can serialise."""

    def __init__(self, status, payload, headers=None):
        self.status = int(status)
        self.payload = payload
        self.headers = dict(headers or {})

    def as_tuple(self):
        return self.status, self.payload


class APIRouter:
    """Small exact/prefix route registry used by non-HTTP transports too."""

    def __init__(self):
        self._routes = []

    def add(self, method, path, handler, prefix=False):
        self._routes.append((str(method).upper(), str(path), bool(prefix), handler))

    def resolve(self, method, path):
        route = str(path).split('?', 1)[0]
        method = str(method).upper()
        for expected_method, expected_path, prefix, handler in self._routes:
            if method != expected_method:
                continue
            if route == expected_path or (prefix and route.startswith(expected_path)):
                return handler
        return None
