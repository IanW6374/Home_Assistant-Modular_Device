"""mTLS client certificate enrolment and scope enforcement."""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import uos as os
except ImportError:
    import os

import certificate_manager


FORMAT_VERSION = 2
ALLOWED_SCOPES = ('read', 'write', 'fleet:read', 'fleet:write')


def certificate_fingerprint(certificate_der):
    if not isinstance(certificate_der, (bytes, bytearray)) or not certificate_der:
        raise ValueError('client certificate must be non-empty DER')
    return binascii.hexlify(hashlib.sha256(bytes(certificate_der)).digest()).decode()


class CATrustStore:
    """Small directory-backed collection of independent API issuing CAs."""
    def __init__(self, directory='certs/trust/api-clients', maximum=8,
                 legacy_path=''):
        self.directory = str(directory).rstrip('/')
        self.maximum = max(1, int(maximum))
        self.legacy_path = str(legacy_path or '')

    def _mkdir(self):
        current = '/' if self.directory.startswith('/') else ''
        for part in (item for item in self.directory.split('/') if item):
            current = current.rstrip('/') + '/' + part if current else part
            try:
                os.mkdir(current)
            except OSError:
                pass

    def paths(self):
        paths = []
        if self.legacy_path:
            try:
                if os.stat(self.legacy_path)[6] > 0:
                    paths.append(self.legacy_path)
            except OSError:
                pass
        try:
            names = sorted(os.listdir(self.directory))
        except OSError:
            names = []
        for name in names:
            if name.endswith('.der') and not name.startswith('.'):
                paths.append(self.directory + '/' + name)
        return paths

    def list(self):
        result = []
        for path in self.paths():
            details = certificate_manager.certificate_lifecycle(path)
            details['path'] = path
            try:
                with open(path, 'rb') as stream:
                    details['fingerprint'] = certificate_fingerprint(stream.read())
            except Exception:
                details['fingerprint'] = ''
            result.append(details)
        return result

    def add(self, certificate_der):
        certificate_der = bytes(certificate_der)
        details = certificate_manager.decode_certificate(certificate_der)
        fingerprint = certificate_fingerprint(certificate_der)
        existing = self.paths()
        for path in existing:
            try:
                with open(path, 'rb') as stream:
                    if certificate_fingerprint(stream.read()) == fingerprint:
                        result = dict(details)
                        result.update({'fingerprint': fingerprint, 'path': path})
                        return result
            except Exception:
                pass
        if len(existing) >= self.maximum:
            raise ValueError('API client CA trust store is full')
        self._mkdir()
        path = self.directory + '/' + fingerprint[:24] + '.der'
        temporary = path + '.tmp'
        with open(temporary, 'wb') as stream:
            stream.write(certificate_der)
        try:
            os.remove(path)
        except OSError:
            pass
        os.rename(temporary, path)
        result = dict(details)
        result.update({'fingerprint': fingerprint, 'path': path})
        return result

    def revoke(self, fingerprint):
        fingerprint = str(fingerprint or '').lower()
        for item in self.list():
            if str(item.get('fingerprint', '')).lower() != fingerprint:
                continue
            if item.get('path') == self.legacy_path:
                raise ValueError('migrate the legacy API CA before removing it')
            os.remove(item['path'])
            return True
        return False


class ClientRegistry:
    def __init__(self, path='certs/api-clients.json', maximum=16):
        self.path = str(path)
        self.maximum = max(1, int(maximum))
        self._cache = None

    def _load(self):
        if self._cache is not None:
            return self._cache
        try:
            with open(self.path, 'r') as stream:
                value = json.load(stream)
            if not isinstance(value, dict) or value.get('format_version') != FORMAT_VERSION:
                raise ValueError('API client registry has an invalid format')
            clients = value.get('clients')
            if not isinstance(clients, list):
                raise ValueError('API client registry is invalid')
            self._cache = value
            return self._cache
        except OSError:
            self._cache = {'format_version': FORMAT_VERSION, 'clients': []}
            return self._cache

    def _save(self, value):
        directory = self.path.rsplit('/', 1)[0] if '/' in self.path else ''
        if directory:
            current = '/' if directory.startswith('/') else ''
            for part in (item for item in directory.split('/') if item):
                current = (
                    current.rstrip('/') + '/' + part
                    if current else part
                )
                try:
                    os.mkdir(current)
                except OSError:
                    pass
        temporary = self.path + '.tmp'
        with open(temporary, 'w') as stream:
            json.dump(value, stream)
        try:
            os.remove(self.path)
        except OSError:
            pass
        os.rename(temporary, self.path)
        self._cache = value

    def list_clients(self):
        result = []
        for client in self._load()['clients']:
            item = dict(client)
            item.update(certificate_manager.certificate_expiry_status(
                item.get('not_after', '')
            ))
            result.append(item)
        return result

    def enrol(self, certificate_der, label='', scopes=('read',)):
        details = certificate_manager.decode_certificate(bytes(certificate_der))
        fingerprint = certificate_fingerprint(certificate_der)
        scopes = sorted(set(str(scope) for scope in scopes))
        if not scopes or any(scope not in ALLOWED_SCOPES for scope in scopes):
            raise ValueError(
                'API client scopes must contain read, write, fleet:read and/or fleet:write'
            )
        label = str(label or details.get('subject') or fingerprint[:12])[:64]
        value = self._load()
        clients = value['clients']
        existing = next(
            (item for item in clients if item.get('fingerprint') == fingerprint),
            None
        )
        record = {
            'fingerprint': fingerprint,
            'label': label,
            'scopes': scopes,
            'subject': details.get('subject', ''),
            'issuer': details.get('issuer', ''),
            'not_after': details.get('not_after', ''),
        }
        if existing:
            clients[clients.index(existing)] = record
        else:
            if len(clients) >= self.maximum:
                raise ValueError('API client registry is full')
            clients.append(record)
        self._save(value)
        return dict(record)

    def revoke(self, fingerprint):
        fingerprint = str(fingerprint).lower()
        value = self._load()
        retained = [
            item for item in value['clients']
            if str(item.get('fingerprint', '')).lower() != fingerprint
        ]
        if len(retained) == len(value['clients']):
            return False
        value['clients'] = retained
        self._save(value)
        return True

    def authenticate(self, certificate_der, required_scope='read'):
        fingerprint = certificate_fingerprint(certificate_der)
        client = next(
            (item for item in self._load()['clients']
             if str(item.get('fingerprint', '')).lower() == fingerprint.lower()),
            None
        )
        if client is None:
            raise PermissionError('client certificate is not enrolled')
        if required_scope not in client.get('scopes', ()):
            raise PermissionError('client certificate does not have ' + required_scope + ' scope')
        return dict(client)
