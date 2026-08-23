"""Structured event facade shared by runtime, API, portal and fleet code."""


class EventService:
    def __init__(self, health, sinks=None):
        self.health = health
        self._sinks = list(sinks or ())

    def add_sink(self, sink):
        if not callable(sink) and not callable(getattr(sink, 'write', None)):
            raise ValueError('event sink must be callable or expose write(event)')
        self._sinks.append(sink)
        return sink

    def emit(self, kind, message='', severity='info', component='runtime',
             values=None, correlation_id='', durable=False):
        event = self.health.record_event(
            kind, message, values, force=durable, severity=severity,
            component=component, correlation_id=correlation_id
        )
        for sink in tuple(self._sinks):
            try:
                writer = getattr(sink, 'write', None)
                writer(event) if writer else sink(event)
            except Exception:
                pass
        return event

    def page(self, cursor=0, limit=32):
        return self.health.events_since(cursor, limit)

    def snapshot(self):
        return self.health.snapshot()
