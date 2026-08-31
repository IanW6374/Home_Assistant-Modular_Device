"""Reset-persistent staged boot state for the immutable recovery supervisor.

The compact record is mirrored to optional backup memory and an atomic flash
checkpoint.  Backup memory accelerates hang/reset diagnosis but is never the
only authoritative copy, because not every supported MicroPython build exposes
that facility.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

import hardware_platform


FORMAT_VERSION = 1
STATE_PATH = '.boot-state.json'
BACKUP_MAGIC = b'IOMDB1:'
MAX_BACKUP_BYTES = 768
MAX_REASON_CHARS = 192

BOOT_STAGES = (
    'reset',
    'platform',
    'persistent-state',
    'update-reconcile',
    'filesystem',
    'configuration',
    'certificates',
    'hardware',
    'network',
    'portal',
    'essential-services',
    'health-check',
    'running',
    'safe-mode',
)

DEVICE_STATES = (
    'booting', 'initialising', 'running', 'degraded',
    'safe', 'restarting', 'updating',
)


def _crc32(data):
    """Small dependency-free CRC32 suitable for the bounded backup record."""
    value = 0xffffffff
    for byte in data:
        value ^= byte
        for _index in range(8):
            value = (value >> 1) ^ (0xedb88320 if value & 1 else 0)
    return value ^ 0xffffffff


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _empty():
    return {
        'format_version': FORMAT_VERSION,
        'boot_count': 0,
        'checkpoint_generation': 0,
        'failure_count': 0,
        'incomplete': False,
        'healthy': False,
        'stage': 'reset',
        'device_state': 'booting',
        'reset_cause': '',
        'update_state': '',
        'free_heap': None,
        'minimum_free_heap': None,
        'reason': '',
    }


def _normalise(value):
    if not isinstance(value, dict):
        raise ValueError('boot state must be an object')
    if int(value.get('format_version', 0) or 0) != FORMAT_VERSION:
        raise ValueError('unsupported boot-state format')
    result = _empty()
    result.update(value)
    if result.get('stage') not in BOOT_STAGES:
        raise ValueError('invalid boot stage')
    if result.get('device_state') not in DEVICE_STATES:
        raise ValueError('invalid device state')
    result['boot_count'] = max(0, int(result.get('boot_count', 0) or 0))
    result['checkpoint_generation'] = max(
        0, int(result.get('checkpoint_generation', 0) or 0)
    )
    result['failure_count'] = max(0, int(result.get('failure_count', 0) or 0))
    result['incomplete'] = bool(result.get('incomplete'))
    result['healthy'] = bool(result.get('healthy'))
    result['reason'] = str(result.get('reason', ''))[:MAX_REASON_CHARS]
    result['reset_cause'] = str(result.get('reset_cause', ''))[:48]
    result['update_state'] = str(result.get('update_state', ''))[:48]
    for name in ('free_heap', 'minimum_free_heap'):
        raw = result.get(name)
        result[name] = None if raw is None else max(0, int(raw))
    return result


def _encode_backup(value):
    payload = json.dumps(_normalise(value)).encode()
    record = BACKUP_MAGIC + ('%08x' % _crc32(payload)).encode() + b':' + payload
    if len(record) > MAX_BACKUP_BYTES:
        raise ValueError('boot-state backup record is too large')
    return record


def _decode_backup(record):
    record = bytes(record or b'')
    if not record.startswith(BACKUP_MAGIC):
        raise ValueError('backup record magic is invalid')
    checksum_end = len(BACKUP_MAGIC) + 8
    if len(record) <= checksum_end or record[checksum_end:checksum_end + 1] != b':':
        raise ValueError('backup record framing is invalid')
    expected = int(record[len(BACKUP_MAGIC):checksum_end], 16)
    payload = record[checksum_end + 1:]
    if _crc32(payload) != expected:
        raise ValueError('backup record checksum is invalid')
    return _normalise(json.loads(payload.decode()))


class BootStateStore:
    """Own the boot record and enforce forward-only normal boot stages."""

    def __init__(self, path=STATE_PATH, platform=hardware_platform):
        self.path = path
        self.platform = platform
        self.data = self._load()

    def _load_flash(self):
        with open(self.path, 'r') as stream:
            return _normalise(json.load(stream))

    def _load_backup(self):
        return _decode_backup(self.platform.backup_memory_read())

    def _load(self):
        flash = None
        backup = None
        try:
            flash = self._load_flash()
        except Exception:
            pass
        try:
            backup = self._load_backup()
        except Exception:
            pass
        backup_position = (
            int(backup.get('boot_count', 0) or 0),
            int(backup.get('checkpoint_generation', 0) or 0),
        ) if backup else (-1, -1)
        flash_position = (
            int(flash.get('boot_count', 0) or 0),
            int(flash.get('checkpoint_generation', 0) or 0),
        ) if flash else (-1, -1)
        if backup and backup_position >= flash_position:
            return backup
        return flash or _empty()

    def _write_flash(self):
        temporary = self.path + '.tmp'
        try:
            with open(temporary, 'w') as stream:
                json.dump(self.data, stream)
            _replace(temporary, self.path)
            return True
        except Exception:
            try:
                os.remove(temporary)
            except OSError:
                pass
            return False

    def checkpoint(self, durable=False):
        self.data['checkpoint_generation'] = int(
            self.data.get('checkpoint_generation', 0) or 0
        ) + 1
        backup_written = False
        try:
            backup_written = bool(
                self.platform.backup_memory_write(_encode_backup(self.data))
            )
        except Exception:
            backup_written = False
        # Significant transitions always reach flash.  On builds without
        # backup memory every stage is persisted so the recovery console can
        # identify the exact point reached before a reset.
        flash_written = self._write_flash() if durable or not backup_written else False
        return backup_written or flash_written

    def begin(self, reset_cause='', update_state=''):
        previous_incomplete = bool(self.data.get('incomplete'))
        failures = int(self.data.get('failure_count', 0) or 0)
        if previous_incomplete:
            failures += 1
        boot_count = int(self.data.get('boot_count', 0) or 0) + 1
        self.data = _empty()
        self.data.update({
            'boot_count': boot_count,
            'failure_count': failures,
            'incomplete': True,
            'stage': 'reset',
            'device_state': 'booting',
            'reset_cause': str(reset_cause)[:48],
            'update_state': str(update_state)[:48],
        })
        self.observe_heap()
        self.checkpoint(durable=True)
        return self.snapshot()

    def stage(self, name, device_state=None, reason='', update_state=None,
              durable=False):
        name = str(name)
        if name not in BOOT_STAGES:
            raise ValueError('unknown boot stage: ' + name)
        current = str(self.data.get('stage', 'reset'))
        if name not in ('safe-mode', 'reset') and current != 'safe-mode':
            if BOOT_STAGES.index(name) < BOOT_STAGES.index(current):
                raise ValueError('boot stage cannot move backwards: ' + current + ' -> ' + name)
        if device_state is not None:
            device_state = str(device_state)
            if device_state not in DEVICE_STATES:
                raise ValueError('unknown device state: ' + device_state)
            self.data['device_state'] = device_state
        self.data['stage'] = name
        if reason:
            self.data['reason'] = str(reason)[:MAX_REASON_CHARS]
        if update_state is not None:
            self.data['update_state'] = str(update_state)[:48]
        self.observe_heap(checkpoint=False)
        self.checkpoint(durable=durable)
        return self.snapshot()

    def observe_heap(self, free_bytes=None, checkpoint=False):
        if free_bytes is None:
            try:
                free_bytes = self.platform.heap_capability().get('gc_free_bytes')
            except Exception:
                free_bytes = None
        if free_bytes is not None:
            free_bytes = max(0, int(free_bytes))
            self.data['free_heap'] = free_bytes
            minimum = self.data.get('minimum_free_heap')
            if minimum is None or free_bytes < int(minimum):
                self.data['minimum_free_heap'] = free_bytes
            if checkpoint:
                self.checkpoint()
        return free_bytes

    def healthy(self, device_state='running'):
        self.data.update({
            'stage': 'running',
            'device_state': str(device_state),
            'incomplete': False,
            'healthy': True,
            'failure_count': 0,
            'reason': '',
            'update_state': '',
        })
        self.observe_heap()
        self.checkpoint(durable=True)
        return self.snapshot()

    def confirm_health(self):
        """Close the rollback window while application startup continues."""
        self.data.update({
            'stage': 'health-check',
            'device_state': 'initialising',
            'incomplete': False,
            'healthy': True,
            'failure_count': 0,
            'reason': '',
        })
        self.observe_heap()
        self.checkpoint(durable=True)
        return self.snapshot()

    def fail(self, reason, safe=False):
        increment = 1 if self.data.get('incomplete') else 0
        self.data.update({
            'stage': 'safe-mode' if safe else self.data.get('stage', 'reset'),
            'device_state': 'safe' if safe else 'restarting',
            'incomplete': False,
            'healthy': False,
            'failure_count': int(self.data.get('failure_count', 0) or 0) + increment,
            'reason': str(reason)[:MAX_REASON_CHARS],
        })
        self.observe_heap()
        self.checkpoint(durable=True)
        return self.snapshot()

    def degrade(self, reason):
        self.data['device_state'] = 'degraded'
        self.data['reason'] = str(reason)[:MAX_REASON_CHARS]
        self.checkpoint(durable=True)
        return self.snapshot()

    def snapshot(self):
        return json.loads(json.dumps(self.data))

    def clear(self):
        self.data = _empty()
        try:
            os.remove(self.path)
        except OSError:
            pass
        try:
            self.platform.backup_memory_clear()
        except Exception:
            pass
        return self.snapshot()


_store = None


def store():
    global _store
    if _store is None:
        _store = BootStateStore()
    return _store


def reset_store():
    global _store
    _store = None


def snapshot():
    return store().snapshot()
