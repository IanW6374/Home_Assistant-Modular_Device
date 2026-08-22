"""Versioned HTTPS device API with mandatory mutual TLS authentication."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import ujson as json
except ImportError:
    import json

try:
    import ussl as ssl
except ImportError:
    import ssl

import http_support


API_VERSION = 2


def make_mtls_context(cert_path, key_path, client_ca_path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    ca_paths = (
        list(client_ca_path)
        if isinstance(client_ca_path, (list, tuple)) else [client_ca_path]
    )
    ca_paths = [path for path in ca_paths if path]
    if not ca_paths:
        raise RuntimeError('at least one API client CA is required')
    for path in ca_paths:
        try:
            context.load_verify_locations(cafile=path)
        except TypeError:
            with open(path, 'rb') as stream:
                context.load_verify_locations(cadata=stream.read())
    if not hasattr(ssl, 'CERT_REQUIRED'):
        raise RuntimeError('this TLS runtime cannot require client certificates')
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class DeviceAPI:
    def __init__(self, broker, health, registry, device_getter, log_output=None,
                 fleet=None, support_getter=None):
        self.broker = broker
        self.health = health
        self.registry = registry
        self.device_getter = device_getter
        self.log_output = log_output
        self.fleet = fleet
        self.support_getter = support_getter

    def dispatch(self, method, path, body, identity):
        route = str(path).split('?', 1)[0]
        is_fleet = route.startswith('/api/v2/fleet')
        scope = (
            'fleet:write' if method == 'POST' else 'fleet:read'
        ) if is_fleet else ('write' if method == 'POST' else 'read')
        client = self.registry.authenticate(identity, scope)
        self._record_request(client, method, route)

        if method == 'GET' and route == '/api/v2/device/inventory':
            return 200, {
                'api_version': API_VERSION,
                'device': self.device_getter(),
                'modules': self.broker.catalog(),
                'fleet': self.fleet.snapshot() if self.fleet else None,
            }
        if method == 'GET' and route == '/api/v2/health':
            return 200, {
                'api_version': API_VERSION, 'health': self.health.snapshot()
            }
        if method == 'GET' and route == '/api/v2/events':
            cursor = self._query_integer(path, 'cursor', 0)
            limit = self._query_integer(path, 'limit', 32)
            return 200, self.health.events_since(cursor, limit)
        if method == 'GET' and route == '/api/v2/support':
            if not self.support_getter:
                raise RuntimeError('support bundle is unavailable')
            return 200, self.support_getter()
        if method == 'GET' and route == '/api/v2/fleet':
            if not self.fleet:
                raise RuntimeError('fleet management is unavailable')
            return 200, self.fleet.snapshot()
        if method == 'POST' and route == '/api/v2/fleet/policy':
            if not self.fleet:
                raise RuntimeError('fleet management is unavailable')
            policy = json.loads(body.decode() if isinstance(body, bytes) else body)
            result = self.fleet.apply_policy(policy)
            self.health.record_event(
                'fleet_policy_applied', 'Applied fleet policy',
                {'policy_sequence': result['policy_sequence']}, force=True,
                component='fleet'
            )
            return 202, result
        if method == 'POST' and (
            route == '/api/v2/fleet/command-result' or
            (
                route.startswith('/api/v2/fleet/commands/') and
                route.endswith('/result')
            )
        ):
            if not self.fleet:
                raise RuntimeError('fleet management is unavailable')
            value = json.loads(body.decode() if isinstance(body, bytes) else body)
            if not isinstance(value, dict):
                raise ValueError('command result must be an object')
            route_identifier = (
                route.split('/')[-2]
                if route.startswith('/api/v2/fleet/commands/') else ''
            )
            result = self.fleet.complete_command(
                route_identifier or value.get('id', ''), value.get('result', 'complete'),
                value.get('detail', '')
            )
            return 200, result

        if method == 'GET' and route == '/api/v1/device':
            return 200, {
                'api_version': API_VERSION,
                'device': self.device_getter(),
                'client': {'label': client.get('label', ''), 'scopes': client.get('scopes', [])},
            }
        if method == 'GET' and route == '/api/v1/modules':
            return 200, {'api_version': API_VERSION, 'modules': self.broker.catalog()}
        if method == 'GET' and route == '/api/v1/health/history':
            return 200, {'api_version': API_VERSION, 'health': self.health.snapshot()}
        if method == 'GET' and route.startswith('/api/v1/operations/'):
            operation = self.broker.operation(route.rsplit('/', 1)[-1])
            return (200, operation) if operation else (404, {'error': 'operation not found'})

        prefix = '/api/v1/modules/'
        if route.startswith(prefix):
            remainder = route[len(prefix):]
            parts = remainder.split('/')
            if len(parts) == 2:
                uuid, action = parts
                if method == 'GET' and action == 'state':
                    try:
                        state = self.broker.state(uuid)
                    except KeyError:
                        return self._module_not_found(client, uuid)
                    return 200, {'module': uuid, 'state': state}
                if method == 'GET' and action == 'diagnostics':
                    try:
                        diagnostics = self.broker.diagnostics(uuid)
                    except KeyError:
                        return self._module_not_found(client, uuid)
                    return 200, {'module': uuid, 'diagnostics': diagnostics}
                if method == 'POST' and action == 'commands':
                    command = json.loads(body.decode() if isinstance(body, bytes) else body)
                    try:
                        operation = self.broker.submit(
                            uuid, command, 'api', client.get('fingerprint', '')[:16]
                        )
                    except KeyError:
                        return self._module_not_found(client, uuid)
                    if self.health:
                        self.health.increment('api_commands')
                    self._audit(client, uuid, operation['id'])
                    return 202, operation
        return 404, {'error': 'endpoint not found'}

    @staticmethod
    def _query_integer(path, name, default):
        query = str(path).split('?', 1)
        if len(query) == 1:
            return default
        for item in query[1].split('&'):
            key_value = item.split('=', 1)
            if key_value[0] == name:
                return int(key_value[1]) if len(key_value) == 2 else default
        return default

    def _record_request(self, client, method, route):
        label = str(client.get('label', 'client'))
        if self.health:
            count = self.health.increment('api_requests')
            # Keep routine reads as an aggregate counter so polling clients do
            # not displace significant history or cause excessive flash wear.
            if method == 'POST' or count % 100 == 0:
                self.health.record_event(
                    'api_request', str(method) + ' ' + str(route),
                    {'client': label, 'request_count': count}, force=False,
                    component='api'
                )
        if self.log_output:
            self.log_output(
                'API', 'Request',
                {'log': label + ' ' + str(method) + ' ' + str(route)}, 'INFO'
            )

    def _module_not_found(self, client, uuid):
        if self.health:
            self.health.increment('api_failures')
            self.health.record_event(
                'api_not_found', 'Unknown module UUID ' + str(uuid),
                {'client': str(client.get('label', 'client'))}, force=False,
                severity='warning', component='api'
            )
        return 404, {'error': 'module not found', 'module': uuid}

    def _audit(self, client, uuid, operation_id):
        if self.log_output:
            self.log_output(
                'API', 'Module command',
                {'log': (
                    str(client.get('label', 'client')) + ' requested module ' +
                    str(uuid) + ' operation ' + str(operation_id)
                )},
                'INFO'
            )


async def _write_response(writer, status, payload, keep_alive=False):
    reason = {
        200: 'OK', 202: 'Accepted', 400: 'Bad Request',
        401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found',
        405: 'Method Not Allowed', 413: 'Payload Too Large',
        503: 'Service Unavailable',
    }.get(status, 'Error')
    body = json.dumps(payload).encode()
    headers = http_support.add_security_headers((
        ('Cache-Control', 'no-store'),
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(body))),
        ('Connection', 'keep-alive' if keep_alive else 'close'),
    ))
    writer.write(
        ('HTTP/1.1 ' + str(status) + ' ' + reason + '\r\n' +
         ''.join(name + ': ' + value + '\r\n' for name, value in headers) +
         '\r\n').encode() + body
    )
    await writer.drain()


def _peer_certificate(reader):
    stream = getattr(reader, 's', None)
    if stream is None or not hasattr(stream, 'getpeercert'):
        raise PermissionError('TLS peer certificate is unavailable')
    value = stream.getpeercert(True)
    if not value:
        raise PermissionError('client certificate is required')
    return value


async def start_device_api(settings, api):
    if not settings.get('enabled'):
        return None
    maximum = int(settings.get('max_body_bytes', 8192))

    async def handle(reader, writer):
        try:
            # MicroPython's TLS server defers the handshake until the first
            # stream read. Inspecting the certificate before that read resets
            # otherwise valid clients during ClientHello.
            identity = None
            for request_number in range(8):
                line, headers = await http_support.read_request(reader)
                if not line:
                    return
                if identity is None:
                    identity = _peer_certificate(reader)
                parts = line.decode().strip().split()
                if len(parts) != 3:
                    raise ValueError('invalid HTTP request line')
                method, path, version = parts
                if method not in ('GET', 'POST'):
                    await _write_response(writer, 405, {'error': 'method not allowed'})
                    return
                length = int(headers.get('content-length', '0') or 0)
                body = await http_support.read_exact_body(reader, length, maximum) if length else b''
                status, payload = api.dispatch(method, path, body, identity)
                connection = str(headers.get('connection', '')).lower()
                keep_alive = (
                    request_number < 7 and
                    connection != 'close' and
                    (version == 'HTTP/1.1' or connection == 'keep-alive')
                )
                await _write_response(writer, status, payload, keep_alive)
                if not keep_alive:
                    return
        except PermissionError as exc:
            if api.health:
                api.health.increment('api_failures')
            if api.log_output:
                api.log_output('API', 'Rejected', {'log': str(exc)}, 'ERROR')
            await _write_response(writer, 403, {'error': str(exc)})
        except KeyError as exc:
            await _write_response(writer, 404, {'error': str(exc)})
        except RuntimeError as exc:
            if api.health:
                api.health.increment('api_failures')
            await _write_response(writer, 503, {'error': str(exc)})
        except Exception as exc:
            if api.health:
                api.health.increment('api_failures')
            if api.log_output:
                api.log_output('API', 'Error', {'log': str(exc)}, 'ERROR')
            await _write_response(writer, 400, {'error': str(exc)})
        finally:
            try:
                writer.close()
                if hasattr(writer, 'wait_closed'):
                    await writer.wait_closed()
            except Exception:
                pass

    context = make_mtls_context(
        settings['cert_path'], settings['key_path'], settings['client_ca_paths']
        if 'client_ca_paths' in settings else settings['client_ca_path']
    )
    return await asyncio.start_server(
        handle, settings.get('host', '0.0.0.0'), int(settings.get('port', 8444)),
        backlog=2, ssl=context
    )
