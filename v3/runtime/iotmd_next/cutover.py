"""Fail-closed coordinator for compatibility, shadow and native-v3 cutover."""

try:
    import ujson as json
except ImportError:
    import json


CONTRACT_VERSION = 1
STATE_VERSION = 1
MODES = ('compatibility', 'shadow', 'active')
PHASES = ('idle', 'starting', 'running', 'fallback', 'stopped')


class CutoverError(RuntimeError):
    pass


def _state():
    return {
        'state_version': STATE_VERSION,
        'requested_mode': 'compatibility',
        'effective_mode': 'compatibility',
        'phase': 'idle',
        'boot_attempts': 0,
        'failures': 0,
        'last_failure': '',
    }


def _validate_state(value):
    if not isinstance(value, dict) or set(value) != set(_state()):
        raise CutoverError('cutover state is invalid')
    if value['state_version'] != STATE_VERSION:
        raise CutoverError('cutover state version is unsupported')
    for key in ('requested_mode', 'effective_mode'):
        if value[key] not in MODES:
            raise CutoverError('cutover mode is invalid')
    if value['phase'] not in PHASES:
        raise CutoverError('cutover phase is invalid')
    for key in ('boot_attempts', 'failures'):
        if (not isinstance(value[key], int) or isinstance(value[key], bool) or
                value[key] < 0 or value[key] > 1000000):
            raise CutoverError('cutover counter is invalid')
    if (not isinstance(value['last_failure'], str) or
            len(value['last_failure']) > 160):
        raise CutoverError('cutover failure is invalid')
    return value


def _decode(payload):
    if not payload:
        return _state()
    try:
        return _validate_state(json.loads(payload.decode()))
    except CutoverError:
        raise
    except Exception:
        raise CutoverError('cutover state is unreadable')


def _encode(value):
    _validate_state(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    except TypeError:
        return json.dumps(value).encode()


def _adapter(value, operations, name):
    for operation in operations:
        if not callable(getattr(value, operation, None)):
            raise CutoverError(name + ' adapter is incomplete')
    return value


class CutoverCoordinator:
    """Own one runtime path and require recorded evidence before v3 activation."""

    def __init__(self, namespace, platform, kernel_factory, compatibility,
                 recovery, qualification):
        if not callable(kernel_factory):
            raise CutoverError('kernel factory is unavailable')
        if not callable(getattr(qualification, 'snapshot', None)):
            raise CutoverError('qualification recorder is unavailable')
        self._namespace = namespace
        self._platform = platform
        self._kernel_factory = kernel_factory
        self._compatibility = _adapter(
            compatibility, ('start', 'stop', 'poll', 'snapshot'),
            'compatibility runtime'
        )
        self._recovery = _adapter(recovery, ('request',), 'recovery')
        self._qualification = qualification
        self._kernel = None
        self._generation, payload = namespace.snapshot()
        self._state = _decode(payload)
        if not payload:
            self._commit()

    def _commit(self):
        self._generation = self._namespace.commit(
            self._generation, _encode(self._state)
        )

    def blockers(self, mode=None):
        mode = mode or self._state['requested_mode']
        if mode not in MODES:
            raise CutoverError('cutover mode is invalid')
        if mode != 'active':
            return []
        capabilities = self._platform.capabilities()
        updates = capabilities['updates']
        blockers = []
        if not updates['paired_trial']:
            blockers.append('native paired trial is unavailable')
        if not updates['native_rollback']:
            blockers.append('native paired rollback is unavailable')
        qualification = self._qualification.snapshot()
        for gate in qualification.get('gates', ()):
            if gate.get('status') != 'passed':
                blockers.append(
                    'qualification ' + str(gate.get('name', 'unknown')) +
                    ' is ' + str(gate.get('status', 'not-run'))
                )
        if not qualification.get('promotion_ready') and not blockers:
            blockers.append('release qualification is incomplete')
        return blockers[:24]

    def request_mode(self, mode):
        if mode not in MODES:
            raise CutoverError('cutover mode is invalid')
        blockers = self.blockers(mode)
        if blockers:
            raise CutoverError('; '.join(blockers))
        if self._state['phase'] in ('starting', 'running'):
            raise CutoverError('runtime must be stopped before changing mode')
        self._state['requested_mode'] = mode
        self._state['last_failure'] = ''
        self._commit()
        return self.snapshot()

    def boot(self, configuration):
        if self._state['phase'] in ('starting', 'running'):
            raise CutoverError('runtime is already started')
        requested = self._state['requested_mode']
        blockers = self.blockers(requested)
        if blockers:
            raise CutoverError('; '.join(blockers))
        self._state['phase'] = 'starting'
        self._state['boot_attempts'] = min(
            1000000, self._state['boot_attempts'] + 1
        )
        self._commit()
        try:
            if requested in ('compatibility', 'shadow'):
                self._compatibility.start()
            if requested in ('shadow', 'active'):
                self._kernel = self._kernel_factory()
                self._kernel.boot(configuration)
            self._state['effective_mode'] = requested
            self._state['phase'] = 'running'
            self._state['last_failure'] = ''
            self._commit()
            return self.snapshot()
        except Exception as exc:
            self._fallback(exc)
            raise

    def _fallback(self, failure):
        if self._kernel is not None:
            try:
                self._kernel.shutdown()
            except Exception:
                pass
            self._kernel = None
        self._state['failures'] = min(1000000, self._state['failures'] + 1)
        self._state['last_failure'] = str(failure)[:160]
        # A failed native path must not be retried automatically on the next
        # boot merely because its earlier qualification evidence still passes.
        # Returning to v3 requires a new explicit mode request.
        self._state['requested_mode'] = 'compatibility'
        self._state['effective_mode'] = 'compatibility'
        self._state['phase'] = 'fallback'
        self._commit()
        try:
            self._recovery.request(self._state['last_failure'])
        finally:
            try:
                self._compatibility.start()
            except Exception:
                pass

    def poll(self):
        if self._state['phase'] != 'running':
            raise CutoverError('runtime is not running')
        try:
            if self._state['effective_mode'] in ('compatibility', 'shadow'):
                self._compatibility.poll()
            if self._kernel is not None:
                self._kernel.poll()
                snapshot = self._kernel.snapshot()
                if snapshot.get('health', {}).get('state') == 'failed':
                    raise CutoverError('v3 kernel health gate failed')
        except Exception as exc:
            self._fallback(exc)
            raise

    def stop(self):
        if self._kernel is not None:
            self._kernel.shutdown()
            self._kernel = None
        try:
            self._compatibility.stop()
        finally:
            self._state['phase'] = 'stopped'
            self._commit()
        return self.snapshot()

    def snapshot(self):
        kernel = None if self._kernel is None else self._kernel.snapshot()
        qualification = self._qualification.snapshot()
        return {
            'contract_version': CONTRACT_VERSION,
            'requested_mode': self._state['requested_mode'],
            'effective_mode': self._state['effective_mode'],
            'phase': self._state['phase'],
            'boot_attempts': self._state['boot_attempts'],
            'failures': self._state['failures'],
            'last_failure': self._state['last_failure'],
            'activation_blockers': self.blockers('active'),
            'qualification_ready': bool(qualification.get('promotion_ready')),
            'compatibility': self._compatibility.snapshot(),
            'kernel': kernel,
        }
