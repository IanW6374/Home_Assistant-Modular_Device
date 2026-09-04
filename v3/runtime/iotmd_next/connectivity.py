"""Unified, bounded connectivity diagnostics for product transports."""


PROBE_NAMES = ('dns', 'time', 'tls', 'mqtt', 'ca', 'syslog', 'release')


def _error_name(value):
    return str(getattr(type(value), '__name__', 'probe error'))[:48]


class ConnectivityDiagnostics:
    def __init__(self, probes):
        if not isinstance(probes, dict) or set(probes) != set(PROBE_NAMES):
            raise ValueError('connectivity probe set is incomplete')
        for probe in probes.values():
            if not callable(probe):
                raise ValueError('connectivity probe is invalid')
        self._probes = dict(probes)
        self._results = {
            name: {'state': 'unknown', 'attempts': 0, 'error': ''}
            for name in PROBE_NAMES
        }
        self._index = 0
        self._running = False

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def poll(self):
        if not self._running:
            return
        name = PROBE_NAMES[self._index]
        self._index = (self._index + 1) % len(PROBE_NAMES)
        record = self._results[name]
        record['attempts'] += 1
        try:
            result = self._probes[name]()
            record['state'] = 'reachable' if result else 'unreachable'
            record['error'] = ''
        except Exception as exc:
            record['state'] = 'error'
            record['error'] = _error_name(exc)

    def run(self, name):
        if name not in self._probes:
            raise ValueError('connectivity probe is unknown')
        while PROBE_NAMES[self._index] != name:
            self._index = (self._index + 1) % len(PROBE_NAMES)
        self.poll()
        return dict(self._results[name])

    def diagnostics(self):
        return {
            'running': self._running,
            'probes': {
                name: dict(self._results[name]) for name in PROBE_NAMES
            },
        }

    def snapshot(self):
        counts = {
            'reachable': 0, 'unreachable': 0, 'error': 0, 'unknown': 0,
        }
        for record in self._results.values():
            state = record['state']
            counts[state] = counts.get(state, 0) + 1
        counts['running'] = self._running
        return counts
