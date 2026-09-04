"""Persistent, bounded evidence for v3 operational qualification gates."""

try:
    import ujson as json
except ImportError:
    import json


CONTRACT_VERSION = 1
STATE_VERSION = 2
MAX_COUNTER = 1000000
GATE_NAMES = (
    'soak', 'health', 'storage', 'network-recovery', 'certificate-renewal',
    'paired-updates', 'power-recovery', 'canary-health',
    'release-confirmation', 'native-recovery', 'watchdog-recovery',
    'identity-interoperability', 'fleet-interoperability',
    'migration-rollback', 'driver-hardware',
)

VALIDATION_COUNTERS = {
    'native-recovery': 'native_recoveries',
    'watchdog-recovery': 'watchdog_recoveries',
    'identity-interoperability': 'identity_transactions',
    'fleet-interoperability': 'fleet_transactions',
    'migration-rollback': 'migration_rollbacks',
    'driver-hardware': 'driver_checks',
}


class QualificationError(RuntimeError):
    pass


def _integer(value, name, minimum=0, maximum=2147483647):
    if (not isinstance(value, int) or isinstance(value, bool) or
            value < minimum or value > maximum):
        raise QualificationError(name + ' is invalid')
    return value


def _text(value, name, maximum=64):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise QualificationError(name + ' is invalid')
    return value


def validate_profile(value):
    required = {
        'name', 'minimum_soak_s', 'maximum_consecutive_unhealthy',
        'minimum_health_samples', 'minimum_storage_samples',
        'minimum_storage_free_bytes', 'maximum_network_recovery_s',
        'required_network_recoveries', 'required_renewals',
        'required_update_confirmations', 'required_power_recoveries',
        'required_native_recoveries', 'required_watchdog_recoveries',
        'required_identity_transactions', 'required_fleet_transactions',
        'required_migration_rollbacks', 'required_driver_checks',
    }
    if not isinstance(value, dict) or set(value) != required:
        raise QualificationError('qualification profile has invalid fields')
    result = dict(value)
    _text(result['name'], 'qualification profile name', 32)
    _integer(result['minimum_soak_s'], 'minimum soak', 60, 604800)
    _integer(
        result['maximum_consecutive_unhealthy'],
        'maximum consecutive unhealthy samples', 0, 1000
    )
    _integer(result['minimum_health_samples'], 'minimum health samples', 1, 1000000)
    _integer(
        result['minimum_storage_samples'], 'minimum storage samples', 1, 1000000
    )
    _integer(
        result['minimum_storage_free_bytes'], 'minimum storage free bytes',
        0, 1073741824
    )
    _integer(
        result['maximum_network_recovery_s'], 'maximum network recovery',
        1, 86400
    )
    for key in (
        'required_network_recoveries', 'required_renewals',
        'required_update_confirmations', 'required_power_recoveries',
        'required_native_recoveries', 'required_watchdog_recoveries',
        'required_identity_transactions', 'required_fleet_transactions',
        'required_migration_rollbacks', 'required_driver_checks',
    ):
        _integer(result[key], key.replace('_', ' '), 1, 1000)
    return result


def beta_profile():
    """Return the minimum evidence profile for a v3 beta candidate."""
    return {
        'name': 'v3-beta',
        'minimum_soak_s': 172800,
        'maximum_consecutive_unhealthy': 3,
        'minimum_health_samples': 2400,
        'minimum_storage_samples': 2400,
        'minimum_storage_free_bytes': 131072,
        'maximum_network_recovery_s': 300,
        'required_network_recoveries': 3,
        'required_renewals': 1,
        'required_update_confirmations': 3,
        'required_power_recoveries': 3,
        'required_native_recoveries': 3,
        'required_watchdog_recoveries': 3,
        'required_identity_transactions': 1,
        'required_fleet_transactions': 1,
        'required_migration_rollbacks': 1,
        'required_driver_checks': 13,
    }


def _counters():
    return {
        'samples': 0,
        'health_samples': 0,
        'storage_samples': 0,
        'unhealthy_samples': 0,
        'consecutive_unhealthy': 0,
        'maximum_consecutive_unhealthy': 0,
        'network_interruptions': 0,
        'network_recoveries': 0,
        'renewal_attempts': 0,
        'renewal_successes': 0,
        'renewal_failures': 0,
        'update_trials': 0,
        'update_confirmations': 0,
        'update_failures': 0,
        'update_rollbacks': 0,
        'power_interruptions': 0,
        'power_recoveries': 0,
        'power_failures': 0,
        'native_recoveries_attempts': 0,
        'native_recoveries_successes': 0,
        'native_recoveries_failures': 0,
        'watchdog_recoveries_attempts': 0,
        'watchdog_recoveries_successes': 0,
        'watchdog_recoveries_failures': 0,
        'identity_transactions_attempts': 0,
        'identity_transactions_successes': 0,
        'identity_transactions_failures': 0,
        'fleet_transactions_attempts': 0,
        'fleet_transactions_successes': 0,
        'fleet_transactions_failures': 0,
        'migration_rollbacks_attempts': 0,
        'migration_rollbacks_successes': 0,
        'migration_rollbacks_failures': 0,
        'driver_checks_attempts': 0,
        'driver_checks_successes': 0,
        'driver_checks_failures': 0,
    }


def _empty_state(started_at, release_version='', release_sequence=0):
    return {
        'state_version': STATE_VERSION,
        'release_version': release_version,
        'release_sequence': release_sequence,
        'started_at': started_at,
        'last_sample_at': started_at,
        'minimum_storage_free_bytes': None,
        'maximum_network_recovery_s': 0,
        'network_up': None,
        'network_outage_started_at': 0,
        'canary_paused': False,
        'counters': _counters(),
    }


def _bounded_increment(value):
    return min(MAX_COUNTER, int(value) + 1)


def _decode(payload):
    if not payload:
        return None
    try:
        value = json.loads(payload.decode())
    except Exception:
        raise QualificationError('qualification state is invalid')
    template = _empty_state(1)
    if not isinstance(value, dict) or set(value) != set(template):
        raise QualificationError('qualification state has invalid fields')
    if value['state_version'] != STATE_VERSION:
        raise QualificationError('qualification state version is unsupported')
    _text(value['release_version'], 'qualification state release', 48)
    _integer(value['release_sequence'], 'qualification state release sequence')
    for key in ('started_at', 'last_sample_at', 'maximum_network_recovery_s',
                'network_outage_started_at'):
        _integer(value[key], 'qualification ' + key.replace('_', ' '))
    minimum_free = value['minimum_storage_free_bytes']
    if minimum_free is not None:
        _integer(minimum_free, 'qualification minimum storage free bytes')
    if value['network_up'] not in (None, True, False):
        raise QualificationError('qualification network state is invalid')
    if value['canary_paused'] not in (True, False):
        raise QualificationError('qualification canary state is invalid')
    counters = value['counters']
    if not isinstance(counters, dict) or set(counters) != set(_counters()):
        raise QualificationError('qualification counters are invalid')
    for key in counters:
        _integer(counters[key], 'qualification counter ' + key, 0, MAX_COUNTER)
    return value


class OperationalQualification:
    """Record only observed evidence; never infer an unexecuted test passed."""

    def __init__(self, namespace, now, device_id, release_getter, profile=None):
        if not callable(now) or not callable(release_getter):
            raise QualificationError('qualification providers are unavailable')
        self._namespace = namespace
        self._now = now
        self._device_id = _text(str(device_id), 'qualification device id')
        self._release_getter = release_getter
        self._profile = validate_profile(profile or beta_profile())
        self._state = None

    def _save(self):
        generation, unused = self._namespace.snapshot()
        try:
            payload = json.dumps(
                self._state, sort_keys=True, separators=(',', ':')
            ).encode()
        except TypeError:
            payload = json.dumps(self._state).encode()
        self._namespace.commit(generation, payload)

    def _release(self):
        release = self._release_getter()
        if not isinstance(release, dict):
            raise QualificationError('qualification release is invalid')
        return {
            'version': _text(
                str(release.get('version', '')), 'qualification release', 48
            ),
            'sequence': _integer(
                int(release.get('sequence', 0)),
                'qualification release sequence'
            ),
            'confirmed': bool(release.get('confirmed', False)),
        }

    def start(self):
        now = _integer(int(self._now()), 'qualification time', 1)
        release = self._release()
        unused, payload = self._namespace.snapshot()
        self._state = _decode(payload) or _empty_state(
            now, release['version'], release['sequence']
        )
        changed_release = (
            self._state['release_version'] != release['version'] or
            self._state['release_sequence'] != release['sequence']
        )
        if changed_release:
            self._state = _empty_state(
                now, release['version'], release['sequence']
            )
        if not payload or changed_release:
            self._save()
        return self.snapshot()

    def reset(self):
        release = self._release()
        self._state = _empty_state(
            _integer(int(self._now()), 'qualification time', 1),
            release['version'], release['sequence']
        )
        self._save()
        return self.snapshot()

    def _require_started(self):
        if self._state is None:
            raise QualificationError('qualification recorder is not started')

    def sample(self, health_state, storage_free_bytes, network_up,
               canary_paused=False):
        self._require_started()
        if health_state not in (None, 'healthy', 'degraded', 'failed'):
            raise QualificationError('qualification health state is invalid')
        free = None
        if storage_free_bytes is not None:
            free = _integer(
                storage_free_bytes, 'qualification storage free bytes', 0,
                1073741824
            )
        if network_up not in (True, False) or canary_paused not in (True, False):
            raise QualificationError('qualification sample flags are invalid')
        now = _integer(int(self._now()), 'qualification time', 1)
        if now < self._state['last_sample_at']:
            raise QualificationError('qualification time moved backwards')
        counters = self._state['counters']
        counters['samples'] = _bounded_increment(counters['samples'])
        if health_state is not None:
            counters['health_samples'] = _bounded_increment(
                counters['health_samples']
            )
            if health_state == 'healthy':
                counters['consecutive_unhealthy'] = 0
            else:
                counters['unhealthy_samples'] = _bounded_increment(
                    counters['unhealthy_samples']
                )
                counters['consecutive_unhealthy'] = _bounded_increment(
                    counters['consecutive_unhealthy']
                )
                counters['maximum_consecutive_unhealthy'] = max(
                    counters['maximum_consecutive_unhealthy'],
                    counters['consecutive_unhealthy']
                )
        if free is not None:
            counters['storage_samples'] = _bounded_increment(
                counters['storage_samples']
            )
            minimum_free = self._state['minimum_storage_free_bytes']
            self._state['minimum_storage_free_bytes'] = (
                free if minimum_free is None else min(minimum_free, free)
            )
        previous_network = self._state['network_up']
        if previous_network is True and not network_up:
            counters['network_interruptions'] = _bounded_increment(
                counters['network_interruptions']
            )
            self._state['network_outage_started_at'] = now
        elif previous_network is False and network_up:
            counters['network_recoveries'] = _bounded_increment(
                counters['network_recoveries']
            )
            started = self._state['network_outage_started_at']
            recovery = max(0, now - started) if started else 0
            self._state['maximum_network_recovery_s'] = max(
                self._state['maximum_network_recovery_s'], recovery
            )
            self._state['network_outage_started_at'] = 0
        self._state['network_up'] = network_up
        self._state['canary_paused'] = canary_paused
        self._state['last_sample_at'] = now
        self._save()
        return self.snapshot()

    def record_renewal(self, successful):
        self._record_boolean('renewal', successful)

    def record_update(self, outcome):
        self._require_started()
        if outcome not in ('confirmed', 'failed', 'rolled-back'):
            raise QualificationError('qualification update outcome is invalid')
        counters = self._state['counters']
        counters['update_trials'] = _bounded_increment(counters['update_trials'])
        key = {
            'confirmed': 'update_confirmations',
            'failed': 'update_failures',
            'rolled-back': 'update_rollbacks',
        }[outcome]
        counters[key] = _bounded_increment(counters[key])
        self._save()

    def record_power_recovery(self, successful):
        self._record_boolean('power', successful)

    def record_validation(self, name, successful):
        self._require_started()
        if name not in VALIDATION_COUNTERS or successful not in (True, False):
            raise QualificationError('qualification validation is invalid')
        prefix = VALIDATION_COUNTERS[name]
        counters = self._state['counters']
        counters[prefix + '_attempts'] = _bounded_increment(
            counters[prefix + '_attempts']
        )
        outcome = prefix + ('_successes' if successful else '_failures')
        counters[outcome] = _bounded_increment(counters[outcome])
        self._save()

    def _record_boolean(self, kind, successful):
        self._require_started()
        if successful not in (True, False):
            raise QualificationError('qualification outcome is invalid')
        counters = self._state['counters']
        attempt_key = kind + ('_attempts' if kind == 'renewal' else '_interruptions')
        success_key = kind + ('_successes' if kind == 'renewal' else '_recoveries')
        failure_key = kind + '_failures'
        counters[attempt_key] = _bounded_increment(counters[attempt_key])
        counters[success_key if successful else failure_key] = _bounded_increment(
            counters[success_key if successful else failure_key]
        )
        self._save()

    def _gate(self, name, status, observed, required):
        return {
            'name': name, 'status': status,
            'observed': int(observed), 'required': int(required),
        }

    def snapshot(self):
        self._require_started()
        now = max(
            self._state['last_sample_at'],
            _integer(int(self._now()), 'qualification time', 1)
        )
        elapsed = max(0, now - self._state['started_at'])
        profile = self._profile
        counters = self._state['counters']
        soak_passed = elapsed >= profile['minimum_soak_s']
        gates = [self._gate(
            'soak', 'passed' if soak_passed else 'in-progress', elapsed,
            profile['minimum_soak_s']
        )]
        unhealthy = counters['maximum_consecutive_unhealthy']
        health_samples = counters['health_samples']
        health_status = (
            'failed' if unhealthy > profile['maximum_consecutive_unhealthy']
            else ('not-run' if not health_samples else
                  ('passed' if (
                      soak_passed and
                      health_samples >= profile['minimum_health_samples']
                  ) else 'in-progress'))
        )
        gates.append(self._gate(
            'health', health_status, health_samples,
            profile['minimum_health_samples']
        ))
        minimum_free = self._state['minimum_storage_free_bytes']
        storage_samples = counters['storage_samples']
        if minimum_free is None:
            storage_status = 'not-run'
        else:
            storage_status = (
                'failed' if minimum_free < profile['minimum_storage_free_bytes']
                else ('passed' if (
                    soak_passed and
                    storage_samples >= profile['minimum_storage_samples']
                ) else 'in-progress')
            )
        gates.append(self._gate(
            'storage', storage_status, storage_samples,
            profile['minimum_storage_samples']
        ))
        recoveries = counters['network_recoveries']
        active_outage = (
            max(0, now - self._state['network_outage_started_at'])
            if self._state['network_up'] is False and
            self._state['network_outage_started_at'] else 0
        )
        maximum_recovery = max(
            self._state['maximum_network_recovery_s'], active_outage
        )
        network_status = (
            'failed' if (
                maximum_recovery >
                profile['maximum_network_recovery_s']
            ) else ('passed' if recoveries >= profile['required_network_recoveries']
                    else ('not-run' if not counters['network_interruptions']
                          else 'in-progress'))
        )
        gates.append(self._gate(
            'network-recovery', network_status, recoveries,
            profile['required_network_recoveries']
        ))
        for name, counter, failure_counters, requirement in (
            ('certificate-renewal', 'renewal_successes',
             ('renewal_failures',), 'required_renewals'),
            ('paired-updates', 'update_confirmations',
             ('update_failures', 'update_rollbacks'),
             'required_update_confirmations'),
            ('power-recovery', 'power_recoveries',
             ('power_failures',), 'required_power_recoveries'),
        ):
            observed = counters[counter]
            attempts = {
                'certificate-renewal': counters['renewal_attempts'],
                'paired-updates': counters['update_trials'],
                'power-recovery': counters['power_interruptions'],
            }[name]
            status = (
                'failed' if any(counters[key] for key in failure_counters)
                else ('passed' if observed >= profile[requirement]
                else ('not-run' if attempts == 0 else 'in-progress')
                )
            )
            gates.append(self._gate(name, status, observed, profile[requirement]))
        release = self._release()
        if (
            self._state['release_version'] != release['version'] or
            self._state['release_sequence'] != release['sequence']
        ):
            raise QualificationError('qualification release changed; restart recorder')
        release_confirmed = release['confirmed']
        canary_status = (
            'failed' if self._state['canary_paused'] else
            ('passed' if counters['update_confirmations'] else 'not-run')
        )
        gates.append(self._gate(
            'canary-health', canary_status,
            0 if self._state['canary_paused'] else counters['update_confirmations'],
            1
        ))
        gates.append(self._gate(
            'release-confirmation',
            'passed' if release_confirmed else 'in-progress',
            1 if release_confirmed else 0, 1
        ))
        validation_requirements = {
            'native-recovery': 'required_native_recoveries',
            'watchdog-recovery': 'required_watchdog_recoveries',
            'identity-interoperability': 'required_identity_transactions',
            'fleet-interoperability': 'required_fleet_transactions',
            'migration-rollback': 'required_migration_rollbacks',
            'driver-hardware': 'required_driver_checks',
        }
        for name in (
            'native-recovery', 'watchdog-recovery',
            'identity-interoperability', 'fleet-interoperability',
            'migration-rollback', 'driver-hardware',
        ):
            prefix = VALIDATION_COUNTERS[name]
            attempts = counters[prefix + '_attempts']
            successes = counters[prefix + '_successes']
            failures = counters[prefix + '_failures']
            required = profile[validation_requirements[name]]
            status = (
                'failed' if failures else
                ('passed' if successes >= required else
                 ('not-run' if not attempts else 'in-progress'))
            )
            gates.append(self._gate(name, status, successes, required))
        result = {
            'contract_version': CONTRACT_VERSION,
            'profile': profile['name'],
            'device_id': self._device_id,
            'release': {
                'version': release['version'],
                'sequence': release['sequence'],
                'confirmed': release_confirmed,
            },
            'started_at': self._state['started_at'],
            'observed_at': now,
            'elapsed_s': elapsed,
            'counters': dict(counters),
            'measurements': {
                'minimum_storage_free_bytes': minimum_free,
                'maximum_network_recovery_s': maximum_recovery,
                'network_outage_open': self._state['network_up'] is False,
            },
            'gates': gates,
            'promotion_ready': all(item['status'] == 'passed' for item in gates),
        }
        return result
