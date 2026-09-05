"""Production certificate/trust bridge with opaque persistent handles."""

try:
    import ujson as json
except ImportError:
    import json

from .configuration import IDENTITY_METHODS


class OpaqueHandleRegistry:
    """Map internal credential locators to stable integers in encrypted NVS.

    Locators are never returned through the v3 identity contract.  The native
    transactional namespace provides generation-safe replacement while the
    compatibility TLS implementation continues to consume internal paths.
    """

    def __init__(self, namespace, maximum=32):
        self._namespace = namespace
        self._maximum = max(2, min(64, int(maximum)))

    def _load(self):
        generation, payload = self._namespace.snapshot()
        if not payload:
            return generation, {'next': 1, 'items': {}}
        value = json.loads(payload.decode())
        if (not isinstance(value, dict) or set(value) != {'next', 'items'} or
                not isinstance(value['next'], int) or value['next'] < 1 or
                not isinstance(value['items'], dict) or
                len(value['items']) > self._maximum):
            raise ValueError('opaque credential registry is invalid')
        for locator, handle in value['items'].items():
            if (not isinstance(locator, str) or not locator or len(locator) > 160 or
                    not isinstance(handle, int) or isinstance(handle, bool) or
                    handle < 1):
                raise ValueError('opaque credential registry is invalid')
        return generation, value

    def resolve(self, kind, locator):
        kind = str(kind)
        locator = str(locator)
        if kind not in ('certificate', 'key') or not locator:
            raise ValueError('credential locator is invalid')
        internal = kind + ':' + locator
        generation, value = self._load()
        handle = value['items'].get(internal)
        if handle is not None:
            return handle
        if len(value['items']) >= self._maximum:
            raise RuntimeError('opaque credential handle limit reached')
        handle = value['next']
        value['next'] += 1
        value['items'][internal] = handle
        payload = json.dumps(value, separators=(',', ':')).encode()
        self._namespace.commit(generation, payload)
        return handle


def _required(value, name):
    if not callable(value):
        raise ValueError(name + ' is unavailable')
    return value


class ProductionIdentityAdapter:
    """Project installed certificate files into the v3 identity contract."""

    def __init__(self, paths, certificate_reader, fingerprint_reader,
                 method_getter, enrollment_handler, renewal_handler,
                 trust_getter, trust_remover, handles, to_epoch, now,
                 tracker=None):
        if not isinstance(paths, dict) or not paths:
            raise ValueError('identity paths are unavailable')
        self._paths = {}
        for purpose, value in paths.items():
            if (purpose not in ('portal', 'device-api-fleet', 'renewal') or
                    not isinstance(value, dict) or
                    set(value) != {'certificate', 'key'} or
                    not value['certificate'] or not value['key']):
                raise ValueError('identity path mapping is invalid')
            self._paths[str(purpose)] = {
                'certificate': str(value['certificate']),
                'key': str(value['key']),
            }
        self._certificate_reader = _required(
            certificate_reader, 'certificate reader'
        )
        self._fingerprint_reader = _required(
            fingerprint_reader, 'certificate fingerprint reader'
        )
        self._method_getter = _required(method_getter, 'identity method reader')
        self._enroll = _required(enrollment_handler, 'enrollment handler')
        self._renew = _required(renewal_handler, 'renewal handler')
        self._trust_getter = _required(trust_getter, 'trust inventory reader')
        self._trust_remover = _required(trust_remover, 'trust remover')
        self._handles = handles
        self._to_epoch = _required(to_epoch, 'certificate time decoder')
        self._now = _required(now, 'identity clock')
        self._tracker = tracker
        self._running = False
        self._generation = 0
        self._fingerprints = ()
        self._operation = ''
        self._requested_method = ''
        self._last_error = ''

    def start(self):
        self._running = True
        self._refresh_generation()

    def stop(self):
        self._running = False

    def poll(self):
        self._refresh_generation()
        if self._tracker is not None:
            state = self._tracker.status()
            self._last_error = state.get('last_error', '')
            if not state.get('pending'):
                self._operation = ''
                self._requested_method = ''

    def _method(self):
        method = self._requested_method or str(self._method_getter())
        if method not in IDENTITY_METHODS:
            raise ValueError('installed identity method is unsupported')
        return method

    def _records(self):
        records = []
        fingerprints = []
        for purpose in ('portal', 'device-api-fleet', 'renewal'):
            paths = self._paths.get(purpose)
            if not paths:
                continue
            certificate = str(paths.get('certificate', ''))
            key = str(paths.get('key', ''))
            details = self._certificate_reader(certificate)
            if not details.get('installed') or details.get('error'):
                continue
            fingerprint = str(self._fingerprint_reader(certificate)).lower()
            if len(fingerprint) != 64:
                raise ValueError('installed certificate fingerprint is invalid')
            fingerprints.append((purpose, fingerprint))
            records.append({
                'purpose': purpose,
                'certificate_handle': self._handles.resolve(
                    'certificate', certificate
                ),
                'key_handle': self._handles.resolve('key', key),
                'subject': str(details.get('subject', ''))[:128],
                'issuer': str(details.get('issuer', ''))[:128],
                'fingerprint': fingerprint,
                'not_before': int(self._to_epoch(details.get('not_before', ''))),
                'not_after': int(self._to_epoch(details.get('not_after', ''))),
            })
        return records, tuple(fingerprints)

    def _refresh_generation(self):
        unused, fingerprints = self._records()
        if fingerprints != self._fingerprints:
            self._fingerprints = fingerprints
            self._generation += 1

    @staticmethod
    def _renewal_due(records, method):
        if method == 'manual-package' or not records:
            return 0
        return min(
            item['not_before'] +
            ((item['not_after'] - item['not_before']) * 2 // 3)
            for item in records
        )

    def identity_state(self):
        method = self._method()
        records, fingerprints = self._records()
        if fingerprints != self._fingerprints:
            self._fingerprints = fingerprints
            self._generation += 1
        managed = method != 'manual-package'
        if not managed:
            state = 'manual'
        elif self._last_error:
            state = 'error'
        elif self._operation:
            state = 'renewing'
        else:
            state = 'current'
        return {
            'contract_version': 1,
            'generation': self._generation,
            'method': method,
            'identities': records,
            'renewal': {
                'managed': managed, 'state': state,
                'due_at': self._renewal_due(records, method),
            },
        }

    def _submit(self, operation, name):
        self._operation = name
        self._last_error = ''
        result = operation
        if self._tracker is not None:
            self._tracker.submit(result)
        elif hasattr(result, '__await__'):
            raise RuntimeError('identity operation requires a task scheduler')
        else:
            self._operation = ''
        return self.identity_state()

    def enroll(self, method, authorization):
        if method not in IDENTITY_METHODS:
            raise ValueError('identity method is unsupported')
        self._requested_method = method
        try:
            operation = self._enroll(method, authorization)
        except Exception:
            self._requested_method = ''
            raise
        return self._submit(operation, 'enrollment')

    def renew(self):
        return self._submit(self._renew(self._method()), 'renewal')

    def trust_inventory(self):
        result = []
        for item in self._trust_getter():
            result.append({
                'id': str(item['id'])[:32],
                'purpose': str(item['purpose']),
                'subject': str(item['subject'])[:128],
                'fingerprint': str(item['fingerprint']).lower(),
                'generation': int(item['generation']),
            })
        return result

    def remove_trust(self, identifier, generation):
        current = next((
            item for item in self.trust_inventory()
            if item['id'] == identifier
        ), None)
        if current is None:
            raise ValueError('trust anchor was not found')
        if current['generation'] != generation:
            raise RuntimeError('trust generation changed')
        self._trust_remover(identifier, generation)
        return self.trust_inventory()
