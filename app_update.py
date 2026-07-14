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


MAGIC = b'HAMD1\n'
BASE_VERSION = '2.0.0'
BUNDLE_PATH = '.app-update.bundle'
STATE_PATH = '.app-update-state.json'
BACKUP_ROOT = '.app-update-backup'
VERSION_PATH = '.app-version'
CHUNK_SIZE = 1024
DEFAULT_MAX_BUNDLE_BYTES = 2 * 1024 * 1024
RECOVERY_FILES = ('main.py', 'app_update.py', 'firmware_update.py')


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


def stage_bundle(path=BUNDLE_PATH, allow_protected=False, selections=None):
    manifest = validate_bundle(path, allow_protected)
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
    selections=None
):
    content_length = int(content_length)
    if content_length < len(MAGIC) + 4 or content_length > int(max_bytes):
        raise ValueError('update bundle size is not allowed')
    temp_path = BUNDLE_PATH + '.upload'
    received = 0
    try:
        with open(temp_path, 'wb') as output:
            while received < content_length:
                chunk = await reader.read(min(CHUNK_SIZE, content_length - received))
                if not chunk:
                    raise ValueError('update upload ended early')
                output.write(chunk)
                received += len(chunk)
        validate_bundle(temp_path, allow_protected)
        _replace_file(temp_path, BUNDLE_PATH)
        return stage_bundle(BUNDLE_PATH, allow_protected, selections)
    except Exception:
        _remove_if_exists(temp_path)
        raise


def update_status():
    try:
        return _read_json(STATE_PATH)
    except Exception:
        return {'status': 'idle'}


def activate_pending():
    state = update_status()
    if state.get('status') == 'trial':
        rollback_update()
        return 'rolled back unconfirmed update'
    if state.get('status') == 'activating':
        rollback_update()
        return 'rolled back interrupted update'
    if state.get('status') != 'ready':
        return ''

    manifest = validate_bundle(BUNDLE_PATH, state.get('allow_protected', False))
    state['status'] = 'activating'
    state['applied'] = []
    _write_json_atomic(STATE_PATH, state)

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
            backup_path = BACKUP_ROOT + '/' + path
            existed = _file_exists(path)
            if existed:
                _copy_file(path, backup_path)
            state['applied'].append({'path': path, 'existed': existed})
            _write_json_atomic(STATE_PATH, state)
            _write_stream_file(stream, size, path)

    state['status'] = 'trial'
    _write_json_atomic(STATE_PATH, state)
    return 'activated update ' + str(state.get('version', ''))


def confirm_update():
    state = update_status()
    if state.get('status') != 'trial':
        return False
    if state.get('has_application') and state.get('version'):
        _write_text_atomic(VERSION_PATH, str(state.get('version')))
    _remove_tree(BACKUP_ROOT)
    _remove_if_exists(BUNDLE_PATH)
    _remove_if_exists(STATE_PATH)
    return True


def running_version(fallback=''):
    try:
        with open(VERSION_PATH, 'r') as stream:
            value = stream.read().strip()
            return value or fallback
    except Exception:
        return fallback


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
    _remove_tree(BACKUP_ROOT)
    _remove_if_exists(BUNDLE_PATH)
    _remove_if_exists(STATE_PATH)
    return bool(applied)


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
