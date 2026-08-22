"""Structured event facade shared by runtime, API, portal and fleet code."""


class EventService:
    def __init__(self, health):
        self.health = health

    def emit(self, kind, message='', severity='info', component='runtime',
             values=None, correlation_id='', durable=False):
        return self.health.record_event(
            kind, message, values, force=durable, severity=severity,
            component=component, correlation_id=correlation_id
        )

    def page(self, cursor=0, limit=32):
        return self.health.events_since(cursor, limit)

    def snapshot(self):
        return self.health.snapshot()
