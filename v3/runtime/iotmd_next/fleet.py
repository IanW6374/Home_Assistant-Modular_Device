"""Bounded signed fleet policy and canary reporting service."""

try:
    import ujson as json
except ImportError:
    import json

POLICY_VERSION = 1
STATE_VERSION = 1
REPORT_VERSION = 1
SIGNATURE_SCHEME = 'ecdsa-p256-sha256'
COMMANDS = ('check-update', 'download-update', 'activate-update', 'rollback')
OUTCOMES = ('unknown', 'healthy', 'confirmed', 'failed', 'rolled-back')


class FleetError(RuntimeError):
    pass


def _integer(value, name, minimum, maximum=4294967295):
    if (not isinstance(value, int) or isinstance(value, bool) or
            value < minimum or value > maximum):
        raise FleetError(name + ' is invalid')
    return value


def _text(value, name, maximum=64, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not value and not empty):
        raise FleetError(name + ' is invalid')
    return value


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != {
            'format_version', 'target_board', 'policy_sequence', 'issued_at',
            'not_before', 'expires_at', 'target_device', 'target_cohort',
            'maintenance', 'updates', 'telemetry', 'commands',
            'signature_scheme', 'signature'}:
        raise FleetError('fleet policy has invalid fields')
    if policy['format_version'] != POLICY_VERSION:
        raise FleetError('fleet policy version is unsupported')
    if policy['target_board'] != 'esp32-s3':
        raise FleetError('fleet policy board is invalid')
    _integer(policy['policy_sequence'], 'fleet policy sequence', 1, 2147483647)
    issued = _integer(policy['issued_at'], 'fleet policy issue time', 1)
    start = _integer(policy['not_before'], 'fleet policy start time', 1)
    end = _integer(policy['expires_at'], 'fleet policy expiry time', 1)
    if not issued <= start < end:
        raise FleetError('fleet policy validity is invalid')
    device = _text(policy['target_device'], 'fleet target device', 64, True)
    cohort = _text(policy['target_cohort'], 'fleet target cohort', 32, True)
    if not device and not cohort:
        raise FleetError('fleet policy has no target')
    maintenance = policy['maintenance']
    if not isinstance(maintenance, dict) or set(maintenance) != {
            'weekdays', 'start_minute', 'duration_minutes'}:
        raise FleetError('fleet maintenance window is invalid')
    weekdays = maintenance['weekdays']
    if (not isinstance(weekdays, list) or not weekdays or len(weekdays) > 7 or
            len(set(weekdays)) != len(weekdays)):
        raise FleetError('fleet maintenance weekdays are invalid')
    for day in weekdays:
        _integer(day, 'fleet maintenance weekday', 0, 6)
    _integer(maintenance['start_minute'], 'fleet maintenance start', 0, 1439)
    _integer(maintenance['duration_minutes'], 'fleet maintenance duration', 1, 1440)
    updates = policy['updates']
    if not isinstance(updates, dict) or set(updates) != {
            'channel', 'automatic_download', 'automatic_activation',
            'maximum_consecutive_failures'}:
        raise FleetError('fleet update controls are invalid')
    if updates['channel'] not in ('stable', 'beta', 'alpha'):
        raise FleetError('fleet update channel is invalid')
    for key in ('automatic_download', 'automatic_activation'):
        if updates[key] is not True and updates[key] is not False:
            raise FleetError('fleet update control is invalid')
    _integer(updates['maximum_consecutive_failures'], 'fleet failure threshold', 1, 20)
    telemetry = policy['telemetry']
    if not isinstance(telemetry, dict) or set(telemetry) != {
            'enabled', 'minimum_interval_s', 'severities'}:
        raise FleetError('fleet telemetry controls are invalid')
    if telemetry['enabled'] is not True and telemetry['enabled'] is not False:
        raise FleetError('fleet telemetry enabled flag is invalid')
    _integer(telemetry['minimum_interval_s'], 'fleet telemetry interval', 10, 86400)
    if (not isinstance(telemetry['severities'], list) or
            any(item not in ('warning', 'error', 'critical')
                for item in telemetry['severities'])):
        raise FleetError('fleet telemetry severities are invalid')
    commands = policy['commands']
    if not isinstance(commands, list) or len(commands) > 16:
        raise FleetError('fleet commands are invalid')
    identifiers = set()
    for command in commands:
        if not isinstance(command, dict) or set(command) != {
                'id', 'action', 'release_sequence'}:
            raise FleetError('fleet command is invalid')
        identifier = _text(command['id'], 'fleet command id', 64)
        if identifier in identifiers or command['action'] not in COMMANDS:
            raise FleetError('fleet command is invalid')
        identifiers.add(identifier)
        _integer(command['release_sequence'], 'fleet command release sequence', 0, 2147483647)
    if policy['signature_scheme'] != SIGNATURE_SCHEME:
        raise FleetError('fleet policy signature scheme is invalid')
    signature = _text(policy['signature'], 'fleet policy signature', 128).lower()
    if len(signature) != 128:
        raise FleetError('fleet policy signature is invalid')
    try:
        int(signature, 16)
    except ValueError:
        raise FleetError('fleet policy signature is invalid')
    return policy


def _empty_state():
    return {
        'contract_version': STATE_VERSION, 'policy_sequence': 0,
        'policy': None, 'consecutive_failures': 0,
        'rollout_paused': False,
        'last_outcome': {'time': 0, 'result': 'unknown'},
    }


def _encode(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    except TypeError:
        return json.dumps(value).encode()


def _decode(payload):
    if not payload:
        return _empty_state()
    try:
        value = json.loads(payload.decode())
    except Exception:
        raise FleetError('fleet state is invalid')
    if not isinstance(value, dict) or set(value) != set(_empty_state()):
        raise FleetError('fleet state has invalid fields')
    if value['contract_version'] != STATE_VERSION:
        raise FleetError('fleet state version is unsupported')
    _integer(value['policy_sequence'], 'fleet state sequence', 0, 2147483647)
    if value['policy'] is not None:
        validate_policy(value['policy'])
    _integer(value['consecutive_failures'], 'fleet failure count', 0, 20)
    if value['rollout_paused'] is not True and value['rollout_paused'] is not False:
        raise FleetError('fleet rollout state is invalid')
    outcome = value['last_outcome']
    if not isinstance(outcome, dict) or set(outcome) != {'time', 'result'}:
        raise FleetError('fleet outcome is invalid')
    _integer(outcome['time'], 'fleet outcome time', 0)
    if outcome['result'] not in OUTCOMES:
        raise FleetError('fleet outcome result is invalid')
    return value


class FleetPolicyService:
    def __init__(self, namespace, verifier, configuration, device_id,
                 inventory_getter, health_getter, release_getter, now,
                 clock_synchronised, adapter=None):
        if not callable(verifier):
            raise FleetError('fleet policy verifier is unavailable')
        self._namespace = namespace
        self._verify = verifier
        self._configuration = dict(configuration)
        self._device_id = _text(str(device_id), 'fleet device id', 64)
        self._inventory_getter = inventory_getter
        self._health_getter = health_getter
        self._release_getter = release_getter
        self._now = now
        self._clock_synchronised = clock_synchronised
        self._adapter = adapter
        if adapter is not None:
            for operation in (
                    'start', 'stop', 'poll', 'fetch_policy', 'submit_report'):
                if not callable(getattr(adapter, operation, None)):
                    raise FleetError('fleet adapter is incomplete')
        self._state = _empty_state()
        self._next_poll = 0
        self._event_cursor = 0
        self._retention_gap = False

    def _save(self):
        generation, unused = self._namespace.snapshot()
        self._namespace.commit(generation, _encode(self._state))

    def start(self):
        unused, payload = self._namespace.snapshot()
        self._state = _decode(payload)
        if self._adapter is not None:
            self._adapter.start()
        self._next_poll = int(self._now())

    def stop(self):
        if self._adapter is not None:
            self._adapter.stop()

    def poll(self):
        if self._adapter is None:
            return
        self._adapter.poll()
        now = int(self._now())
        if now < self._next_poll:
            return
        self._next_poll = now + int(self._configuration['poll_interval_s'])
        policy = self._adapter.fetch_policy(self._state['policy_sequence'])
        if policy is not None and policy.get('policy_sequence', 0) > self._state['policy_sequence']:
            self.apply_policy(policy)
        self._adapter.submit_report(self.report())

    def apply_policy(self, policy):
        validate_policy(policy)
        if not self._clock_synchronised():
            raise FleetError('fleet policy requires a synchronised clock')
        if (policy['target_device'] not in ('', self._device_id) or
                policy['target_cohort'] not in ('', self._configuration['cohort'])):
            raise FleetError('fleet policy target does not match')
        now = int(self._now())
        if now < policy['not_before'] or now >= policy['expires_at']:
            raise FleetError('fleet policy is not currently valid')
        if policy['policy_sequence'] <= self._state['policy_sequence']:
            raise FleetError('fleet policy sequence is not newer')
        if self._verify(policy) is not True:
            raise FleetError('fleet policy signature verification failed')
        self._state['policy_sequence'] = policy['policy_sequence']
        self._state['policy'] = dict(policy)
        self._state['rollout_paused'] = False
        self._save()
        return self.snapshot()

    def record_outcome(self, result):
        if result not in OUTCOMES or result == 'unknown':
            raise FleetError('fleet outcome is invalid')
        failed = result in ('failed', 'rolled-back')
        count = self._state['consecutive_failures']
        self._state['consecutive_failures'] = min(20, count + 1) if failed else 0
        policy = self._state['policy'] or {}
        threshold = (policy.get('updates') or {}).get(
            'maximum_consecutive_failures', 1
        )
        self._state['rollout_paused'] = (
            self._state['consecutive_failures'] >= threshold
        )
        self._state['last_outcome'] = {
            'time': int(self._now()), 'result': result,
        }
        self._save()

    def set_event_cursor(self, cursor, retention_gap=False):
        self._event_cursor = _integer(cursor, 'fleet event cursor', 0)
        self._retention_gap = bool(retention_gap)

    def report(self):
        inventory = self._inventory_getter()
        health = self._health_getter()
        release = self._release_getter()
        return {
            'contract_version': REPORT_VERSION,
            'device_id': self._device_id,
            'cohort': self._configuration['cohort'],
            'policy_sequence': self._state['policy_sequence'],
            'inventory': {
                'board': str(inventory.get('board', ''))[:32],
                'modules': max(0, min(8, int(inventory.get('modules', 0)))),
                'transports': max(0, min(8, int(inventory.get('transports', 0)))),
            },
            'release': {
                'version': str(release.get('version', ''))[:48],
                'sequence': max(0, int(release.get('sequence', 0))),
                'confirmed': bool(release.get('confirmed', False)),
            },
            'health': {
                'state': str(health.get('state', 'unknown'))[:16],
                'services_degraded': max(
                    0, min(20, int(health.get('services_degraded', 0)))
                ),
                'services_failed': max(
                    0, min(20, int(health.get('services_failed', 0)))
                ),
            },
            'canary': {
                'outcome': self._state['last_outcome']['result'],
                'consecutive_failures': self._state['consecutive_failures'],
                'rollout_paused': self._state['rollout_paused'],
            },
            'event_cursor': self._event_cursor,
            'retention_gap': self._retention_gap,
        }

    def snapshot(self):
        return {
            'state': 'managed' if self._state['policy'] else 'unmanaged',
            'policy_sequence': self._state['policy_sequence'],
            'cohort': self._configuration['cohort'],
            'rollout_paused': self._state['rollout_paused'],
            'consecutive_failures': self._state['consecutive_failures'],
            'last_outcome': self._state['last_outcome']['result'],
        }
