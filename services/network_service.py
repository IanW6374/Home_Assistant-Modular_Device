"""Network lifecycle boundary used by the v2 composition root."""


STARTUP_WIFI_ATTEMPTS = 3
STARTUP_WIFI_TIMEOUT_S = 20
STARTUP_WIFI_BACKOFF_S = (2, 5)


async def connect_with_retries(connector, sleeper, quick=True,
                               attempts=STARTUP_WIFI_ATTEMPTS,
                               backoff=STARTUP_WIFI_BACKOFF_S,
                               on_retry=None):
    """Retry a bounded startup connection before escalating to recovery."""
    attempts = max(1, int(attempts))
    last_error = None
    for index in range(attempts):
        try:
            await connector(quick=quick)
            return index + 1
        except (OSError, ValueError) as exc:
            last_error = exc
            completed = index + 1
            if completed >= attempts:
                raise
            delay = int(backoff[min(index, len(backoff) - 1)]) if backoff else 0
            if on_retry:
                on_retry(completed, attempts, delay, exc)
            if delay > 0:
                await sleeper(delay)
    raise last_error


class NetworkService:
    def __init__(self, status_getter, scan_getter, trial_confirmer=None):
        self._status_getter = status_getter
        self._scan_getter = scan_getter
        self._trial_confirmer = trial_confirmer

    def status(self):
        return dict(self._status_getter() or {})

    def visible_networks(self):
        return list(self._scan_getter() or ())

    def confirm_trial(self):
        return bool(self._trial_confirmer()) if self._trial_confirmer else False
