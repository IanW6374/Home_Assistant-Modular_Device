"""Update staging boundary shared by portal, release and fleet transports."""


class UpdateService:
    def __init__(self, resumable_store, application_receiver,
                 firmware_receiver, universal_receiver, status_getter):
        self.store = resumable_store
        self.receivers = {
            'application': application_receiver,
            'firmware': firmware_receiver,
            'universal': universal_receiver,
        }
        self._status_getter = status_getter

    def begin(self, request):
        return self.store.begin(
            request.get('id', ''), request.get('kind', ''),
            request.get('total_bytes', 0), request.get('sha256', '')
        )

    def status(self, identifier):
        return self.store.status(identifier)

    def snapshot(self):
        return dict(self._status_getter() or {})

    def receiver(self, kind):
        value = self.receivers.get(str(kind))
        if value is None:
            raise ValueError('update type is invalid')
        return value
