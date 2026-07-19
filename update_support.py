"""Shared storage, history, locking, and interrupted-update helpers."""

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


HISTORY_PATH = '.update-history.json'
MAX_HISTORY = 20
DEFAULT_STORAGE_RESERVE = 96 * 1024
_locked = False


def acquire_update_lock():
    global _locked
    if _locked:
        raise RuntimeError('another update is already in progress')
    _locked = True


def release_update_lock():
    global _locked
    _locked = False


def update_locked():
    return _locked


def storage_status(path='.'):
    try:
        values = os.statvfs(path)
        block_size = int(values[0])
        total = block_size * int(values[2])
        free = block_size * int(values[4])
        return {'total_bytes': total, 'free_bytes': free, 'available': True}
    except Exception:
        return {'total_bytes': 0, 'free_bytes': 0, 'available': False}


def require_free_space(required, reserve=DEFAULT_STORAGE_RESERVE, path='.'):
    status = storage_status(path)
    if status['available'] and status['free_bytes'] < int(required) + int(reserve):
        raise ValueError(
            'insufficient storage: need ' + str(int(required) + int(reserve)) +
            ' bytes, have ' + str(status['free_bytes'])
        )
    return status


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _read_history():
    try:
        with open(HISTORY_PATH, 'r') as stream:
            value = json.load(stream)
        return value if isinstance(value, list) else []
    except Exception:
        return []


def update_history():
    return _read_history()


def record_update_event(kind, event, version='', detail='', digest=''):
    try:
        history = _read_history()
        timestamp = 0
        try:
            timestamp = int(time.time()) if time else 0
        except Exception:
            pass
        history.append({
            'time': timestamp,
            'kind': str(kind),
            'event': str(event),
            'version': str(version),
            'detail': str(detail)[:160],
            'sha256': str(digest),
        })
        history = history[-MAX_HISTORY:]
        temp = HISTORY_PATH + '.tmp'
        with open(temp, 'w') as stream:
            json.dump(history, stream)
        _replace(temp, HISTORY_PATH)
        return True
    except Exception:
        return False


def remove_file(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def cleanup_interrupted_files(paths):
    removed = []
    for path in paths:
        if remove_file(path):
            removed.append(path)
    return removed
