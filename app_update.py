"""Transactional application updates for MicroPython devices."""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii

import os
import sys
import update_security
import update_support

try:
    import asyncio
except ImportError:
    asyncio = None


MAGIC = b'HAMD1\n'
BUNDLE_PATH = '.app-update.bundle'
STATE_PATH = '.app-update-state.json'
BACKUP_ROOT = '.app-update-backup'
VERSION_PATH = '.app-version'
SLOT_ROOT = '.app-slots'
SLOT_STATE_PATH = '.app-slot-state.json'
SLOT_NAMES = ('a', 'b')
APPLICATION_ENTRY = 'HA-Device.py'
SLOT_INTEGRITY_FILE = '.slot-integrity.json'
CHUNK_SIZE = 1024
DEFAULT_MAX_BUNDLE_BYTES = 2 * 1024 * 1024
RECOVERY_FILES = (
    'main.py', 'recovery_boot.py', 'app_update.py', 'firmware_update.py',
    'hardware_platform.py', 'update_security.py', 'update_support.py',
    'wifi_recovery.py',
    '.update-signing-key'
)


def _hex_digest(hasher):
    return binascii.hexlify(hasher.digest()).decode()


def _safe_path(path):
    path = str(path).replace('\\', '/').lstrip('/')
    parts = path.split('/')
    if not path or any(part in ('', '.', '..') for part in parts):
        raise ValueError('unsafe update path: ' + str(path))
    if path in RECOVERY_FILES:
        raise ValueError('recovery file cannot be remotely updated: ' + path)
    return path


def is_protected_path(path):
    path = str(path).replace('\\', '/').lstrip('/')
    return path == 'secrets.py' or path.startswith('certs/')


def is_shared_path(path):
    path = str(path).replace('\\', '/').lstrip('/')
    return (
        path in ('device_settings.json', 'module_settings.json') or
        is_protected_path(path)
    )


def _slot_path(slot, path=''):
    if slot not in SLOT_NAMES:
        raise ValueError('invalid application slot: ' + str(slot))
    root = SLOT_ROOT + '/' + slot
    return root + '/' + path if path else root


def slot_status():
    try:
        state = _read_json(SLOT_STATE_PATH)
    except Exception:
        return {'active': '', 'versions': {}}
    active = state.get('active', '')
    if active not in SLOT_NAMES:
        active = ''
    versions = state.get('versions', {})
    if not isinstance(versions, dict):
        versions = {}
    return {'active': active, 'versions': versions}


def active_slot():
    state = slot_status()
    active = state.get('active', '')
    if (
        active and _file_exists(_slot_path(active, APPLICATION_ENTRY)) and
        validate_slot_integrity(active, entry_only=True)
    ):
        return active
    return ''


def previous_slot():
    slots = slot_status()
    current = slots.get('active', '')
    candidate = 'b' if current == 'a' else 'a'
    if candidate in SLOT_NAMES and _file_exists(_slot_path(candidate, APPLICATION_ENTRY)):
        return candidate
    return ''


def application_root():
    update = update_status()
    if update.get('status') in ('trial', 'committing'):
        trial = update.get('target_slot', '')
        if (
            trial in SLOT_NAMES and
            _file_exists(_slot_path(trial, APPLICATION_ENTRY)) and
            validate_slot_integrity(trial)
        ):
            return _slot_path(trial)
    active = active_slot()
    return _slot_path(active) if active else ''


def application_entry():
    root = application_root()
    return root + '/' + APPLICATION_ENTRY if root else APPLICATION_ENTRY


def prepare_application_path():
    root = application_root()
    if not root:
        return ''
    for path in list(sys.path):
        if str(path).startswith(SLOT_ROOT + '/'):
            try:
                sys.path.remove(path)
            except ValueError:
                pass
    sys.path.insert(0, root + '/lib')
    sys.path.insert(0, root)
    return root


def _read_exact(stream, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError('truncated update bundle')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def read_manifest(stream):
    if _read_exact(stream, len(MAGIC)) != MAGIC:
        raise ValueError('invalid update bundle magic')
    length_bytes = _read_exact(stream, 4)
    length = int.from_bytes(length_bytes, 'big')
    if length < 2 or length > 65535:
        raise ValueError('invalid update manifest length')
    manifest = json.loads(_read_exact(stream, length).decode())
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
        raise ValueError('invalid update manifest')
    update_security.validate_manifest('hamd', manifest)
    return manifest


def validate_bundle(path=BUNDLE_PATH, allow_protected=False):
    with open(path, 'rb') as stream:
        manifest = read_manifest(stream)
        seen = set()
        for entry in manifest['files']:
            file_path = _safe_path(entry.get('path', ''))
            if file_path in seen:
                raise ValueError('duplicate update path: ' + file_path)
            seen.add(file_path)
            if is_protected_path(file_path) and not allow_protected:
                raise ValueError('protected file requires explicit authorization: ' + file_path)
            size = int(entry.get('size', -1))
            expected = str(entry.get('sha256', '')).lower()
            if size < 0 or len(expected) != 64:
                raise ValueError('invalid update entry: ' + file_path)
            hasher = hashlib.sha256()
            remaining = size
            while remaining:
                chunk = stream.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError('truncated update file: ' + file_path)
                hasher.update(chunk)
                remaining -= len(chunk)
            if _hex_digest(hasher) != expected:
                raise ValueError('SHA-256 mismatch: ' + file_path)
        if stream.read(1):
            raise ValueError('unexpected data after update files')
    return manifest


async def _report_progress(callback, phase, completed, total):
    if not callback:
        return
    result = callback(phase, completed, total)
    if result is not None:
        await result


async def validate_bundle_async(path=BUNDLE_PATH, allow_protected=False, progress_callback=None):
    with open(path, 'rb') as stream:
        manifest = read_manifest(stream)
        total = sum(max(0, int(entry.get('size', 0))) for entry in manifest['files'])
        verified = 0
        await _report_progress(progress_callback, 'verification', verified, total)
        seen = set()
        for entry in manifest['files']:
            file_path = _safe_path(entry.get('path', ''))
            if file_path in seen:
                raise ValueError('duplicate update path: ' + file_path)
            seen.add(file_path)
            if is_protected_path(file_path) and not allow_protected:
                raise ValueError('protected file requires explicit authorization: ' + file_path)
            size = int(entry.get('size', -1))
            expected = str(entry.get('sha256', '')).lower()
            if size < 0 or len(expected) != 64:
                raise ValueError('invalid update entry: ' + file_path)
            hasher = hashlib.sha256()
            remaining = size
            while remaining:
                chunk = stream.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError('truncated update file: ' + file_path)
                hasher.update(chunk)
                remaining -= len(chunk)
                verified += len(chunk)
                await _report_progress(
                    progress_callback, 'verification', verified, total
                )
                if asyncio:
                    await asyncio.sleep(0)
            if _hex_digest(hasher) != expected:
                raise ValueError('SHA-256 mismatch: ' + file_path)
        if stream.read(1):
            raise ValueError('unexpected data after update files')
    return manifest


def selected_bundle_paths(manifest, selections=None):
    selections = selections or {}
    selected = []
    for entry in manifest.get('files', []):
        path = _safe_path(entry.get('path', ''))
        include = True
        if path == 'device_settings.json':
            include = bool(selections.get('device_settings', False))
        elif path == 'module_settings.json':
            include = bool(selections.get('module_settings', False))
        elif path == 'secrets.py':
            include = bool(selections.get('secrets', False))
        elif path.startswith('certs/'):
            include = bool(selections.get('certificates', False))
        if include:
            selected.append(path)
    return selected


def optional_bundle_groups(manifest):
    groups = []
    paths = [_safe_path(entry.get('path', '')) for entry in manifest.get('files', [])]
    if 'device_settings.json' in paths:
        groups.append('device_settings')
    if 'module_settings.json' in paths:
        groups.append('module_settings')
    if 'secrets.py' in paths:
        groups.append('secrets')
    if any(path.startswith('certs/') for path in paths):
        groups.append('certificates')
    return groups


def stage_bundle(path=BUNDLE_PATH, allow_protected=False, selections=None, manifest=None):
    manifest = manifest or validate_bundle(path, allow_protected)
    selected_paths = selected_bundle_paths(manifest, selections)
    has_application = any(
        path not in ('device_settings.json', 'module_settings.json') and
        not is_protected_path(path)
        for path in selected_paths
    )
    state = {
        'status': 'ready',
        'version': manifest.get('version', ''),
        'allow_protected': bool(allow_protected),
        'applied': [],
        'has_application': has_application,
        'selected_paths': selected_paths,
        'optional_groups': optional_bundle_groups(manifest)
    }
    _write_json_atomic(STATE_PATH, state)
    return state


def configure_pending_update(selections=None):
    state = update_status()
    if state.get('status') != 'ready':
        raise ValueError('no staged update')
    selections = selections or {}
    available = set(state.get('optional_groups', ()))
    requested = {key for key, value in selections.items() if value}
    if not requested.issubset(available):
        raise ValueError('selected overwrite is not present in staged update')
    if (
        ('secrets' in requested or 'certificates' in requested) and
        not state.get('allow_protected', False)
    ):
        raise ValueError('protected updates are disabled in device settings')

    manifest = validate_bundle(BUNDLE_PATH, state.get('allow_protected', False))
    selected_paths = selected_bundle_paths(manifest, selections)
    state['selected_paths'] = selected_paths
    state['has_application'] = any(
        path not in ('device_settings.json', 'module_settings.json') and
        not is_protected_path(path)
        for path in selected_paths
    )
    _write_json_atomic(STATE_PATH, state)
    return state


async def receive_bundle(
    reader,
    content_length,
    allow_protected=False,
    max_bytes=DEFAULT_MAX_BUNDLE_BYTES,
    selections=None,
    progress_callback=None
):
    content_length = int(content_length)
    if content_length < len(MAGIC) + 4 or content_length > int(max_bytes):
        raise ValueError('update bundle size is not allowed')
    update_support.acquire_update_lock()
    temp_path = BUNDLE_PATH + '.upload'
    received = 0
    try:
        update_support.require_free_space(content_length * 2)
        with open(temp_path, 'wb') as output:
            while received < content_length:
                chunk = await reader.read(min(CHUNK_SIZE, content_length - received))
                if not chunk:
                    raise ValueError('update upload ended early')
                output.write(chunk)
                received += len(chunk)
        manifest = await validate_bundle_async(
            temp_path, allow_protected, progress_callback
        )
        _replace_file(temp_path, BUNDLE_PATH)
        state = stage_bundle(
            BUNDLE_PATH, allow_protected, selections, manifest=manifest
        )
        update_support.record_update_event(
            'application', 'staged', state.get('version', ''),
            digest=str(manifest.get('signature', ''))
        )
        return state
    except Exception as exc:
        _remove_if_exists(temp_path)
        update_support.record_update_event('application', 'rejected', detail=str(exc))
        raise
    finally:
        update_support.release_update_lock()


def update_status():
    try:
        return _read_json(STATE_PATH)
    except Exception:
        return {'status': 'idle'}


def activate_pending():
    update_support.acquire_update_lock()
    try:
        return _activate_pending_locked()
    finally:
        update_support.release_update_lock()


def _activate_pending_locked():
    state = update_status()
    if state.get('status') == 'trial':
        rollback_update()
        return 'rolled back unconfirmed update'
    if state.get('status') == 'activating':
        rollback_update()
        return 'rolled back interrupted update'
    if state.get('status') == 'committing':
        _finish_commit(state)
        return 'completed interrupted update confirmation'
    if state.get('status') != 'ready':
        return ''

    manifest = validate_bundle(BUNDLE_PATH, state.get('allow_protected', False))
    selected_paths_for_update = set(state.get('selected_paths', ()))
    selected_size = sum(
        int(entry.get('size', 0)) for entry in manifest.get('files', [])
        if _safe_path(entry.get('path', '')) in selected_paths_for_update
    )
    backup_size = 0
    for path in selected_paths_for_update:
        if is_shared_path(path) and _file_exists(path):
            try:
                backup_size += int(os.stat(path)[6])
            except Exception:
                pass
    update_support.require_free_space(selected_size + backup_size)
    current_slot = active_slot()
    target_slot = ''
    if state.get('has_application'):
        target_slot = 'b' if current_slot == 'a' else 'a'
    state['status'] = 'activating'
    state['applied'] = []
    state['previous_slot'] = current_slot
    state['target_slot'] = target_slot
    _write_json_atomic(STATE_PATH, state)

    if target_slot:
        _remove_tree(_slot_path(target_slot))

    with open(BUNDLE_PATH, 'rb') as stream:
        read_manifest(stream)
        configured_paths = state.get('selected_paths')
        if configured_paths is None:
            selected_paths = {
                _safe_path(entry.get('path', ''))
                for entry in manifest.get('files', [])
            }
        else:
            selected_paths = set(configured_paths)
        for entry in manifest['files']:
            path = _safe_path(entry['path'])
            size = int(entry['size'])
            if path not in selected_paths:
                _skip_stream(stream, size, path)
                continue
            if is_shared_path(path):
                backup_path = BACKUP_ROOT + '/' + path
                existed = _file_exists(path)
                if existed:
                    _copy_file(path, backup_path)
                state['applied'].append({'path': path, 'existed': existed})
                _write_json_atomic(STATE_PATH, state)
                _write_stream_file(stream, size, path)
            elif target_slot:
                _write_stream_file(stream, size, _slot_path(target_slot, path))
            else:
                _skip_stream(stream, size, path)

    if target_slot and not _file_exists(
        _slot_path(target_slot, APPLICATION_ENTRY)
    ):
        raise ValueError('application bundle has no ' + APPLICATION_ENTRY)

    if target_slot:
        integrity_entries = []
        for entry in manifest.get('files', []):
            entry_path = _safe_path(entry.get('path', ''))
            if entry_path in selected_paths and not is_shared_path(entry_path):
                integrity_entries.append({
                    'path': entry_path,
                    'size': int(entry.get('size', 0)),
                    'sha256': str(entry.get('sha256', '')).lower()
                })
        _write_json_atomic(
            _slot_path(target_slot, SLOT_INTEGRITY_FILE),
            {'files': integrity_entries}
        )
        if not validate_slot_integrity(target_slot):
            raise ValueError('application slot integrity verification failed')

    state['status'] = 'trial'
    _write_json_atomic(STATE_PATH, state)
    update_support.record_update_event(
        'application', 'trial', state.get('version', ''),
        digest=str(manifest.get('signature', ''))
    )
    return 'activated update ' + str(state.get('version', ''))


def confirm_update():
    state = update_status()
    if state.get('status') not in ('trial', 'committing'):
        return False
    if state.get('status') == 'trial':
        target = state.get('target_slot', '')
        if target and not validate_slot_integrity(target):
            raise ValueError('trial application slot failed integrity verification')
        state['status'] = 'committing'
        _write_json_atomic(STATE_PATH, state)
    _finish_commit(state)
    return True


def _finish_commit(state):
    target_slot = state.get('target_slot', '')
    if state.get('has_application'):
        if target_slot not in SLOT_NAMES or not _file_exists(
            _slot_path(target_slot, APPLICATION_ENTRY)
        ):
            raise ValueError('confirmed application slot is unavailable')
        slots = slot_status()
        versions = slots.get('versions', {})
        versions[target_slot] = str(state.get('version', ''))
        _write_json_atomic(SLOT_STATE_PATH, {
            'active': target_slot,
            'versions': versions
        })
        if state.get('version'):
            _write_text_atomic(VERSION_PATH, str(state.get('version')))
    _remove_tree(BACKUP_ROOT)
    _remove_if_exists(BUNDLE_PATH)
    _remove_if_exists(STATE_PATH)
    update_support.record_update_event(
        'application', 'confirmed', state.get('version', '')
    )


def running_version(fallback=''):
    slots = slot_status()
    active = slots.get('active', '')
    version = slots.get('versions', {}).get(active, '')
    if version:
        return str(version)
    try:
        with open(VERSION_PATH, 'r') as stream:
            value = stream.read().strip()
            return value or fallback
    except Exception:
        return fallback


def rollback_to_previous():
    update_support.acquire_update_lock()
    try:
        return _rollback_to_previous_locked()
    finally:
        update_support.release_update_lock()


def _rollback_to_previous_locked():
    if update_status().get('status') != 'idle':
        raise ValueError('cannot select a previous slot while an update is pending')
    current = active_slot()
    target = previous_slot()
    if not current or not target:
        raise ValueError('no previous application slot is available')
    slots = slot_status()
    _write_json_atomic(SLOT_STATE_PATH, {
        'active': target,
        'versions': slots.get('versions', {})
    })
    version = slots.get('versions', {}).get(target, '')
    if version:
        _write_text_atomic(VERSION_PATH, version)
    update_support.record_update_event(
        'application', 'manual_rollback', version,
        detail='from slot ' + current + ' to slot ' + target
    )
    return {'active': target, 'version': version, 'previous': current}


def rollback_update():
    state = update_status()
    applied = state.get('applied', [])
    for entry in reversed(applied):
        path = _safe_path(entry['path'])
        backup_path = BACKUP_ROOT + '/' + path
        if entry.get('existed') and _file_exists(backup_path):
            _copy_file(backup_path, path)
        elif not entry.get('existed'):
            _remove_if_exists(path)
    target_slot = state.get('target_slot', '')
    if target_slot in SLOT_NAMES:
        slots = slot_status()
        if slots.get('active') == target_slot:
            previous_slot = state.get('previous_slot', '')
            if previous_slot not in SLOT_NAMES or not _file_exists(
                _slot_path(previous_slot, APPLICATION_ENTRY)
            ):
                previous_slot = ''
            _write_json_atomic(SLOT_STATE_PATH, {
                'active': previous_slot,
                'versions': slots.get('versions', {})
            })
        _remove_tree(_slot_path(target_slot))
    _remove_tree(BACKUP_ROOT)
    _remove_if_exists(BUNDLE_PATH)
    _remove_if_exists(STATE_PATH)
    if applied or target_slot:
        update_support.record_update_event(
            'application', 'rolled_back', state.get('version', ''),
            detail='unconfirmed or interrupted ' + str(state.get('status', 'update'))
        )
    return bool(applied or target_slot)


def cleanup_interrupted():
    return update_support.cleanup_interrupted_files((
        BUNDLE_PATH + '.upload', STATE_PATH + '.tmp', SLOT_STATE_PATH + '.tmp',
        VERSION_PATH + '.tmp'
    ))


def validate_slot_integrity(slot, entry_only=False):
    path = _slot_path(slot, SLOT_INTEGRITY_FILE)
    if not _file_exists(path):
        # Slots created before integrity manifests were introduced remain
        # bootable and will be replaced on their next update.
        return True
    try:
        manifest = _read_json(path)
        entries = manifest.get('files', [])
        if not isinstance(entries, list) or not entries:
            return False
        checked_entry = False
        for entry in entries:
            relative = _safe_path(entry.get('path', ''))
            if entry_only and relative != APPLICATION_ENTRY:
                continue
            source = _slot_path(slot, relative)
            hasher = hashlib.sha256()
            size = 0
            with open(source, 'rb') as stream:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    hasher.update(chunk)
            if size != int(entry.get('size', -1)):
                return False
            if _hex_digest(hasher) != str(entry.get('sha256', '')).lower():
                return False
            if relative == APPLICATION_ENTRY:
                checked_entry = True
        return checked_entry if entry_only else True
    except Exception:
        return False


def _write_stream_file(stream, size, path):
    temp_path = path + '.update-tmp'
    _ensure_parent(path)
    with open(temp_path, 'wb') as output:
        remaining = size
        while remaining:
            chunk = stream.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError('truncated update file: ' + path)
            output.write(chunk)
            remaining -= len(chunk)
    _replace_file(temp_path, path)


def _skip_stream(stream, size, path):
    remaining = size
    while remaining:
        chunk = stream.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError('truncated update file: ' + path)
        remaining -= len(chunk)


def _copy_file(source, destination):
    _ensure_parent(destination)
    temp_path = destination + '.copy-tmp'
    with open(source, 'rb') as src, open(temp_path, 'wb') as dst:
        while True:
            chunk = src.read(CHUNK_SIZE)
            if not chunk:
                break
            dst.write(chunk)
    _replace_file(temp_path, destination)


def _replace_file(source, destination):
    _remove_if_exists(destination)
    os.rename(source, destination)


def _ensure_parent(path):
    parts = path.split('/')[:-1]
    current = ''
    for part in parts:
        current = part if not current else current + '/' + part
        try:
            os.mkdir(current)
        except OSError:
            pass


def _file_exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _read_json(path):
    with open(path, 'rb') as stream:
        return json.loads(stream.read())


def _write_json_atomic(path, value):
    temp_path = path + '.tmp'
    with open(temp_path, 'w') as stream:
        stream.write(json.dumps(value))
    _replace_file(temp_path, path)


def _write_text_atomic(path, value):
    temp_path = path + '.tmp'
    with open(temp_path, 'w') as stream:
        stream.write(str(value))
    _replace_file(temp_path, path)


def _remove_if_exists(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _remove_tree(path):
    try:
        entries = os.listdir(path)
    except OSError:
        return
    for name in entries:
        child = path + '/' + name
        try:
            mode = os.stat(child)[0]
            is_dir = bool(mode & 0x4000)
        except OSError:
            continue
        if is_dir:
            _remove_tree(child)
        else:
            _remove_if_exists(child)
    try:
        os.rmdir(path)
    except OSError:
        pass
