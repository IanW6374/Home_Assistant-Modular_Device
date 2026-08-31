"""Explicit runtime context and supervised background-task ownership."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import time
except ImportError:
    time = None

from .lifecycle import ApplicationLifecycle


def _monotonic_ms():
    if time is None:
        return 0
    try:
        ticks = getattr(time, 'ticks_ms', None)
        if ticks:
            return int(ticks())
        monotonic = getattr(time, 'monotonic', None)
        if monotonic:
            return int(monotonic() * 1000)
        return int(time.time() * 1000)
    except Exception:
        return 0


class RuntimeState:
    """Small mutable state boundary with snapshot isolation for transports."""

    def __init__(self, initial=None):
        self._values = dict(initial or {})

    def get(self, name, default=None):
        return self._values.get(str(name), default)

    def set(self, name, value):
        self._values[str(name)] = value
        return value

    def update(self, values):
        if not isinstance(values, dict):
            raise ValueError('runtime state update must be an object')
        self._values.update(values)
        return self.snapshot()

    def snapshot(self):
        return dict(self._values)


class TaskSupervisor:
    """Own application tasks and report failures through one event boundary."""

    def __init__(self, event_service=None, critical_failure=None,
                 task_factory=None, clock=None):
        self.event_service = event_service
        self.critical_failure = critical_failure
        self.task_factory = task_factory or asyncio.create_task
        self.clock = clock or _monotonic_ms
        self._tasks = {}
        self._states = {}

    def _transition(self, name, status, **values):
        previous = self._states.get(name, {})
        state = dict(previous)
        state.update({
            'status': status,
            'state': status,
            'error': values.pop('error', ''),
        })
        state.update(values)
        self._states[name] = state
        return state

    def start(self, name, coroutine, critical=False):
        name = str(name)
        if not name:
            raise ValueError('task name is required')
        existing = self._tasks.get(name)
        if existing is not None and not getattr(existing, 'done', lambda: True)():
            raise RuntimeError('task is already running: ' + name)

        previous = self._states.get(name, {})
        self._states[name] = {
            'status': 'starting',
            'state': 'starting',
            'error': '',
            'last_error': previous.get('last_error', ''),
            'failure_count': int(previous.get('failure_count', 0) or 0),
            'start_count': int(previous.get('start_count', 0) or 0) + 1,
            'started_ms': int(self.clock()),
            'last_success_ms': int(previous.get('last_success_ms', 0) or 0),
            'stopped_ms': 0,
            'critical': bool(critical),
        }

        async def runner():
            self._transition(name, 'running')
            self._emit('task_started', name, 'debug')
            try:
                await coroutine
            except asyncio.CancelledError:
                self._transition(
                    name, 'cancelled', stopped_ms=int(self.clock())
                )
                self._emit('task_cancelled', name, 'debug')
                raise
            except Exception as exc:
                detail = str(exc) or exc.__class__.__name__
                self._transition(
                    name, 'failed', error=detail, last_error=detail,
                    failure_count=int(
                        self._states[name].get('failure_count', 0) or 0
                    ) + 1,
                    stopped_ms=int(self.clock())
                )
                self._emit('task_failed', name + ': ' + detail, 'error', True)
                if critical and self.critical_failure:
                    self.critical_failure(name, exc)
            else:
                now = int(self.clock())
                self._transition(
                    name, 'complete', last_success_ms=now, stopped_ms=now
                )
                self._emit('task_completed', name, 'debug')
            finally:
                self._tasks.pop(name, None)

        task = self.task_factory(runner())
        self._tasks[name] = task
        return task

    def status(self, name=None):
        if name is not None:
            return dict(self._states.get(str(name), {
                'status': 'unknown', 'error': ''
            }))
        return {key: dict(value) for key, value in self._states.items()}

    def cancel(self, name):
        task = self._tasks.get(str(name))
        if task is None:
            return False
        task.cancel()
        return True

    def heartbeat(self, name):
        """Record progress from a managed long-running task."""
        name = str(name)
        if name not in self._states:
            return False
        self._transition(name, 'running', last_success_ms=int(self.clock()))
        return True

    def degrade(self, name, error):
        """Expose a recoverable service failure without ending its task."""
        name = str(name)
        if name not in self._states:
            return False
        detail = str(error) or 'degraded'
        self._transition(
            name, 'degraded', error=detail, last_error=detail,
            failure_count=int(
                self._states[name].get('failure_count', 0) or 0
            ) + 1
        )
        self._emit('task_degraded', name + ': ' + detail, 'warning')
        return True

    def _emit(self, kind, detail, severity='info', durable=False):
        if self.event_service is None:
            return
        try:
            self.event_service.emit(
                kind, detail, severity=severity, component='task',
                durable=durable
            )
        except Exception:
            pass


class ApplicationContext:
    """Single explicit registry for runtime services and mutable state."""

    def __init__(self, identity, configuration=None, state=None,
                 event_service=None, critical_failure=None):
        if not isinstance(identity, dict) or not identity.get('device_id'):
            raise ValueError('application identity requires device_id')
        self.identity = dict(identity)
        self.configuration = configuration
        self.state = state or RuntimeState()
        self.events = event_service
        self.tasks = TaskSupervisor(event_service, critical_failure)
        self.lifecycle = ApplicationLifecycle(self.state, event_service)
        self._services = {}
        self._sealed = False

    def register(self, name, service):
        name = str(name)
        if self._sealed:
            raise RuntimeError('application context is sealed')
        if not name or service is None:
            raise ValueError('service name and implementation are required')
        if name in self._services:
            raise ValueError('service is already registered: ' + name)
        self._services[name] = service
        return service

    def service(self, name):
        try:
            return self._services[str(name)]
        except KeyError:
            raise RuntimeError('required service is unavailable: ' + str(name))

    def optional(self, name, default=None):
        return self._services.get(str(name), default)

    def seal(self, required=()):
        missing = [name for name in required if str(name) not in self._services]
        if missing:
            raise RuntimeError('missing application services: ' + ', '.join(missing))
        self._sealed = True
        return self

    def inventory(self):
        return {
            'identity': dict(self.identity),
            'services': sorted(self._services),
            'state': self.state.snapshot(),
            'lifecycle': self.lifecycle.snapshot(),
            'tasks': self.tasks.status(),
        }
