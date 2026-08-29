"""Signed fleet policy and rollout state for the IoT-MD v2 device API."""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

try:
    import time
except ImportError:
    time = None

import update_security


FORMAT_VERSION = 1
STATE_FORMAT_VERSION = 1
DEFAULT_STATE_PATH = '.fleet-state.json'
FLEET_VERIFICATION_KEY_PATH = '.fleet-verification-key'
ALLOWED_POLICY_FIELDS = {
    'format_version', 'target_board', 'policy_sequence', 'issued_at', 'not_before',
    'expires_at', 'target_device', 'target_cohort', 'maintenance', 'updates',
    'telemetry', 'commands', 'signature_scheme', 'signature',
}
ALLOWED_COMMANDS = ('check-update', 'download-update', 'activate-update', 'rollback')
ALLOWED_SEVERITIES = ('debug', 'info', 'warning', 'error', 'critical')


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _bounded_integer(value, name, minimum, maximum):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(name + ' must be an integer')
    if value < minimum or value > maximum:
        raise ValueError(name + ' is outside the supported range')
    return value


def validate_policy_structure(policy):
    if not isinstance(policy, dict):
        raise ValueError('fleet policy must be an object')
    unknown = set(policy) - ALLOWED_POLICY_FIELDS
    if unknown:
        raise ValueError('unknown fleet policy field: ' + sorted(unknown)[0])
    if policy.get('format_version') != FORMAT_VERSION:
        raise ValueError('unsupported fleet policy format')
    if policy.get('target_board') != update_security.TARGET_BOARD:
        raise ValueError('fleet policy target board is invalid')
    _bounded_integer(policy.get('policy_sequence'), 'policy sequence', 1, 2147483647)
    issued_at = _bounded_integer(policy.get('issued_at'), 'issued_at', 1, 4294967295)
    not_before = _bounded_integer(policy.get('not_before'), 'not_before', 1, 4294967295)
    expires_at = _bounded_integer(policy.get('expires_at'), 'expires_at', 1, 4294967295)
    if not issued_at <= not_before < expires_at:
        raise ValueError('fleet policy validity period is invalid')
    if not str(policy.get('target_device', '') or policy.get('target_cohort', '')).strip():
        raise ValueError('fleet policy must target a device or cohort')

    maintenance = policy.get('maintenance')
    if not isinstance(maintenance, dict) or set(maintenance) != {
        'weekdays', 'start_minute', 'duration_minutes'
    }:
        raise ValueError('fleet maintenance window is invalid')
    weekdays = maintenance['weekdays']
    if (
        not isinstance(weekdays, list) or not weekdays or
        any(not isinstance(day, int) or isinstance(day, bool) or day < 0 or day > 6
            for day in weekdays) or len(set(weekdays)) != len(weekdays)
    ):
        raise ValueError('fleet maintenance weekdays are invalid')
    _bounded_integer(maintenance['start_minute'], 'maintenance start', 0, 1439)
    _bounded_integer(maintenance['duration_minutes'], 'maintenance duration', 1, 1440)

    updates = policy.get('updates')
    if not isinstance(updates, dict) or set(updates) != {
        'channel', 'automatic_download', 'automatic_activation',
        'maximum_consecutive_failures'
    }:
        raise ValueError('fleet update policy is invalid')
    if updates['channel'] not in ('stable', 'beta', 'alpha'):
        raise ValueError('fleet update channel is invalid')
    if not isinstance(updates['automatic_download'], bool) or not isinstance(
        updates['automatic_activation'], bool
    ):
        raise ValueError('fleet automatic update controls must be boolean')
    _bounded_integer(
        updates['maximum_consecutive_failures'], 'maximum failures', 1, 20
    )

    telemetry = policy.get('telemetry')
    if not isinstance(telemetry, dict) or set(telemetry) != {
        'enabled', 'minimum_interval_s', 'severities'
    }:
        raise ValueError('fleet telemetry policy is invalid')
    if not isinstance(telemetry['enabled'], bool):
        raise ValueError('fleet telemetry enabled must be boolean')
    _bounded_integer(telemetry['minimum_interval_s'], 'telemetry interval', 10, 86400)
    severities = telemetry['severities']
    if (
        not isinstance(severities, list) or
        any(value not in ALLOWED_SEVERITIES for value in severities)
    ):
        raise ValueError('fleet telemetry severities are invalid')

    commands = policy.get('commands')
    if not isinstance(commands, list) or len(commands) > 16:
        raise ValueError('fleet policy commands are invalid')
    identifiers = set()
    for command in commands:
        if not isinstance(command, dict) or set(command) != {
            'id', 'action', 'release_sequence'
        }:
            raise ValueError('fleet policy command is invalid')
        identifier = str(command['id'])
        if not identifier or len(identifier) > 64 or identifier in identifiers:
            raise ValueError('fleet command identifier is invalid')
        identifiers.add(identifier)
        if command['action'] not in ALLOWED_COMMANDS:
            raise ValueError('fleet command action is invalid')
        _bounded_integer(
            command['release_sequence'], 'command release sequence', 0, 2147483647
        )
    if policy.get('signature_scheme') != update_security.SIGNATURE_SCHEME:
        raise ValueError('fleet policy signature scheme is invalid')
    signature = str(policy.get('signature', '')).lower()
    if len(signature) != 128:
        raise ValueError('fleet policy signature is invalid')
    return policy


class FleetService:
    def __init__(self, device_id, cohort='default', state_path=DEFAULT_STATE_PATH,
                 key_path=FLEET_VERIFICATION_KEY_PATH, now=None,
                 localtime=None):
        self.device_id = str(device_id)
        self.cohort = str(cohort or 'default')
        self.state_path = str(state_path)
        self.key_path = key_path
        self._now = now or (lambda: int(time.time()) if time else 0)
        self._localtime = localtime or (lambda epoch: time.localtime(epoch))
        self.state = self._load()

    def _empty(self):
        return {
            'format_version': STATE_FORMAT_VERSION,
            'policy_sequence': 0,
            'policy': None,
            'consecutive_failures': 0,
            'rollout_paused': False,
            'completed_commands': [],
            'last_result': {},
        }

    def _load(self):
        try:
            with open(self.state_path, 'r') as stream:
                value = json.load(stream)
            if value.get('format_version') != STATE_FORMAT_VERSION:
                raise ValueError
            return value
        except Exception:
            return self._empty()

    def _save(self):
        temporary = self.state_path + '.tmp'
        with open(temporary, 'w') as stream:
            json.dump(self.state, stream)
        _replace(temporary, self.state_path)

    def apply_policy(self, policy):
        validate_policy_structure(policy)
        if (
            str(policy.get('target_device', '')) not in ('', self.device_id) or
            str(policy.get('target_cohort', '')) not in ('', self.cohort)
        ):
            raise ValueError('fleet policy target does not match this device')
        now = int(self._now())
        if now < int(policy['not_before']) or now >= int(policy['expires_at']):
            raise ValueError('fleet policy is not currently valid')
        sequence = int(policy['policy_sequence'])
        if sequence <= int(self.state.get('policy_sequence', 0) or 0):
            raise ValueError('fleet policy sequence is not newer')
        try:
            with open(self.key_path, 'rb') as stream:
                raw_key = stream.read()
            public_key = update_security.validate_public_key_bytes(raw_key)
        except Exception:
            raise ValueError('fleet verification key is not provisioned or invalid')
        if public_key is None or not update_security.verify_manifest_signature(
            'fleet-policy', policy, policy['signature'], public_key
        ):
            raise ValueError('fleet policy signature verification failed')
        self.state['policy_sequence'] = sequence
        self.state['policy'] = dict(policy)
        self.state['rollout_paused'] = False
        self._save()
        return self.snapshot()

    def within_maintenance_window(self, epoch=None):
        policy = self.state.get('policy') or {}
        window = policy.get('maintenance') or {}
        if not window:
            return False
        value = self._localtime(int(self._now() if epoch is None else epoch))
        weekday = int(value[6])
        minute = int(value[3]) * 60 + int(value[4])
        start = int(window['start_minute'])
        duration = int(window['duration_minutes'])
        return weekday in window['weekdays'] and start <= minute < start + duration

    def pending_commands(self):
        completed = set(self.state.get('completed_commands', ()))
        policy = self.state.get('policy') or {}
        return [
            dict(command) for command in policy.get('commands', ())
            if command.get('id') not in completed
        ]

    def complete_command(self, identifier, result='complete', detail=''):
        identifier = str(identifier)
        if identifier not in [item.get('id') for item in self.pending_commands()]:
            raise ValueError('fleet command is not pending')
        completed = self.state.setdefault('completed_commands', [])
        completed.append(identifier)
        self.state['completed_commands'] = completed[-64:]
        self.record_result(result, detail)
        return self.snapshot()

    def record_result(self, result, detail=''):
        failed = str(result) not in ('complete', 'confirmed', 'healthy')
        failures = int(self.state.get('consecutive_failures', 0) or 0)
        self.state['consecutive_failures'] = failures + 1 if failed else 0
        policy = self.state.get('policy') or {}
        maximum = int((policy.get('updates') or {}).get(
            'maximum_consecutive_failures', 1
        ))
        self.state['rollout_paused'] = self.state['consecutive_failures'] >= maximum
        self.state['last_result'] = {
            'time': int(self._now()), 'result': str(result),
            'detail': str(detail)[:160],
        }
        self._save()
        return dict(self.state['last_result'])

    def snapshot(self):
        value = json.loads(json.dumps(self.state))
        value.update({
            'device_id': self.device_id,
            'cohort': self.cohort,
            'within_maintenance_window': self.within_maintenance_window(),
            'pending_commands': self.pending_commands(),
        })
        return value
