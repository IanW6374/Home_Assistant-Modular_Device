"""Transport-neutral update upload and installer coordination."""


class _ArtifactReader:
    def __init__(self, path):
        self.stream = open(path, 'rb')

    async def read(self, size):
        return self.stream.read(size)

    def close(self):
        self.stream.close()


class UpdateService:
    """Own resumable upload state and dispatch verified artifacts to installers."""

    def __init__(self, resumable_store, receivers=None, status_getter=None,
                 maximum_chunk_bytes=64 * 1024):
        self.store = resumable_store
        self.receivers = {}
        self._status_getter = status_getter
        self.maximum_chunk_bytes = max(1024, int(maximum_chunk_bytes))
        for kind, receiver in (receivers or {}).items():
            if receiver is not None:
                self.register_receiver(kind, receiver)

    def register_receiver(self, kind, receiver):
        kind = str(kind)
        if kind not in ('application', 'firmware', 'universal'):
            raise ValueError('update type is invalid')
        if not callable(receiver):
            raise ValueError('update receiver must be callable')
        self.receivers[kind] = receiver
        return receiver

    def begin(self, request):
        if not isinstance(request, dict):
            raise ValueError('resumable upload request is invalid')
        kind = str(request.get('kind', ''))
        self.receiver(kind)
        return self.store.begin(
            request.get('id', ''), kind,
            request.get('total_bytes', 0), request.get('sha256', '')
        )

    def status(self, identifier):
        return self.store.status(identifier)

    async def append(self, identifier, offset, reader, length):
        length = int(length)
        if length <= 0 or length > self.maximum_chunk_bytes:
            raise ValueError('resumable upload chunk size is invalid')
        payload = bytearray()
        while len(payload) < length:
            chunk = await reader.read(length - len(payload))
            if not chunk:
                raise ValueError('resumable upload chunk ended early')
            payload.extend(chunk)
        return self.store.append(identifier, offset, payload)

    async def complete(self, identifier, progress_callback=None):
        artifact = self.store.complete(identifier)
        reader = _ArtifactReader(artifact['path'])
        try:
            installer = self.receiver(artifact['kind'])
            return await installer(
                reader, artifact['total_bytes'],
                {'_progress': progress_callback}
            )
        finally:
            reader.close()
            self.store.remove(identifier)

    def discard(self, identifier):
        return self.store.remove(identifier)

    def snapshot(self):
        return dict(self._status_getter() or {}) if self._status_getter else {}

    def receiver(self, kind):
        value = self.receivers.get(str(kind))
        if value is None:
            raise ValueError('update type is invalid or disabled')
        return value
