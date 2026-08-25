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

try:
    import ubinascii as binascii
except ImportError:
    import binascii


FORMAT_VERSION = 1
ALLOWED_KINDS = ('application', 'firmware', 'universal')
MAX_CHUNK_BYTES = 64 * 1024
DEFAULT_STORAGE_RESERVE_BYTES = 96 * 1024


def _hex_digest(hasher):
    return binascii.hexlify(hasher.digest()).decode()


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
                 maximum_sessions=2,
                 storage_reserve_bytes=DEFAULT_STORAGE_RESERVE_BYTES,
                 storage_reclaimer=None):
        self.directory = str(directory).rstrip('/')
        self.maximum_bytes = max(1, int(maximum_bytes))
        self.maximum_sessions = max(1, int(maximum_sessions))
        self.storage_reserve_bytes = max(0, int(storage_reserve_bytes))
        self.storage_reclaimer = storage_reclaimer
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

    def _discard_other_sessions(self, identifier):
        """Keep one resumable artifact and reclaim abandoned upload storage."""
        try:
            names = os.listdir(self.directory)
        except OSError:
            return
        suffixes = ('.json.tmp', '.part.reconcile', '.json', '.part')
        for name in names:
            for suffix in suffixes:
                if name.endswith(suffix):
                    session = name[:-len(suffix)]
                    if session and session != identifier:
                        try:
                            os.remove(self.directory + '/' + name)
                        except OSError:
                            pass
                    break

    def _require_upload_space(self, required):
        required = max(0, int(required)) + self.storage_reserve_bytes
        try:
            values = os.statvfs(self.directory)
            free = int(values[0]) * int(values[4])
        except Exception:
            return
        if free < required:
            raise ValueError(
                'insufficient storage for resumable upload: need ' +
                str(required) + ' bytes, have ' + str(free)
            )

    def _ensure_upload_space(self, required, kind):
        try:
            self._require_upload_space(required)
        except ValueError:
            if not self.storage_reclaimer or not self.storage_reclaimer(
                str(kind), int(required)
            ):
                raise
            self._require_upload_space(required)

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
                self._discard_other_sessions(identifier)
                try:
                    self._ensure_upload_space(
                        total_bytes - int(current.get('received_bytes', 0)),
                        kind
                    )
                except ValueError:
                    # A partial artifact that cannot accept its remaining
                    # bytes is not resumable in practice. Reclaim it and
                    # evaluate a clean restart instead of wedging the device.
                    self.remove(identifier)
                    existing.remove(identifier)
                else:
                    return self.status(identifier)
            else:
                self.remove(identifier)
                existing.remove(identifier)
        # A device can only install one update at a time. Selecting a different
        # artifact is therefore an explicit replacement of any interrupted
        # upload, and must reclaim its payload before accepting new bytes.
        self._discard_other_sessions(identifier)
        existing = self._session_names()
        if identifier not in existing and len(existing) >= self.maximum_sessions:
            raise ValueError('too many update uploads are active')
        self._ensure_upload_space(total_bytes, kind)
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
        actual = _hex_digest(digest)
        if actual != value['sha256']:
            raise ValueError('upload SHA-256 verification failed')
        value['complete'] = True
        self._write_metadata(value)
        result = self.status(identifier)
        result['path'] = value['_payload_path']
        return result

    def handoff(self, identifier):
        """Release resumable metadata before an installer mutates the artifact."""
        value = self._load(identifier)
        if not value.get('complete'):
            raise ValueError('upload is not complete')
        try:
            os.remove(value['_metadata_path'])
        except OSError:
            pass
        return value['_payload_path']

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
