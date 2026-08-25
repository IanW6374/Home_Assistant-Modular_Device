"""Transport-neutral update upload and installer coordination."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii


class _ArtifactReader:
    def __init__(self, path):
        self.path = str(path)
        self.stream = open(self.path, 'rb')

    async def read(self, size):
        return self.stream.read(size)

    async def compact_remaining(self, length, progress_callback=None):
        """Move the unread tail to byte zero with bounded LittleFS free space."""
        length = int(length)
        source_offset = int(self.stream.tell())
        self.stream.close()
        self.stream = None
        moved = 0
        with open(self.path, 'r+b') as stream:
            if source_offset >= length:
                # The universal core prefix is larger than the application
                # tail. Copy from the end and truncate each released source
                # block immediately. LittleFS is copy-on-write, so postponing
                # the truncate until the end can exhaust its free blocks even
                # though the operation has no logical storage growth.
                remaining = length
                while remaining:
                    size = min(4096, remaining)
                    start = remaining - size
                    stream.seek(source_offset + start)
                    chunk = stream.read(size)
                    if len(chunk) != size:
                        raise ValueError('update artifact tail ended early')
                    stream.seek(start)
                    stream.write(chunk)
                    stream.truncate(source_offset + start)
                    remaining = start
                    moved += size
                    if progress_callback:
                        result = progress_callback('compacting', moved, length)
                        if result is not None:
                            await result
                    await asyncio.sleep(0)
            else:
                # Retain memmove-safe forward copying for overlapping ranges.
                while moved < length:
                    stream.seek(source_offset + moved)
                    chunk = stream.read(min(
                        4096, max(1, source_offset), length - moved
                    ))
                    if not chunk:
                        raise ValueError('update artifact tail ended early')
                    stream.seek(moved)
                    stream.write(chunk)
                    moved += len(chunk)
                    if progress_callback:
                        result = progress_callback('compacting', moved, length)
                        if result is not None:
                            await result
                    await asyncio.sleep(0)
            stream.truncate(length)
            stream.seek(0)
            digest = hashlib.sha256()
            remaining = length
            while remaining:
                chunk = stream.read(min(4096, remaining))
                if not chunk:
                    raise ValueError('compacted update artifact ended early')
                digest.update(chunk)
                remaining -= len(chunk)
        return {
            'path': self.path,
            'size': moved,
            'sha256': binascii.hexlify(digest.digest()).decode(),
        }

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class UpdateService:
    """Own resumable upload state and dispatch verified artifacts to installers."""

    def __init__(self, resumable_store, receivers=None, status_getter=None,
                 maximum_chunk_bytes=64 * 1024):
        self.store = resumable_store
        self.receivers = {}
        self._status_getter = status_getter
        self._installing = False
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
        if self._installing:
            raise ValueError('another update is already being installed')
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
        if self._installing:
            raise ValueError('another update is already being installed')
        self._installing = True
        reader = None
        try:
            artifact = self.store.complete(identifier)
            handoff = getattr(self.store, 'handoff', None)
            if handoff:
                handoff(identifier)
            reader = _ArtifactReader(artifact['path'])
            installer = self.receiver(artifact['kind'])
            return await installer(
                reader, artifact['total_bytes'],
                {'_progress': progress_callback}
            )
        finally:
            if reader is not None:
                reader.close()
            self.store.remove(identifier)
            self._installing = False

    def discard(self, identifier):
        if self._installing:
            raise ValueError('another update is already being installed')
        return self.store.remove(identifier)

    def snapshot(self):
        return dict(self._status_getter() or {}) if self._status_getter else {}

    def receiver(self, kind):
        value = self.receivers.get(str(kind))
        if value is None:
            raise ValueError('update type is invalid or disabled')
        return value
