"""Power-safe, bounded resumable upload storage for v2 update bundles."""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib


FORMAT_VERSION = 1
ALLOWED_KINDS = ('application', 'firmware', 'universal')
MAX_CHUNK_BYTES = 64 * 1024


def _safe_identifier(value):
    value = str(value)
    if (
        not 8 <= len(value) <= 64 or
        any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'
            for character in value)
    ):
        raise ValueError('upload session identifier is invalid')
    return value


def _mkdir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass


class ResumableUploadStore:
    def __init__(self, directory='.update-uploads', maximum_bytes=7 * 1024 * 1024,
                 maximum_sessions=2):
        self.directory = str(directory).rstrip('/')
        self.maximum_bytes = max(1, int(maximum_bytes))
        self.maximum_sessions = max(1, int(maximum_sessions))
        _mkdir(self.directory)

    def _paths(self, identifier):
        identifier = _safe_identifier(identifier)
        root = self.directory + '/' + identifier
        return root + '.json', root + '.part'

    def _load(self, identifier):
        metadata_path, payload_path = self._paths(identifier)
        try:
            with open(metadata_path, 'r') as stream:
                value = json.load(stream)
        except OSError:
            raise ValueError('upload session does not exist')
        if not isinstance(value, dict) or value.get('format_version') != FORMAT_VERSION:
            raise ValueError('upload session metadata is invalid')
        value['_metadata_path'] = metadata_path
        value['_payload_path'] = payload_path
        self._reconcile_payload(value)
        return value

    def _reconcile_payload(self, value):
        """Discard bytes written after the last committed metadata offset."""
        expected = int(value.get('received_bytes', 0))
        try:
            actual = int(os.stat(value['_payload_path'])[6])
        except OSError:
            raise ValueError('upload session payload is missing')
        if actual < expected:
            raise ValueError('upload session payload is incomplete')
        if actual == expected:
            return
        try:
            with open(value['_payload_path'], 'r+b') as stream:
                stream.truncate(expected)
            return
        except (AttributeError, OSError):
            pass
        source_path = value['_payload_path']
        temporary = source_path + '.reconcile'
        remaining = expected
        with open(source_path, 'rb') as source, open(temporary, 'wb') as target:
            while remaining:
                chunk = source.read(min(4096, remaining))
                if not chunk:
                    raise ValueError('upload session payload is incomplete')
                target.write(chunk)
                remaining -= len(chunk)
        try:
            os.remove(source_path)
        except OSError:
            pass
        os.rename(temporary, source_path)

    def _write_metadata(self, value):
        path = value['_metadata_path']
        temporary = path + '.tmp'
        saved = {key: item for key, item in value.items() if not key.startswith('_')}
        with open(temporary, 'w') as stream:
            json.dump(saved, stream)
        try:
            os.remove(path)
        except OSError:
            pass
        os.rename(temporary, path)

    def _session_names(self):
        try:
            return sorted(
                name[:-5] for name in os.listdir(self.directory)
                if name.endswith('.json') and not name.startswith('.')
            )
        except OSError:
            return []

    def begin(self, identifier, kind, total_bytes, sha256):
        identifier = _safe_identifier(identifier)
        kind = str(kind)
        if kind not in ALLOWED_KINDS:
            raise ValueError('upload kind is invalid')
        total_bytes = int(total_bytes)
        if total_bytes <= 0 or total_bytes > self.maximum_bytes:
            raise ValueError('upload size is outside the supported range')
        sha256 = str(sha256).lower()
        if len(sha256) != 64 or any(
            character not in '0123456789abcdef' for character in sha256
        ):
            raise ValueError('upload SHA-256 is invalid')
        existing = self._session_names()
        if identifier in existing:
            current = self._load(identifier)
            if (
                current.get('kind') == kind and
                int(current.get('total_bytes', 0)) == total_bytes and
                current.get('sha256') == sha256
            ):
                return self.status(identifier)
            self.remove(identifier)
            existing.remove(identifier)
        if identifier not in existing and len(existing) >= self.maximum_sessions:
            raise ValueError('too many update uploads are active')
        metadata_path, payload_path = self._paths(identifier)
        value = {
            'format_version': FORMAT_VERSION,
            'id': identifier,
            'kind': kind,
            'total_bytes': total_bytes,
            'sha256': sha256,
            'received_bytes': 0,
            'complete': False,
            '_metadata_path': metadata_path,
            '_payload_path': payload_path,
        }
        with open(payload_path, 'wb'):
            pass
        self._write_metadata(value)
        return self.status(identifier)

    def append(self, identifier, offset, payload):
        value = self._load(identifier)
        if value.get('complete'):
            raise ValueError('upload session is already complete')
        payload = bytes(payload)
        if not payload or len(payload) > MAX_CHUNK_BYTES:
            raise ValueError('upload chunk size is invalid')
        offset = int(offset)
        received = int(value.get('received_bytes', 0))
        if offset != received:
            raise ValueError('upload chunk offset does not match received bytes')
        if received + len(payload) > int(value['total_bytes']):
            raise ValueError('upload chunk exceeds declared size')
        with open(value['_payload_path'], 'ab') as stream:
            stream.write(payload)
        value['received_bytes'] = received + len(payload)
        self._write_metadata(value)
        return self.status(identifier)

    def complete(self, identifier):
        value = self._load(identifier)
        if int(value.get('received_bytes', 0)) != int(value['total_bytes']):
            raise ValueError('upload is incomplete')
        digest = hashlib.sha256()
        with open(value['_payload_path'], 'rb') as stream:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != value['sha256']:
            raise ValueError('upload SHA-256 verification failed')
        value['complete'] = True
        self._write_metadata(value)
        result = self.status(identifier)
        result['path'] = value['_payload_path']
        return result

    def status(self, identifier):
        value = self._load(identifier)
        received = int(value.get('received_bytes', 0))
        total = int(value.get('total_bytes', 0))
        return {
            'id': value['id'], 'kind': value['kind'],
            'received_bytes': received, 'total_bytes': total,
            'percent': int(received * 100 / total) if total else 0,
            'complete': bool(value.get('complete')),
        }

    def remove(self, identifier):
        metadata_path, payload_path = self._paths(identifier)
        removed = False
        for path in (metadata_path, payload_path):
            try:
                os.remove(path)
                removed = True
            except OSError:
                pass
        return removed
