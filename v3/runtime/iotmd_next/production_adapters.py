"""Production bridges from v3 services to the qualified device transports.

The bridges own lifecycle/retry state but receive concrete sockets, listeners
and clients from the composition root.  This keeps v3 services independent of
the v2 compatibility implementation while allowing shadow-mode parity tests.
"""


def _callable(value, name):
    if not callable(value):
        raise ValueError(name + ' is unavailable')
    return value


class AsyncOperationTracker:
    """Schedule awaitables without leaking unbounded task references."""

    def __init__(self, scheduler, maximum=8):
        self._scheduler = _callable(scheduler, 'task scheduler')
        self._maximum = max(1, min(16, int(maximum)))
        self._pending = 0
        self._completed = 0
        self._failures = 0
        self._last_error = ''

    async def _run(self, operation):
        try:
            await operation
            self._completed += 1
        except Exception as exc:
            self._failures += 1
            self._last_error = str(getattr(type(exc), '__name__', 'error'))[:48]
        finally:
            self._pending -= 1

    def submit(self, result):
        if not hasattr(result, '__await__'):
            self._completed += 1
            return result
        if self._pending >= self._maximum:
            raise RuntimeError('production adapter operation limit reached')
        self._pending += 1
        return self._scheduler(self._run(result))

    def status(self):
        return {
            'pending': self._pending, 'completed': self._completed,
            'failures': self._failures, 'last_error': self._last_error,
        }


class ProductionWiFiAdapter:
    """Own station activation and bounded reconnect scheduling."""

    def __init__(self, station, settings, configure, connector, tracker,
                 now_ms, reconnect_ms=5000):
        for operation in ('active', 'isconnected', 'disconnect'):
            if not callable(getattr(station, operation, None)):
                raise ValueError('Wi-Fi station is incomplete')
        self._station = station
        self._settings = dict(settings)
        self._configure = _callable(configure, 'Wi-Fi configurator')
        self._connector = _callable(connector, 'Wi-Fi connector')
        self._tracker = tracker
        self._now_ms = _callable(now_ms, 'monotonic clock')
        self._reconnect_ms = max(1000, min(60000, int(reconnect_ms)))
        self._running = False
        self._next_attempt = 0
        self._attempts = 0

    def _connect(self):
        self._attempts += 1
        self._next_attempt = int(self._now_ms()) + self._reconnect_ms
        self._tracker.submit(self._connector(dict(self._settings)))

    def start(self):
        self._configure(self._station, dict(self._settings))
        self._station.active(True)
        self._running = True
        if not self._station.isconnected():
            self._connect()

    def stop(self):
        self._running = False
        self._station.disconnect()
        self._station.active(False)

    def poll(self):
        if (self._running and not self._station.isconnected() and
                int(self._now_ms()) >= self._next_attempt and
                self._tracker.status()['pending'] == 0):
            self._connect()

    def status(self):
        address = ''
        if self._station.isconnected():
            try:
                address = str(self._station.ifconfig()[0])[:48]
            except Exception:
                pass
        tasks = self._tracker.status()
        return {
            'state': 'online' if self._station.isconnected() else
                ('connecting' if self._running else 'offline'),
            'address': address, 'attempts': self._attempts,
            'failures': tasks['failures'], 'last_error': tasks['last_error'],
        }


class ProductionMQTTAdapter:
    """Adapt the asynchronous production MQTT client to v3 lifecycle calls."""

    def __init__(self, client, tracker, status_getter=None):
        for operation in ('connect', 'disconnect', 'publish'):
            if not callable(getattr(client, operation, None)):
                raise ValueError('MQTT client is incomplete')
        self._client = client
        self._tracker = tracker
        self._status_getter = status_getter
        self._running = False
        self._published = 0

    def connect(self):
        self._running = True
        self._tracker.submit(self._client.connect())

    def disconnect(self):
        self._running = False
        self._tracker.submit(self._client.disconnect())

    def publish(self, topic, payload, retain, qos):
        self._tracker.submit(self._client.publish(
            topic, payload, retain=bool(retain), qos=int(qos)
        ))
        self._published += 1

    def poll(self):
        return None

    def status(self):
        state = 'online' if self._running else 'offline'
        if self._status_getter is not None:
            value = self._status_getter()
            state = str(value.get('state', state) if isinstance(value, dict)
                        else value)[:32]
        tasks = self._tracker.status()
        return {
            'state': state, 'published': self._published,
            'pending': tasks['pending'], 'failures': tasks['failures'],
            'last_error': tasks['last_error'],
        }


class ProductionListenerAdapter:
    """Lifecycle bridge for the HTTPS portal and mTLS API listeners."""

    def __init__(self, starter, stopper, tracker):
        self._starter = _callable(starter, 'listener starter')
        self._stopper = _callable(stopper, 'listener stopper')
        self._tracker = tracker
        self._listener = None
        self._starting = False
        self._mtls = False

    async def _start(self, handler, require_mtls):
        try:
            result = self._starter(
                handler, require_mtls=bool(require_mtls)
            )
            self._listener = (
                await result if hasattr(result, '__await__') else result
            )
        finally:
            self._starting = False

    def start(self, handler, require_mtls=False):
        self._mtls = bool(require_mtls)
        self._starting = True
        self._tracker.submit(self._start(handler, self._mtls))

    async def _stop(self):
        try:
            result = self._stopper(self._listener)
            if hasattr(result, '__await__'):
                await result
        finally:
            self._listener = None
            self._starting = False

    def stop(self):
        self._tracker.submit(self._stop())

    def poll(self):
        return None

    def status(self):
        tasks = self._tracker.status()
        return {
            'state': 'online' if self._listener is not None else
                ('starting' if self._starting else 'offline'),
            'mtls': self._mtls, 'pending': tasks['pending'],
            'failures': tasks['failures'], 'last_error': tasks['last_error'],
        }


class ProductionSyslogAdapter:
    def __init__(self, remote, tracker):
        for operation in ('enqueue', 'run', 'status'):
            if not callable(getattr(remote, operation, None)):
                raise ValueError('syslog transport is incomplete')
        self._remote = remote
        self._tracker = tracker
        self._running = False
        self._task = None

    def start(self):
        self._running = True
        if getattr(self._remote, 'active', True):
            self._task = self._tracker.submit(self._remote.run())

    def stop(self):
        self._running = False
        if self._task is not None and callable(getattr(self._task, 'cancel', None)):
            self._task.cancel()
        self._task = None

    def poll(self):
        return None

    def emit(self, timestamp, message, severity, audit):
        return bool(self._remote.enqueue(timestamp, message, severity, audit))

    def status(self):
        value = self._remote.status()
        return {
            'state': 'online' if self._running and not value.get('last_error')
                else ('error' if value.get('last_error') else 'offline'),
            'queued': int(value.get('queued', 0)),
            'delivered': int(value.get('delivered', 0)),
            'failures': int(value.get('failures', 0)),
        }


def build_production_adapters(wifi, mqtt, portal, device_api, syslog):
    """Validate and return the five adapters expected by v3 configuration."""
    result = {
        'wifi': wifi, 'mqtt': mqtt, 'portal': portal,
        'device-api': device_api, 'syslog': syslog,
    }
    for name, adapter in result.items():
        if adapter is None:
            raise ValueError('production ' + name + ' adapter is unavailable')
    return result
