"""Bounded request and response values shared by v3 transport adapters."""

try:
    import ujson as json
except ImportError:
    import json


MAX_PATH = 160
MAX_BODY = 4096
MAX_RESPONSE = 8192
METHODS = ('GET', 'POST')


class TransportContractError(ValueError):
    pass


def _bounded_text(value, name, maximum):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise TransportContractError(name + ' is invalid')
    return value


class TransportRequest:
    def __init__(self, method, path, body=b'', identity=None):
        method = str(method).upper()
        if method not in METHODS:
            raise TransportContractError('request method is unsupported')
        _bounded_text(path, 'request path', MAX_PATH)
        if not path.startswith('/') or '\r' in path or '\n' in path:
            raise TransportContractError('request path is invalid')
        if isinstance(body, str):
            body = body.encode()
        if not isinstance(body, bytes) or len(body) > MAX_BODY:
            raise TransportContractError('request body is invalid')
        if identity is not None and not isinstance(identity, dict):
            raise TransportContractError('request identity is invalid')
        self.method = method
        self.path = path
        self.body = body
        self.identity = dict(identity or {})


class TransportResponse:
    def __init__(self, status, body, content_type='application/json'):
        status = int(status)
        if status < 100 or status > 599:
            raise TransportContractError('response status is invalid')
        _bounded_text(content_type, 'response content type', 64)
        if isinstance(body, (dict, list)):
            encoded = json.dumps(body, separators=(',', ':'))
        elif isinstance(body, bytes):
            encoded = body
        elif isinstance(body, str):
            encoded = body
        else:
            raise TransportContractError('response body is invalid')
        if len(encoded) > MAX_RESPONSE:
            raise TransportContractError('response body is too large')
        self.status = status
        self.body = encoded
        self.content_type = content_type

    def snapshot(self):
        return {
            'status': self.status,
            'content_type': self.content_type,
            'body_bytes': len(self.body),
        }
