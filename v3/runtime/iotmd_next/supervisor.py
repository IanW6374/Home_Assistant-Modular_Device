"""Deterministic service registry and bounded cooperative supervisor."""

SERVICE_STATES = ('registered', 'running', 'degraded', 'failed', 'stopped')
MAX_SERVICES = 16


class SupervisorError(RuntimeError):
    pass


def _service_name(value):
    if not isinstance(value, str) or not value or len(value) > 32:
        raise SupervisorError('service name is invalid')
    for character in value:
        if not (
                character in 'abcdefghijklmnopqrstuvwxyz' or
                character in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' or
                character in '0123456789_.:-'):
            raise SupervisorError('service name is invalid')
    return value


def _safe_detail(service):
    try:
        value = service.snapshot()
        if not isinstance(value, dict) or len(value) > 12:
            raise ValueError
        result = {}
        for key in value:
            _service_name(key)
            item = value[key]
            if item is None or item is True or item is False:
                result[key] = item
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                if item != item or item < -1000000000000 or item > 1000000000000:
                    raise ValueError
                result[key] = item
            elif isinstance(item, str) and len(item) <= 80:
                result[key] = item
            else:
                raise ValueError
        return result
    except Exception:
        return {'diagnostic_error': 'invalid service snapshot'}


def _error_name(value):
    return str(getattr(type(value), '__name__', 'service error'))[:48]


class ServiceRegistry:
    def __init__(self, events, max_failures=3):
        if not isinstance(max_failures, int) or max_failures < 1:
            raise SupervisorError('maximum failures is invalid')
        self._events = events
        self._maximum_failures = max_failures
        self._records = {}
        self._start_order = []

    def register(self, name, service, dependencies=(), critical=False):
        _service_name(name)
        if name in self._records or len(self._records) >= MAX_SERVICES:
            raise SupervisorError('service registration is invalid')
        for dependency in dependencies:
            _service_name(dependency)
        for operation in ('start', 'stop', 'poll', 'snapshot'):
            if not hasattr(service, operation):
                raise SupervisorError('service contract is incomplete')
        self._records[name] = {
            'service': service,
            'dependencies': tuple(dependencies),
            'critical': bool(critical),
            'state': 'registered',
            'failures': 0,
            'last_error': '',
        }

    def _ordered(self):
        pending = list(self._records)
        ordered = []
        while pending:
            moved = False
            for name in tuple(pending):
                dependencies = self._records[name]['dependencies']
                for dependency in dependencies:
                    if dependency not in self._records:
                        raise SupervisorError('service dependency is missing')
                if all(dependency in ordered for dependency in dependencies):
                    ordered.append(name)
                    pending.remove(name)
                    moved = True
            if not moved:
                raise SupervisorError('service dependency cycle detected')
        return ordered

    def start_all(self):
        for name in self._ordered():
            record = self._records[name]
            try:
                record['service'].start()
                record['state'] = 'running'
                record['failures'] = 0
                record['last_error'] = ''
                self._start_order.append(name)
                self._events.add('service_started', name, 'info')
            except Exception as exc:
                record['state'] = 'failed'
                record['failures'] += 1
                record['last_error'] = _error_name(exc)
                self._events.add('service_start_failed', name, 'error')
                if record['critical']:
                    raise

    def poll(self):
        for name in tuple(self._start_order):
            record = self._records[name]
            if record['state'] not in ('running', 'degraded'):
                continue
            try:
                record['service'].poll()
                if record['state'] == 'degraded':
                    self._events.add('service_recovered', name, 'info')
                record['state'] = 'running'
                record['failures'] = 0
                record['last_error'] = ''
            except Exception as exc:
                record['failures'] += 1
                record['last_error'] = _error_name(exc)
                if record['failures'] >= self._maximum_failures:
                    record['state'] = 'failed'
                    self._events.add('service_failed', name, 'error')
                else:
                    record['state'] = 'degraded'
                    self._events.add('service_degraded', name, 'warning')

    def restart(self, name):
        if name not in self._records:
            raise SupervisorError('service is unknown')
        record = self._records[name]
        try:
            record['service'].stop()
        finally:
            record['state'] = 'stopped'
        record['service'].start()
        record['state'] = 'running'
        record['failures'] = 0
        record['last_error'] = ''
        if name not in self._start_order:
            self._start_order.append(name)
        self._events.add('service_restarted', name, 'info')

    def stop_all(self):
        for name in tuple(reversed(self._start_order)):
            record = self._records[name]
            try:
                record['service'].stop()
            except Exception as exc:
                record['last_error'] = _error_name(exc)
                self._events.add('service_stop_failed', name, 'error')
            finally:
                record['state'] = 'stopped'
        self._start_order = []

    def snapshot(self):
        result = []
        for name in sorted(self._records):
            record = self._records[name]
            result.append({
                'name': name,
                'state': record['state'],
                'critical': record['critical'],
                'failures': record['failures'],
                'last_error': record['last_error'],
                'detail': _safe_detail(record['service']),
            })
        return result
