"""Compact persistent runtime-health counters and significant-event history.

The device writes counters in batches to limit flash wear.  Callers can force a
checkpoint for events that must survive an immediate restart, such as update
results and startup failures.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

try:
    import time
except ImportError:
    time = None


HEALTH_PATH = '.runtime-health.json'
FORMAT_VERSION = 1
MAX_EVENTS = 24
DEFAULT_CHECKPOINT_CHANGES = 10


def _now():
    try:
        return int(time.time()) if time else 0
    except Exception:
        return 0


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _empty():
    return {
        'format_version': FORMAT_VERSION,
        'counters': {
            'boots': 0,
            'watchdog_resets': 0,
            'wifi_reconnects': 0,
            'mqtt_publish_drops': 0,
            'mqtt_publish_failures': 0,
            'api_requests': 0,
            'api_failures': 0,
            'api_commands': 0,
        },
        'observations': {
            'last_reset_cause': '',
            'last_startup_exception': '',
            'last_wifi_rssi': None,
            'minimum_wifi_rssi': None,
            'minimum_free_heap': None,
            'last_update_result': {},
        },
        'events': [],
        'updated_at': 0,
    }


class HealthHistory:
    def __init__(self, path=HEALTH_PATH, max_events=MAX_EVENTS,
                 checkpoint_changes=DEFAULT_CHECKPOINT_CHANGES):
        self.path = path
        self.max_events = max(1, int(max_events))
        self.checkpoint_changes = max(1, int(checkpoint_changes))
        self._dirty_changes = 0
        self.data = self._load()

    def _load(self):
        try:
            with open(self.path, 'r') as stream:
                value = json.load(stream)
            if not isinstance(value, dict) or int(value.get('format_version', 0)) != FORMAT_VERSION:
                raise ValueError('unsupported health-history format')
            if not isinstance(value.get('counters'), dict):
                raise ValueError('health counters are invalid')
            if not isinstance(value.get('observations'), dict):
                raise ValueError('health observations are invalid')
            if not isinstance(value.get('events'), list):
                raise ValueError('health events are invalid')
            base = _empty()
            base['counters'].update(value['counters'])
            base['observations'].update(value['observations'])
            base['events'] = value['events'][-self.max_events:]
            base['updated_at'] = int(value.get('updated_at', 0) or 0)
            return base
        except Exception:
            return _empty()

    def checkpoint(self, force=False):
        if not force and self._dirty_changes < self.checkpoint_changes:
            return False
        self.data['updated_at'] = _now()
        temporary = self.path + '.tmp'
        try:
            with open(temporary, 'w') as stream:
                json.dump(self.data, stream)
            _replace(temporary, self.path)
            self._dirty_changes = 0
            return True
        except Exception:
            try:
                os.remove(temporary)
            except OSError:
                pass
            return False

    def increment(self, name, amount=1, force=False):
        counters = self.data['counters']
        counters[str(name)] = int(counters.get(str(name), 0) or 0) + int(amount)
        self._dirty_changes += 1
        self.checkpoint(force)
        return counters[str(name)]

    def observe(self, name, value, minimum=False, force=False):
        name = str(name)
        observations = self.data['observations']
        if minimum:
            current = observations.get(name)
            if current is not None and value is not None and value >= current:
                return current
        observations[name] = value
        self._dirty_changes += 1
        self.checkpoint(force)
        return value

    def record_event(self, kind, detail='', values=None, force=False):
        event = {
            'time': _now(),
            'kind': str(kind),
            'detail': str(detail)[:192],
        }
        if isinstance(values, dict) and values:
            event['values'] = values
        self.data['events'].append(event)
        self.data['events'] = self.data['events'][-self.max_events:]
        self._dirty_changes += 1
        self.checkpoint(force)
        return event

    def record_boot(self, reset_cause='', startup_exception=''):
        self.increment('boots')
        reset_cause = str(reset_cause or '')
        self.observe('last_reset_cause', reset_cause)
        if 'watchdog' in reset_cause.lower() or reset_cause.lower() in ('wdt', 'wdt_reset'):
            self.increment('watchdog_resets')
        if startup_exception:
            self.observe('last_startup_exception', str(startup_exception)[:256])
            self.record_event('startup_exception', startup_exception)
        self.record_event('boot', reset_cause, force=True)

    def observe_wifi(self, rssi=None, reconnected=False):
        if rssi is not None:
            rssi = int(rssi)
            self.observe('last_wifi_rssi', rssi)
            self.observe('minimum_wifi_rssi', rssi, minimum=True)
        if reconnected:
            self.increment('wifi_reconnects')

    def observe_heap(self, free_bytes):
        if free_bytes is not None:
            self.observe('minimum_free_heap', int(free_bytes), minimum=True)

    def record_update_result(self, kind, result, version='', detail=''):
        value = {
            'time': _now(),
            'kind': str(kind),
            'result': str(result),
            'version': str(version),
            'detail': str(detail)[:160],
        }
        self.observe('last_update_result', value)
        self.record_event('update_' + str(result), detail, value, force=True)
        return value

    def snapshot(self):
        # JSON round-trip provides a small, portable deep copy on MicroPython.
        return json.loads(json.dumps(self.data))

    def clear(self):
        """Reset persistent counters, observations and events on user request."""
        self.data = _empty()
        self._dirty_changes = self.checkpoint_changes
        if not self.checkpoint(force=True):
            raise OSError('health history could not be reset')
        return self.snapshot()
