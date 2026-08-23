"""Explicit application startup and shutdown state machine."""


STARTUP_STATES = (
    'created', 'starting', 'network-ready', 'portal-ready',
    'services-ready', 'running'
)


class LifecycleError(RuntimeError):
    pass


class ApplicationLifecycle:
    """Record ordered startup phases without depending on a transport."""

    def __init__(self, state, event_service=None):
        self.state = state
        self.events = event_service
        self._position = 0
        self.state.set('lifecycle', STARTUP_STATES[0])

    def transition(self, target, detail=''):
        target = str(target)
        if target == 'failed':
            self.state.update({'lifecycle': 'failed', 'lifecycle_error': str(detail)})
            self._emit('startup_failed', detail, 'error', True)
            return target
        if target == 'stopping':
            self.state.set('lifecycle', target)
            self._emit('application_stopping', detail)
            return target
        try:
            position = STARTUP_STATES.index(target)
        except ValueError:
            raise LifecycleError('unknown application lifecycle state: ' + target)
        if position != self._position + 1:
            raise LifecycleError(
                'invalid application lifecycle transition: ' +
                STARTUP_STATES[self._position] + ' -> ' + target
            )
        self._position = position
        self.state.update({'lifecycle': target, 'lifecycle_error': ''})
        self._emit('startup_phase', target, 'debug')
        return target

    def snapshot(self):
        return {
            'state': self.state.get('lifecycle', STARTUP_STATES[0]),
            'error': self.state.get('lifecycle_error', ''),
        }

    def _emit(self, kind, detail, severity='info', durable=False):
        if self.events is None:
            return
        try:
            self.events.emit(
                kind, str(detail), severity=severity, component='lifecycle',
                durable=durable
            )
        except Exception:
            pass
