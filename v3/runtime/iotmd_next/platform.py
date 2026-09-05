"""Validated MicroPython adapter for the versioned native v3 platform ABI."""

EXPECTED_ABI_VERSION = 5


class PlatformContractError(RuntimeError):
    pass


def _mapping(value, name):
    if not isinstance(value, dict):
        raise PlatformContractError(name + ' must be a mapping')
    return value


def _exact_keys(value, name, required, optional=()):
    value = _mapping(value, name)
    required = tuple(required)
    allowed = required + tuple(optional)
    for key in required:
        if key not in value:
            raise PlatformContractError(name + ' is missing ' + key)
    for key in value:
        if key not in allowed:
            raise PlatformContractError(name + ' contains unknown ' + str(key))
    return value


def _boolean(value, name):
    if value is not True and value is not False:
        raise PlatformContractError(name + ' must be boolean')
    return value


def _bounded_string(value, name, maximum=32):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise PlatformContractError(name + ' is invalid')
    return value


def validate_capabilities(value):
    value = _exact_keys(
        value, 'platform capabilities',
        ('abi_version', 'board', 'runtime', 'security', 'memory', 'interfaces',
         'storage', 'updates', 'recovery', 'jobs', 'resources')
    )
    if value['abi_version'] != EXPECTED_ABI_VERSION:
        raise PlatformContractError('unsupported platform ABI version')

    board = _exact_keys(value['board'], 'board', ('target', 'revision'))
    if board['target'] != 'esp32-s3':
        raise PlatformContractError('unsupported platform target')
    _bounded_string(board['revision'], 'board revision')

    runtime = _exact_keys(
        value['runtime'], 'runtime', ('engine', 'version', 'platform_abi')
    )
    if runtime['engine'] != 'micropython':
        raise PlatformContractError('unsupported runtime engine')
    _bounded_string(runtime['version'], 'runtime version')
    if runtime['platform_abi'] != EXPECTED_ABI_VERSION:
        raise PlatformContractError('runtime platform ABI does not match')

    security = _exact_keys(
        value['security'], 'security',
        ('secure_boot', 'flash_encryption', 'encrypted_nvs')
    )
    for key in security:
        _boolean(security[key], 'security.' + key)

    memory = _exact_keys(
        value['memory'], 'memory',
        ('psram', 'psram_bytes', 'ota_partition_bytes')
    )
    _boolean(memory['psram'], 'memory.psram')
    for key in ('psram_bytes', 'ota_partition_bytes'):
        if not isinstance(memory[key], int) or memory[key] < 0:
            raise PlatformContractError('memory.' + key + ' is invalid')
    if memory['psram'] != bool(memory['psram_bytes']):
        raise PlatformContractError('PSRAM capability is inconsistent')

    interfaces = _exact_keys(
        value['interfaces'], 'interfaces',
        ('wifi', 'usb_device', 'usb_ncm_hardware', 'usb_ncm_runtime',
         'usb_ncm_available'),
        ('ethernet',)
    )
    for key in interfaces:
        _boolean(interfaces[key], 'interfaces.' + key)
    if interfaces['usb_ncm_available'] and not (
        interfaces['usb_device'] and interfaces['usb_ncm_hardware'] and
        interfaces['usb_ncm_runtime']
    ):
        raise PlatformContractError('USB NCM capability is inconsistent')

    storage = _exact_keys(
        value['storage'], 'storage',
        ('encrypted', 'transactional', 'max_namespaces', 'max_payload_bytes')
    )
    _boolean(storage['encrypted'], 'storage.encrypted')
    _boolean(storage['transactional'], 'storage.transactional')
    if storage['transactional'] and not storage['encrypted']:
        raise PlatformContractError('transactional storage must be encrypted')
    for key, minimum, maximum in (
        ('max_namespaces', 1, 16), ('max_payload_bytes', 512, 65536)
    ):
        number = storage[key]
        if (not isinstance(number, int) or isinstance(number, bool) or
                number < minimum or number > maximum):
            raise PlatformContractError('storage.' + key + ' is invalid')

    updates = _exact_keys(
        value['updates'], 'updates',
        ('paired_manifest', 'native_trial_observation',
         'native_trial_control', 'paired_trial', 'native_rollback')
    )
    for key in updates:
        _boolean(updates[key], 'updates.' + key)
    if updates['native_rollback'] and not updates['paired_trial']:
        raise PlatformContractError('native rollback requires paired trial')
    if updates['native_trial_control'] and not updates['native_trial_observation']:
        raise PlatformContractError(
            'native trial control requires native trial observation'
        )

    recovery = _exact_keys(
        value['recovery'], 'recovery',
        ('native_state', 'product_independent', 'signed_release', 'qualified')
    )
    for key in recovery:
        _boolean(recovery[key], 'recovery.' + key)
    if recovery['qualified'] and not (
            recovery['native_state'] and recovery['product_independent'] and
            recovery['signed_release']):
        raise PlatformContractError('native recovery capability is inconsistent')

    jobs = _exact_keys(
        value['jobs'], 'jobs',
        ('async_worker', 'max_pending', 'max_events', 'timeout_ms', 'qualified')
    )
    _boolean(jobs['async_worker'], 'jobs.async_worker')
    _boolean(jobs['qualified'], 'jobs.qualified')
    for key in ('max_pending', 'max_events'):
        number = jobs[key]
        if (not isinstance(number, int) or isinstance(number, bool) or
                number < 1 or number > 32):
            raise PlatformContractError('jobs.' + key + ' is invalid')
    timeout = jobs['timeout_ms']
    if (not isinstance(timeout, int) or isinstance(timeout, bool) or
            timeout < 100 or timeout > 60000):
        raise PlatformContractError('jobs.timeout_ms is invalid')
    if jobs['qualified'] and not jobs['async_worker']:
        raise PlatformContractError('native job capability is inconsistent')

    resources = _exact_keys(
        value['resources'], 'resources', (
            'managed', 'physical', 'shared_buses', 'interrupt_cleanup',
            'soft_restart_cleanup', 'recovery', 'qualified', 'max_claims',
            'kinds',
        )
    )
    for key in ('managed', 'physical', 'shared_buses', 'interrupt_cleanup',
                'soft_restart_cleanup', 'recovery', 'qualified'):
        _boolean(resources[key], 'resources.' + key)
    if resources['qualified'] and not all(
            resources[key] for key in (
                'managed', 'physical', 'shared_buses', 'interrupt_cleanup',
                'soft_restart_cleanup', 'recovery')):
        raise PlatformContractError('physical resource capability is inconsistent')
    maximum = resources['max_claims']
    if (not isinstance(maximum, int) or isinstance(maximum, bool) or
            maximum < 1 or maximum > 32):
        raise PlatformContractError('resources.max_claims is invalid')
    kinds = resources['kinds']
    allowed_kinds = ('adc', 'gpio', 'i2c', 'spi', 'uart')
    if (not isinstance(kinds, (list, tuple)) or not kinds or len(kinds) > 8 or
            len(set(kinds)) != len(kinds)):
        raise PlatformContractError('resources.kinds is invalid')
    for kind in kinds:
        if kind not in allowed_kinds:
            raise PlatformContractError('resources.kinds is invalid')
    if resources['managed'] and not kinds:
        raise PlatformContractError('managed resources require kinds')
    return value


class Platform:
    def __init__(self, provider=None):
        if provider is None:
            try:
                import _iotmd_platform_v3 as provider
            except ImportError:
                raise PlatformContractError('native v3 platform is unavailable')
        if getattr(provider, 'ABI_VERSION', None) != EXPECTED_ABI_VERSION:
            raise PlatformContractError('native v3 platform ABI is unsupported')
        if not hasattr(provider, 'capabilities'):
            raise PlatformContractError('native capability provider is incomplete')
        for operation in ('storage_open', 'storage_close', 'storage_snapshot',
                          'storage_commit'):
            if not hasattr(provider, operation):
                raise PlatformContractError(
                    'native transactional storage provider is incomplete'
                )
        for operation in ('resource_claim', 'resource_construct',
                          'resource_recover', 'resource_release',
                          'resource_release_owner', 'resource_reset',
                          'resource_snapshot'):
            if not hasattr(provider, operation):
                raise PlatformContractError(
                    'native resource provider is incomplete'
                )
        for operation in ('update_snapshot', 'update_confirm',
                          'update_rollback'):
            if not hasattr(provider, operation):
                raise PlatformContractError(
                    'native update provider is incomplete'
                )
        for operation in (
                'recovery_boot_begin', 'recovery_snapshot',
                'recovery_request', 'recovery_mark_healthy', 'recovery_clear'):
            if not hasattr(provider, operation):
                raise PlatformContractError(
                    'native recovery provider is incomplete'
                )
        for operation in ('job_submit', 'event_poll'):
            if not hasattr(provider, operation):
                raise PlatformContractError(
                    'native job provider is incomplete'
                )
        self._provider = provider

    def capabilities(self):
        return validate_capabilities(self._provider.capabilities())

    def update_snapshot(self):
        value = self._provider.update_snapshot()
        if not isinstance(value, dict) or set(value) != {
                'running_label', 'running_state', 'next_label',
                'pending_verify', 'can_confirm', 'can_rollback'}:
            raise PlatformContractError('native update snapshot is invalid')
        _bounded_string(value['running_label'], 'running OTA label', 16)
        if value['running_state'] not in (
                'new', 'pending-verify', 'valid', 'invalid', 'aborted',
                'undefined'):
            raise PlatformContractError('running OTA state is invalid')
        if value['next_label'] is not None:
            _bounded_string(value['next_label'], 'next OTA label', 16)
        for name in ('pending_verify', 'can_confirm', 'can_rollback'):
            _boolean(value[name], 'update.' + name)
        if value['can_confirm'] and not value['pending_verify']:
            raise PlatformContractError('native confirm state is inconsistent')
        if value['can_rollback'] and not value['pending_verify']:
            raise PlatformContractError('native rollback state is inconsistent')
        return value

    def confirm_update(self, expected_running_label):
        _bounded_string(expected_running_label, 'running OTA label', 16)
        return self._provider.update_confirm(expected_running_label) is True

    def rollback_update(self, expected_running_label):
        _bounded_string(expected_running_label, 'running OTA label', 16)
        return self._provider.update_rollback(expected_running_label)

    def recovery_boot_begin(self):
        value = self._provider.recovery_boot_begin()
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PlatformContractError('native recovery boot count is invalid')
        return value

    def recovery_snapshot(self):
        value = self._provider.recovery_snapshot()
        if not isinstance(value, dict) or set(value) != {
                'requested', 'reason', 'boot_pending', 'boot_count',
                'failed_boots', 'reset_reason'}:
            raise PlatformContractError('native recovery snapshot is invalid')
        _boolean(value['requested'], 'recovery.requested')
        if value['reason']:
            _bounded_string(value['reason'], 'recovery reason', 160)
        _boolean(value['boot_pending'], 'recovery.boot_pending')
        for key in ('boot_count', 'failed_boots', 'reset_reason'):
            if (not isinstance(value[key], int) or isinstance(value[key], bool) or
                    value[key] < 0):
                raise PlatformContractError('recovery.' + key + ' is invalid')
        return value

    def request_recovery(self, reason):
        _bounded_string(reason, 'recovery reason', 160)
        return self._provider.recovery_request(reason) is True

    def mark_recovery_healthy(self):
        return self._provider.recovery_mark_healthy() is True

    def clear_recovery(self):
        return self._provider.recovery_clear() is True

    def submit_job(self, kind, argument):
        _bounded_string(kind, 'native job kind', 24)
        _bounded_string(argument, 'native job argument', 160)
        value = self._provider.job_submit(kind, argument)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise PlatformContractError('native job identifier is invalid')
        return value

    def poll_event(self):
        value = self._provider.event_poll()
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {
                'id', 'kind', 'status', 'error', 'retryable', 'detail'}:
            raise PlatformContractError('native job event is invalid')
        if (not isinstance(value['id'], int) or isinstance(value['id'], bool) or
                value['id'] < 1):
            raise PlatformContractError('native job event identifier is invalid')
        _bounded_string(value['kind'], 'native job event kind', 24)
        if value['status'] not in (
                'running', 'completed', 'failed', 'restarting', 'observed'):
            raise PlatformContractError('native job event status is invalid')
        if not isinstance(value['error'], int) or isinstance(value['error'], bool):
            raise PlatformContractError('native job event error is invalid')
        _boolean(value['retryable'], 'native job event retryable')
        if value['detail']:
            _bounded_string(value['detail'], 'native job event detail', 96)
        return value

    @property
    def provider(self):
        return self._provider
