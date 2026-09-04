"""Previewed, isolated migration of authenticated v2 complete backups."""

try:
    import ujson as json
except ImportError:
    import json

MIGRATION_VERSION = 1
V2_BACKUP_VERSION = 2
PHASES = ('idle', 'preview', 'staged', 'trial', 'confirmed', 'rolled-back')
SECTIONS = ('credentials', 'module_settings', 'certificates_and_trust')
MAX_BACKUP_BYTES = 131072
MAX_FILES = 32


class MigrationError(RuntimeError):
    pass


def _text(value, name, maximum=64, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not value and not empty):
        raise MigrationError(name + ' is invalid')
    return value


def _fingerprint(value):
    value = _text(value, 'backup fingerprint', 64).lower()
    if len(value) != 64:
        raise MigrationError('backup fingerprint is invalid')
    try:
        int(value, 16)
    except ValueError:
        raise MigrationError('backup fingerprint is invalid')
    return value


def validate_v2_backup(value):
    """Validate already authenticated/decrypted v2 backup content."""
    if not isinstance(value, dict) or set(value) != {
            'format_version', 'created_at', 'metadata', 'credentials',
            'module_settings', 'files'}:
        raise MigrationError('v2 backup has invalid fields')
    if value['format_version'] != V2_BACKUP_VERSION:
        raise MigrationError('v2 backup version is unsupported')
    if (not isinstance(value['created_at'], int) or
            isinstance(value['created_at'], bool) or value['created_at'] < 0):
        raise MigrationError('v2 backup creation time is invalid')
    for name in ('metadata', 'credentials', 'module_settings', 'files'):
        if not isinstance(value[name], dict):
            raise MigrationError('v2 backup ' + name + ' is invalid')
    if len(value['credentials']) > 64:
        raise MigrationError('v2 backup credentials are too large')
    devices = value['module_settings'].get('devices', ())
    if not isinstance(devices, (list, tuple)) or len(devices) > 8:
        raise MigrationError('v2 backup modules are invalid')
    files = value['files']
    if len(files) > MAX_FILES:
        raise MigrationError('v2 backup contains too many protected files')
    total = 0
    for name, payload in files.items():
        _text(name, 'v2 backup file name', 64)
        if not isinstance(payload, (bytes, bytearray)) or len(payload) > 65536:
            raise MigrationError('v2 backup protected file is invalid')
        total += len(payload)
    try:
        total += len(json.dumps(value['credentials']).encode())
        total += len(json.dumps(value['module_settings']).encode())
    except Exception:
        raise MigrationError('v2 backup content is not serialisable')
    if total > MAX_BACKUP_BYTES:
        raise MigrationError('v2 backup exceeds the migration limit')
    return value


def _empty_state():
    return {
        'contract_version': MIGRATION_VERSION, 'phase': 'idle',
        'plan_id': '', 'fingerprint': '', 'source_device': '',
        'sections': [], 'warnings': [], 'failure': '',
    }


def validate_migration_state(value):
    if not isinstance(value, dict) or set(value) != set(_empty_state()):
        raise MigrationError('migration state has invalid fields')
    if value['contract_version'] != MIGRATION_VERSION or value['phase'] not in PHASES:
        raise MigrationError('migration state is unsupported')
    _text(value['plan_id'], 'migration plan id', 64, value['phase'] == 'idle')
    _text(value['fingerprint'], 'migration fingerprint', 64, value['phase'] == 'idle')
    if value['fingerprint']:
        _fingerprint(value['fingerprint'])
    _text(value['source_device'], 'migration source device', 64, True)
    sections = value['sections']
    if not isinstance(sections, list) or len(sections) > len(SECTIONS):
        raise MigrationError('migration sections are invalid')
    seen = set()
    for item in sections:
        if not isinstance(item, dict) or set(item) != {
                'name', 'count', 'handle', 'state'}:
            raise MigrationError('migration section has invalid fields')
        if item['name'] not in SECTIONS or item['name'] in seen:
            raise MigrationError('migration section is invalid')
        seen.add(item['name'])
        if (not isinstance(item['count'], int) or isinstance(item['count'], bool) or
                item['count'] < 0 or item['count'] > 64):
            raise MigrationError('migration section count is invalid')
        if (not isinstance(item['handle'], int) or isinstance(item['handle'], bool) or
                item['handle'] < 0):
            raise MigrationError('migration section handle is invalid')
        if item['state'] not in ('preview', 'staged', 'activated', 'discarded'):
            raise MigrationError('migration section state is invalid')
        if item['state'] in ('staged', 'activated') and item['handle'] < 1:
            raise MigrationError('migration section handle is missing')
    warnings = value['warnings']
    if (not isinstance(warnings, list) or len(warnings) > 8 or
            any(not isinstance(item, str) or not item or len(item) > 96
                for item in warnings)):
        raise MigrationError('migration warnings are invalid')
    _text(value['failure'], 'migration failure', 96, True)
    return value


def _encode(value):
    validate_migration_state(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    except TypeError:
        return json.dumps(value).encode()


def _decode(payload):
    if not payload:
        return _empty_state()
    try:
        return validate_migration_state(json.loads(payload.decode()))
    except MigrationError:
        raise
    except Exception:
        raise MigrationError('migration state is invalid')


class V2MigrationCoordinator:
    """Persist only plans and opaque v3 staging handles, never backup secrets."""

    def __init__(self, namespace, staging_adapter, plan_id_factory):
        for operation in ('stage', 'activate', 'discard'):
            if not callable(getattr(staging_adapter, operation, None)):
                raise MigrationError('migration staging adapter is incomplete')
        if not callable(plan_id_factory):
            raise MigrationError('migration plan id source is unavailable')
        self._namespace = namespace
        self._staging = staging_adapter
        self._plan_id_factory = plan_id_factory

    def state(self):
        unused, payload = self._namespace.snapshot()
        value = _decode(payload)
        return {
            'contract_version': value['contract_version'],
            'phase': value['phase'], 'plan_id': value['plan_id'],
            'fingerprint': value['fingerprint'],
            'source_device': value['source_device'],
            'sections': [dict(item) for item in value['sections']],
            'warnings': list(value['warnings']), 'failure': value['failure'],
        }

    def _commit(self, value):
        generation, unused = self._namespace.snapshot()
        self._namespace.commit(generation, _encode(value))
        return self.state()

    def preview(self, backup, fingerprint):
        backup = validate_v2_backup(backup)
        fingerprint = _fingerprint(fingerprint)
        current = self.state()
        if current['phase'] in ('staged', 'trial'):
            raise MigrationError('another migration is active')
        plan_id = _text(str(self._plan_id_factory()), 'migration plan id', 64)
        devices = backup['module_settings'].get('devices', ())
        warnings = []
        if not backup['credentials']:
            warnings.append('No credentials are present in the backup')
        if not devices:
            warnings.append('No module configuration is present in the backup')
        if not backup['files']:
            warnings.append('No certificate or trust material is present')
        state = {
            'contract_version': MIGRATION_VERSION, 'phase': 'preview',
            'plan_id': plan_id, 'fingerprint': fingerprint,
            'source_device': str(backup['metadata'].get('device_id', ''))[:64],
            'sections': [
                {'name': 'credentials', 'count': len(backup['credentials']),
                 'handle': 0, 'state': 'preview'},
                {'name': 'module_settings', 'count': len(devices),
                 'handle': 0, 'state': 'preview'},
                {'name': 'certificates_and_trust', 'count': len(backup['files']),
                 'handle': 0, 'state': 'preview'},
            ],
            'warnings': warnings, 'failure': '',
        }
        return self._commit(state)

    def stage(self, plan_id, backup, fingerprint):
        backup = validate_v2_backup(backup)
        current = self.state()
        if (current['phase'] != 'preview' or current['plan_id'] != plan_id or
                current['fingerprint'] != _fingerprint(fingerprint)):
            raise MigrationError('migration preview does not match')
        payloads = {
            'credentials': backup['credentials'],
            'module_settings': backup['module_settings'],
            'certificates_and_trust': backup['files'],
        }
        handles = []
        try:
            for item in current['sections']:
                handle = self._staging.stage(item['name'], payloads[item['name']])
                if not isinstance(handle, int) or isinstance(handle, bool) or handle < 1:
                    raise MigrationError('migration staging handle is invalid')
                item['handle'] = handle
                item['state'] = 'staged'
                handles.append(handle)
            current['phase'] = 'staged'
            return self._commit(current)
        except Exception:
            if handles:
                self._staging.discard(handles)
            raise

    def begin_trial(self, plan_id):
        current = self.state()
        if current['phase'] != 'staged' or current['plan_id'] != plan_id:
            raise MigrationError('migration is not staged')
        current['phase'] = 'trial'
        return self._commit(current)

    def finish_trial(self, plan_id, healthy, failure=''):
        current = self.state()
        if current['phase'] != 'trial' or current['plan_id'] != plan_id:
            raise MigrationError('migration is not in trial')
        handles = [item['handle'] for item in current['sections']]
        if healthy is True:
            self._staging.activate(handles)
            current['phase'] = 'confirmed'
            for item in current['sections']:
                item['state'] = 'activated'
        elif healthy is False:
            self._staging.discard(handles)
            current['phase'] = 'rolled-back'
            current['failure'] = str(failure)[:96] or 'v3 trial did not become healthy'
            for item in current['sections']:
                item['state'] = 'discarded'
        else:
            raise MigrationError('migration health decision must be boolean')
        return self._commit(current)
