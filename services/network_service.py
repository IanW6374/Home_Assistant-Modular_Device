"""Network lifecycle boundary used by the v2 composition root."""


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
