"""Adapters from structured application events to operational outputs."""


class LegacyLogSink:
    """Bridge v2 events to the bounded portal/console/syslog log pipeline."""

    LEVELS = {
        'debug': 'DEBUG', 'info': 'INFO', 'warning': 'INFO',
        'error': 'ERROR', 'critical': 'ERROR',
    }

    def __init__(self, logger):
        self.logger = logger

    def write(self, event):
        event = event or {}
        component = str(event.get('component') or 'runtime')
        kind = str(event.get('kind') or 'event')
        message = str(event.get('message') or event.get('detail') or '')
        self.logger(
            'Local', component + ' ' + kind,
            {'log': message or kind},
            self.LEVELS.get(str(event.get('severity') or 'info').lower(), 'INFO')
        )
