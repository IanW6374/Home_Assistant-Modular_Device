"""Transport adapters for the v3 MQTT, portal and mTLS Device API services."""

try:
    import ujson as json
except ImportError:
    import json

from .connectivity import PROBE_NAMES
from .presentation import html_escape, render_document, render_form
from .transport_contracts import TransportRequest, TransportResponse


API_VERSION = 3
MAX_MQTT_PAYLOAD = 4096


def _adapter(adapter, operations):
    for operation in operations:
        if not callable(getattr(adapter, operation, None)):
            raise ValueError('transport adapter is incomplete')
    return adapter


def _safe_adapter_status(adapter):
    try:
        value = adapter.status()
        if not isinstance(value, dict) or len(value) > 8:
            raise ValueError
        result = {}
        for key, item in value.items():
            key = str(key)[:24]
            if item is None or isinstance(item, (bool, int, float)):
                result[key] = item
            elif isinstance(item, str):
                result[key] = item[:64]
            else:
                raise ValueError
        return result
    except Exception:
        return {'state': 'unavailable'}


class WiFiService:
    def __init__(self, adapter):
        self._adapter = _adapter(adapter, ('start', 'stop', 'poll', 'status'))

    def start(self):
        self._adapter.start()

    def stop(self):
        self._adapter.stop()

    def poll(self):
        self._adapter.poll()

    def snapshot(self):
        return _safe_adapter_status(self._adapter)


class MQTTService:
    def __init__(self, adapter, state_getter, topic_prefix):
        self._adapter = _adapter(
            adapter, ('connect', 'disconnect', 'poll', 'publish', 'status')
        )
        self._state_getter = state_getter
        self._topic = self._topic_prefix(topic_prefix)
        self._published = 0

    @staticmethod
    def _topic_prefix(value):
        value = str(value).strip('/')
        if not value or len(value) > 96 or any(
                character in value for character in ('#', '+', '\x00')):
            raise ValueError('MQTT topic prefix is invalid')
        return value

    def start(self):
        self._adapter.connect()
        self._adapter.publish(self._topic + '/availability', 'online', True, 1)

    def stop(self):
        try:
            self._adapter.publish(
                self._topic + '/availability', 'offline', True, 1
            )
        finally:
            self._adapter.disconnect()

    def poll(self):
        self._adapter.poll()

    def publish_state(self):
        state = self._state_getter()
        payload = json.dumps(state, separators=(',', ':'))
        if len(payload) > MAX_MQTT_PAYLOAD:
            raise ValueError('MQTT state payload is too large')
        self._adapter.publish(self._topic + '/state', payload, False, 1)
        self._published += 1

    def publish_discovery(self, component, payload):
        component = str(component)
        if not component or len(component) > 48 or '/' in component:
            raise ValueError('discovery component is invalid')
        encoded = json.dumps(payload, separators=(',', ':'))
        if len(encoded) > MAX_MQTT_PAYLOAD:
            raise ValueError('MQTT discovery payload is too large')
        self._adapter.publish(
            'homeassistant/sensor/' + component + '/config', encoded, True, 1
        )
        self._published += 1

    def snapshot(self):
        value = _safe_adapter_status(self._adapter)
        value['published'] = self._published
        return value


class SyslogService:
    """Bounded remote-log transport using the same service lifecycle."""

    def __init__(self, adapter):
        self._adapter = _adapter(
            adapter, ('start', 'stop', 'poll', 'emit', 'status')
        )
        self._emitted = 0

    def start(self):
        self._adapter.start()

    def stop(self):
        self._adapter.stop()

    def poll(self):
        self._adapter.poll()

    def emit(self, timestamp, message, severity='INFO', audit=False):
        if self._adapter.emit(timestamp, message, severity, bool(audit)):
            self._emitted += 1
            return True
        return False

    def snapshot(self):
        value = _safe_adapter_status(self._adapter)
        value['emitted'] = self._emitted
        return value


class PortalService:
    def __init__(self, adapter, snapshot_getter, connectivity_getter,
                 connectivity_runner=None, identity_getter=None,
                 fleet_getter=None, migration_getter=None,
                 qualification_getter=None):
        self._adapter = _adapter(adapter, ('start', 'stop', 'poll', 'status'))
        self._snapshot_getter = snapshot_getter
        self._connectivity_getter = connectivity_getter
        self._connectivity_runner = connectivity_runner
        self._identity_getter = identity_getter
        self._fleet_getter = fleet_getter
        self._migration_getter = migration_getter
        self._qualification_getter = qualification_getter

    def start(self):
        self._adapter.start(self.handle)

    def stop(self):
        self._adapter.stop()

    def poll(self):
        self._adapter.poll()

    def handle(self, request):
        if not isinstance(request, TransportRequest):
            raise ValueError('portal request contract is invalid')
        role = str(request.identity.get('role', ''))
        if role not in ('viewer', 'operator', 'administrator'):
            return TransportResponse(401, 'Authentication required', 'text/plain')
        route = request.path.split('?', 1)[0]
        if route in ('/', '/status'):
            if request.method != 'GET':
                return TransportResponse(405, 'Method not allowed', 'text/plain')
            snapshot = self._snapshot_getter()
            qualification = (
                self._qualification_getter()
                if self._qualification_getter is not None else None
            )
            qualification_content = ''
            if qualification is not None:
                gates = qualification.get('gates', ())
                counts = {
                    'passed': 0, 'failed': 0,
                    'in-progress': 0, 'not-run': 0,
                }
                for gate in gates:
                    state = str(gate.get('status', 'not-run'))
                    if state in counts:
                        counts[state] += 1
                overall = (
                    'Ready' if qualification.get('promotion_ready') else
                    ('Blocked' if counts['failed'] else
                     ('In progress' if counts['in-progress'] else 'Not started'))
                )
                qualification_content = (
                    '<p>Release qualification: <strong>' +
                    html_escape(overall) + '</strong> (' +
                    html_escape(counts['passed']) + ' passed, ' +
                    html_escape(counts['failed']) + ' failed, ' +
                    html_escape(counts['in-progress'] + counts['not-run']) +
                    ' open)</p>'
                )
            content = (
                '<p>Kernel: <strong>' +
                html_escape(snapshot.get('kernel_state', 'unknown')) +
                '</strong></p><p>Health: <strong>' +
                html_escape(snapshot.get('health', {}).get('state', 'unknown')) +
                '</strong></p>' + qualification_content
            )
            return TransportResponse(
                200, render_document('Overview', role, '/status', content),
                'text/html; charset=utf-8'
            )
        if route == '/status/connectivity':
            if request.method != 'GET':
                return TransportResponse(405, 'Method not allowed', 'text/plain')
            rows = []
            for name, record in self._connectivity_getter().get(
                    'probes', {}).items():
                rows.append(
                    '<li>' + html_escape(name) + ': ' +
                    html_escape(record.get('state', 'unknown')) + '</li>'
                )
            return TransportResponse(
                200, render_document(
                    'Connectivity', role, route, '<ul>' + ''.join(rows) + '</ul>'
                ), 'text/html; charset=utf-8'
            )
        if route in ('/device/identity', '/device/fleet',
                     '/maintenance/migration', '/maintenance/qualification'):
            if request.method != 'GET':
                return TransportResponse(405, 'Method not allowed', 'text/plain')
            if route == '/maintenance/migration' and role != 'administrator':
                return TransportResponse(403, 'Administrator role required', 'text/plain')
            getter = {
                '/device/identity': self._identity_getter,
                '/device/fleet': self._fleet_getter,
                '/maintenance/migration': self._migration_getter,
                '/maintenance/qualification': self._qualification_getter,
            }[route]
            if getter is None:
                return TransportResponse(503, 'Service unavailable', 'text/plain')
            value = getter()
            rows = []
            for key in sorted(value):
                item = value[key]
                if item is None or isinstance(item, (str, int, float, bool)):
                    rows.append('<li>' + html_escape(key) + ': ' +
                                html_escape(item) + '</li>')
            title = {
                '/device/identity': 'Identity',
                '/device/fleet': 'Fleet',
                '/maintenance/migration': 'Migration',
                '/maintenance/qualification': 'Release qualification',
            }[route]
            if route == '/maintenance/qualification':
                rows = []
                for gate in value.get('gates', ()):
                    rows.append(
                        '<li><strong>' + html_escape(gate.get('name', '')) +
                        '</strong>: ' + html_escape(gate.get('status', 'not-run')) +
                        ' — ' + html_escape(gate.get('observed', 0)) + ' / ' +
                        html_escape(gate.get('required', 0)) + '</li>'
                    )
            return TransportResponse(
                200, render_document(
                    title, role, route, '<ul>' + ''.join(rows) + '</ul>'
                ), 'text/html; charset=utf-8'
            )
        if route == '/maintenance/diagnostics':
            if role not in ('operator', 'administrator'):
                return TransportResponse(403, 'Operator role required', 'text/plain')
            notice = ''
            if request.method == 'POST':
                if request.identity.get('csrf_valid') is not True:
                    return TransportResponse(403, 'CSRF validation failed', 'text/plain')
                target = ''
                try:
                    text = request.body.decode()
                    if text.startswith('target='):
                        target = text[7:]
                except Exception:
                    pass
                if target not in PROBE_NAMES or self._connectivity_runner is None:
                    return TransportResponse(400, 'Invalid diagnostic target', 'text/plain')
                record = self._connectivity_runner(target)
                notice = '<p>Result: ' + html_escape(record['state']) + '</p>'
            elif request.method != 'GET':
                return TransportResponse(405, 'Method not allowed', 'text/plain')
            content = notice + render_form(
                'diagnostic-run', role, {'target': PROBE_NAMES}
            )
            return TransportResponse(
                200, render_document('Diagnostics', role, route, content),
                'text/html; charset=utf-8'
            )
        return TransportResponse(404, 'Not found', 'text/plain')

    def snapshot(self):
        return _safe_adapter_status(self._adapter)


class DeviceAPIService:
    def __init__(self, adapter, snapshot_getter, connectivity_getter,
                 identity=None, fleet=None, qualification=None):
        self._adapter = _adapter(adapter, ('start', 'stop', 'poll', 'status'))
        self._snapshot_getter = snapshot_getter
        self._connectivity_getter = connectivity_getter
        self._identity = identity
        self._fleet = fleet
        self._qualification = qualification

    def start(self):
        self._adapter.start(self.handle, require_mtls=True)

    def stop(self):
        self._adapter.stop()

    def poll(self):
        self._adapter.poll()

    @staticmethod
    def _authorized(request, scope):
        identity = request.identity
        scopes = identity.get('scopes', ())
        if not isinstance(scopes, (list, tuple)):
            return False
        return (
            identity.get('verified') is True and
            scope in scopes
        )

    def handle(self, request):
        if not isinstance(request, TransportRequest):
            raise ValueError('API request contract is invalid')
        route = request.path.split('?', 1)[0]
        if route == '/api/v3/fleet/report':
            if not self._authorized(request, 'fleet:read') or self._fleet is None:
                return TransportResponse(403, {'error': 'mTLS scope denied'})
            if request.method != 'GET':
                return TransportResponse(405, {'error': 'method not allowed'})
            return TransportResponse(200, self._fleet.report())
        if route == '/api/v3/fleet/policy':
            if not self._authorized(request, 'fleet:write') or self._fleet is None:
                return TransportResponse(403, {'error': 'mTLS scope denied'})
            if request.method != 'POST':
                return TransportResponse(405, {'error': 'method not allowed'})
            try:
                policy = json.loads(request.body.decode())
                result = self._fleet.apply_policy(policy)
            except Exception as exc:
                return TransportResponse(400, {
                    'error': str(getattr(type(exc), '__name__', 'invalid policy'))[:48]
                })
            return TransportResponse(200, {
                'api_version': API_VERSION,
                'policy_sequence': result['policy_sequence'],
            })
        if not self._authorized(request, 'read'):
            return TransportResponse(403, {'error': 'mTLS scope denied'})
        if request.method != 'GET':
            return TransportResponse(405, {'error': 'method not allowed'})
        snapshot = self._snapshot_getter()
        if route == '/api/v3/device':
            return TransportResponse(200, {
                'api_version': API_VERSION,
                'device': snapshot.get('device', ''),
                'kernel_state': snapshot.get('kernel_state', 'unknown'),
            })
        if route == '/api/v3/health':
            return TransportResponse(200, {
                'api_version': API_VERSION,
                'health': snapshot.get('health', {}),
            })
        if route == '/api/v3/services':
            return TransportResponse(200, {
                'api_version': API_VERSION,
                'services': snapshot.get('services', ()),
            })
        if route == '/api/v3/connectivity':
            return TransportResponse(200, {
                'api_version': API_VERSION,
                'connectivity': self._connectivity_getter(),
            })
        if route == '/api/v3/identity' and self._identity is not None:
            return TransportResponse(200, {
                'api_version': API_VERSION,
                'identity': self._identity.snapshot(),
            })
        if route == '/api/v3/qualification' and self._qualification is not None:
            return TransportResponse(200, {
                'api_version': API_VERSION,
                'qualification': self._qualification.snapshot(),
            })
        return TransportResponse(404, {'error': 'not found'})

    def snapshot(self):
        value = _safe_adapter_status(self._adapter)
        value['mtls_required'] = True
        return value


def build_service_factories(adapters, snapshot_getter, connectivity,
                            identity=None, fleet=None, migration=None,
                            qualification=None):
    """Return configuration factories without exposing adapter objects."""
    if not isinstance(adapters, dict):
        raise ValueError('transport adapters are invalid')

    def wifi(unused):
        return WiFiService(adapters.get('wifi'))

    def mqtt(configuration):
        topic = configuration.get('settings', {}).get('topic_prefix', '')
        return MQTTService(adapters.get('mqtt'), snapshot_getter, topic)

    def portal(unused):
        return PortalService(
            adapters.get('portal'), snapshot_getter,
            connectivity.diagnostics, connectivity.run,
            None if identity is None else identity.snapshot,
            None if fleet is None else fleet.snapshot,
            None if migration is None else migration.state,
            None if qualification is None else qualification.snapshot,
        )

    def device_api(unused):
        return DeviceAPIService(
            adapters.get('device-api'), snapshot_getter,
            connectivity.diagnostics, identity, fleet, qualification
        )

    def syslog(unused):
        return SyslogService(adapters.get('syslog'))

    return {
        'wifi': wifi,
        'mqtt': mqtt,
        'portal': portal,
        'device-api': device_api, 'syslog': syslog,
        'connectivity': lambda unused: connectivity,
    }
