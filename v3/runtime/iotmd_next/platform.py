"""Validated MicroPython adapter for the versioned native v3 platform ABI."""

EXPECTED_ABI_VERSION = 3


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
         'storage', 'updates', 'resources')
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
        ('paired_manifest', 'paired_trial', 'native_rollback')
    )
    for key in updates:
        _boolean(updates[key], 'updates.' + key)
    if updates['native_rollback'] and not updates['paired_trial']:
        raise PlatformContractError('native rollback requires paired trial')

    resources = _exact_keys(
        value['resources'], 'resources', ('managed', 'max_claims', 'kinds')
    )
    _boolean(resources['managed'], 'resources.managed')
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
        for operation in ('resource_claim', 'resource_release',
                          'resource_release_owner', 'resource_snapshot'):
            if not hasattr(provider, operation):
                raise PlatformContractError(
                    'native resource provider is incomplete'
                )
        self._provider = provider

    def capabilities(self):
        return validate_capabilities(self._provider.capabilities())

    @property
    def provider(self):
        return self._provider
