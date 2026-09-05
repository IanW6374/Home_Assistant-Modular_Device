"""Certificate lifecycle orchestration without exposing certificate secrets."""

from .configuration import IDENTITY_METHODS

IDENTITY_STATE_VERSION = 1
IDENTITY_PURPOSES = ('portal', 'device-api-fleet', 'renewal')
TRUST_PURPOSES = ('mqtt', 'release', 'syslog', 'private-ca', 'api-client')
RENEWAL_STATES = ('managed', 'manual', 'current', 'due', 'renewing', 'error')
MAX_IDENTITIES = 3
MAX_TRUST_ANCHORS = 16


class IdentityError(RuntimeError):
    pass


def _adapter(value):
    operations = (
        'start', 'stop', 'poll', 'identity_state', 'enroll', 'renew',
        'trust_inventory', 'remove_trust',
    )
    for operation in operations:
        if not callable(getattr(value, operation, None)):
            raise IdentityError('identity adapter is incomplete')
    return value


def _integer(value, name, minimum=0):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise IdentityError(name + ' is invalid')
    return value


def _text(value, name, maximum, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not value and not empty):
        raise IdentityError(name + ' is invalid')
    return value


def _fingerprint(value, name):
    value = _text(value, name, 64).lower()
    if len(value) != 64:
        raise IdentityError(name + ' is invalid')
    try:
        int(value, 16)
    except ValueError:
        raise IdentityError(name + ' is invalid')
    return value


def validate_identity_state(value):
    if not isinstance(value, dict) or set(value) != {
            'contract_version', 'generation', 'method', 'identities', 'renewal'}:
        raise IdentityError('identity state has invalid fields')
    if value['contract_version'] != IDENTITY_STATE_VERSION:
        raise IdentityError('identity state contract is unsupported')
    _integer(value['generation'], 'identity generation')
    if value['method'] not in IDENTITY_METHODS:
        raise IdentityError('identity method is invalid')
    identities = value['identities']
    if (not isinstance(identities, list) or len(identities) > MAX_IDENTITIES or
            len({item.get('purpose') for item in identities
                 if isinstance(item, dict)}) != len(identities)):
        raise IdentityError('identity inventory is invalid')
    for item in identities:
        if not isinstance(item, dict) or set(item) != {
                'purpose', 'certificate_handle', 'key_handle', 'subject',
                'issuer', 'fingerprint', 'not_before', 'not_after'}:
            raise IdentityError('identity record has invalid fields')
        if item['purpose'] not in IDENTITY_PURPOSES:
            raise IdentityError('identity purpose is invalid')
        _integer(item['certificate_handle'], 'certificate handle', 1)
        _integer(item['key_handle'], 'private key handle', 1)
        _text(item['subject'], 'certificate subject', 128)
        _text(item['issuer'], 'certificate issuer', 128)
        _fingerprint(item['fingerprint'], 'certificate fingerprint')
        before = _integer(item['not_before'], 'certificate not-before')
        after = _integer(item['not_after'], 'certificate not-after', 1)
        if before >= after:
            raise IdentityError('certificate validity is invalid')
    renewal = value['renewal']
    if not isinstance(renewal, dict) or set(renewal) != {
            'managed', 'state', 'due_at'}:
        raise IdentityError('identity renewal has invalid fields')
    if renewal['managed'] is not True and renewal['managed'] is not False:
        raise IdentityError('identity renewal managed flag is invalid')
    if renewal['state'] not in RENEWAL_STATES:
        raise IdentityError('identity renewal state is invalid')
    _integer(renewal['due_at'], 'identity renewal due time')
    if value['method'] == 'manual-package' and (
            renewal['managed'] or renewal['state'] != 'manual'):
        raise IdentityError('manual identity cannot enable renewal')
    if value['method'] != 'manual-package' and not renewal['managed']:
        raise IdentityError('managed identity must enable renewal')
    return value


def validate_trust_inventory(value):
    if not isinstance(value, list) or len(value) > MAX_TRUST_ANCHORS:
        raise IdentityError('trust inventory is invalid')
    result = []
    identifiers = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
                'id', 'purpose', 'subject', 'fingerprint', 'generation'}:
            raise IdentityError('trust record has invalid fields')
        identifier = _text(item['id'], 'trust identifier', 32)
        if identifier in identifiers:
            raise IdentityError('trust identifier is duplicated')
        identifiers.add(identifier)
        if item['purpose'] not in TRUST_PURPOSES:
            raise IdentityError('trust purpose is invalid')
        result.append({
            'id': identifier, 'purpose': item['purpose'],
            'subject': _text(item['subject'], 'trust subject', 128),
            'fingerprint': _fingerprint(
                item['fingerprint'], 'trust fingerprint'
            ),
            'generation': _integer(item['generation'], 'trust generation'),
        })
    return result


class IdentityLifecycleService:
    """Policy layer over native/transport certificate operations."""

    def __init__(self, adapter, configuration, now, clock_synchronised):
        self._adapter = _adapter(adapter)
        self._configuration = dict(configuration)
        self._now = now
        self._clock_synchronised = clock_synchronised
        self._state = None
        self._trust_count = 0
        self._next_check = 0
        self._renewals = 0

    def start(self):
        self._adapter.start()
        self._state = validate_identity_state(self._adapter.identity_state())
        if self._state['method'] != self._configuration['method']:
            raise IdentityError('configured identity method does not match installed state')
        self._trust_count = len(self.trust_inventory())
        self._next_check = int(self._now())

    def stop(self):
        self._adapter.stop()

    def poll(self):
        self._adapter.poll()
        refreshed = validate_identity_state(self._adapter.identity_state())
        if refreshed['method'] != self._configuration['method']:
            raise IdentityError(
                'configured identity method does not match installed state'
            )
        self._state = refreshed
        now = int(self._now())
        if now < self._next_check:
            return
        self._next_check = now + int(self._configuration['renewal_check_s'])
        if self._state['method'] == 'manual-package':
            return
        if not self._clock_synchronised():
            return
        due_at = self._state['renewal']['due_at']
        if (due_at and now >= due_at and
                self._state['renewal']['state'] != 'renewing'):
            self._state = validate_identity_state(self._adapter.renew())
            self._renewals += 1

    def change_method(self, method, authorization=None):
        if method not in IDENTITY_METHODS:
            raise IdentityError('identity method is invalid')
        self._state = validate_identity_state(
            self._adapter.enroll(method, authorization)
        )
        if self._state['method'] != method:
            raise IdentityError('enrollment returned the wrong identity method')
        self._configuration['method'] = method
        return self.inventory()

    def inventory(self):
        if self._state is None:
            raise IdentityError('identity service is not started')
        return {
            'contract_version': self._state['contract_version'],
            'generation': self._state['generation'],
            'method': self._state['method'],
            'identities': [dict(item) for item in self._state['identities']],
            'renewal': dict(self._state['renewal']),
        }

    def trust_inventory(self):
        return validate_trust_inventory(self._adapter.trust_inventory())

    def remove_trust(self, identifier, generation):
        identifier = _text(identifier, 'trust identifier', 32)
        generation = _integer(generation, 'trust generation')
        result = self._adapter.remove_trust(identifier, generation)
        inventory = validate_trust_inventory(result)
        self._trust_count = len(inventory)
        return inventory

    def snapshot(self):
        if self._state is None:
            return {'state': 'inactive'}
        renewal = self._state['renewal']
        state = renewal['state']
        if renewal['managed'] and not self._clock_synchronised():
            state = 'clock-unsynchronised'
        return {
            'state': 'active',
            'method': self._state['method'],
            'generation': self._state['generation'],
            'identities': len(self._state['identities']),
            'trust_anchors': self._trust_count,
            'renewal': state,
            'renewal_due_at': renewal['due_at'],
            'renewals': self._renewals,
        }
