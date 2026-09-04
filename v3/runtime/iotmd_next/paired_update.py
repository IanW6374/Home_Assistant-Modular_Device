"""Deterministic paired platform/runtime trial-state coordinator."""

try:
    import json
except ImportError:  # pragma: no cover - MicroPython compatibility
    import ujson as json

CONTRACT_VERSION = 1
COMPONENTS = ('platform', 'runtime')
PHASES = ('idle', 'staging', 'ready', 'trial', 'confirmed', 'rollback')


class PairedUpdateError(RuntimeError):
    pass


def _bounded(value, name, maximum=128):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise PairedUpdateError(name + ' is invalid')
    return value


def validate_pair(value):
    if not isinstance(value, dict) or set(value) != {
            'id', 'sequence', 'platform', 'runtime'}:
        raise PairedUpdateError('paired release descriptor is invalid')
    _bounded(value['id'], 'pair id', 64)
    sequence = value['sequence']
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise PairedUpdateError('pair sequence is invalid')
    for component in COMPONENTS:
        item = value[component]
        if not isinstance(item, dict) or set(item) != {'version', 'sha256'}:
            raise PairedUpdateError(component + ' descriptor is invalid')
        _bounded(item['version'], component + ' version', 48)
        digest = _bounded(item['sha256'], component + ' digest', 64)
        if len(digest) != 64:
            raise PairedUpdateError(component + ' digest is invalid')
        try:
            int(digest, 16)
        except ValueError:
            raise PairedUpdateError(component + ' digest is invalid')
    return value


def initial_state():
    return {
        'contract_version': CONTRACT_VERSION,
        'phase': 'idle',
        'pair': None,
        'previous_pair': None,
        'staged': {'platform': False, 'runtime': False},
        'failure_reason': '',
    }


def validate_state(value):
    if not isinstance(value, dict) or set(value) != {
            'contract_version', 'phase', 'pair', 'previous_pair', 'staged',
            'failure_reason'}:
        raise PairedUpdateError('paired update state is invalid')
    if value['contract_version'] != CONTRACT_VERSION:
        raise PairedUpdateError('paired update contract is unsupported')
    if value['phase'] not in PHASES:
        raise PairedUpdateError('paired update phase is invalid')
    if value['pair'] is not None:
        validate_pair(value['pair'])
    if value['previous_pair'] is not None:
        validate_pair(value['previous_pair'])
    staged = value['staged']
    if not isinstance(staged, dict) or set(staged) != set(COMPONENTS):
        raise PairedUpdateError('paired staged state is invalid')
    if any(staged[item] is not True and staged[item] is not False
           for item in COMPONENTS):
        raise PairedUpdateError('paired staged state is invalid')
    if not isinstance(value['failure_reason'], str) or len(
            value['failure_reason']) > 160:
        raise PairedUpdateError('paired failure reason is invalid')
    if value['phase'] in ('ready', 'trial') and not all(staged.values()):
        raise PairedUpdateError('paired release is not fully staged')
    return value


def _encode(value):
    validate_state(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'))
    except TypeError:  # MicroPython ujson has a smaller API.
        encoded = json.dumps(value)
    return encoded.encode()


def _decode(payload):
    if not payload:
        return initial_state()
    try:
        value = json.loads(payload.decode())
    except (ValueError, UnicodeError):
        raise PairedUpdateError('paired update state is unreadable')
    return validate_state(value)


class PairedUpdateCoordinator:
    def __init__(self, namespace):
        self._namespace = namespace

    def state(self):
        generation, payload = self._namespace.snapshot()
        return generation, _decode(payload)

    def _change(self, generation, value):
        validate_state(value)
        return self._namespace.commit(generation, _encode(value)), value

    def prepare(self, pair):
        validate_pair(pair)
        generation, state = self.state()
        if state['phase'] not in ('idle', 'confirmed'):
            raise PairedUpdateError('another paired update is pending')
        confirmed = state['pair'] if state['phase'] == 'confirmed' else None
        if confirmed is not None and pair['sequence'] <= confirmed['sequence']:
            raise PairedUpdateError('paired release sequence is not newer')
        return self._change(generation, {
            'contract_version': CONTRACT_VERSION,
            'phase': 'staging',
            'pair': pair,
            'previous_pair': confirmed,
            'staged': {'platform': False, 'runtime': False},
            'failure_reason': '',
        })

    def mark_staged(self, component):
        if component not in COMPONENTS:
            raise PairedUpdateError('paired component is invalid')
        generation, state = self.state()
        if state['phase'] != 'staging':
            raise PairedUpdateError('paired release is not staging')
        state['staged'][component] = True
        if all(state['staged'].values()):
            state['phase'] = 'ready'
        return self._change(generation, state)

    def begin_trial(self):
        generation, state = self.state()
        if state['phase'] != 'ready':
            raise PairedUpdateError('paired release is not ready')
        state['phase'] = 'trial'
        return self._change(generation, state)

    def confirm(self, running_pair_id):
        generation, state = self.state()
        if state['phase'] != 'trial' or state['pair']['id'] != running_pair_id:
            raise PairedUpdateError('running pair cannot be confirmed')
        state['phase'] = 'confirmed'
        state['previous_pair'] = None
        return self._change(generation, state)

    def request_rollback(self, reason):
        reason = _bounded(reason, 'rollback reason', 160)
        generation, state = self.state()
        if state['phase'] not in ('staging', 'ready', 'trial'):
            raise PairedUpdateError('paired release cannot roll back')
        state['phase'] = 'rollback'
        state['failure_reason'] = reason
        return self._change(generation, state)

    def complete_rollback(self):
        generation, state = self.state()
        if state['phase'] != 'rollback':
            raise PairedUpdateError('paired rollback is not pending')
        restored = state['previous_pair']
        value = initial_state()
        if restored is not None:
            value['phase'] = 'confirmed'
            value['pair'] = restored
            value['staged'] = {'platform': True, 'runtime': True}
        return self._change(generation, value)

    def reconcile_trial(self, platform_digest, runtime_digest):
        generation, state = self.state()
        if state['phase'] != 'trial':
            return generation, state
        expected = state['pair']
        if (expected['platform']['sha256'] == platform_digest and
                expected['runtime']['sha256'] == runtime_digest):
            return generation, state
        state['phase'] = 'rollback'
        state['failure_reason'] = 'running platform/runtime pair does not match'
        return self._change(generation, state)

