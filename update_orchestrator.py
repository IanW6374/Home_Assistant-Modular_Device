"""Persistent firmware/application release-set orchestration."""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

import release_update
import update_security


STATE_PATH = '.paired-update-state.json'
FORMAT_VERSION = 1


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _write(state, path=STATE_PATH):
    temporary = path + '.tmp'
    with open(temporary, 'w') as stream:
        json.dump(state, stream)
    _replace(temporary, path)


def load(path=STATE_PATH):
    try:
        with open(path, 'r') as stream:
            state = json.load(stream)
        if not isinstance(state, dict) or state.get('format_version') != FORMAT_VERSION:
            raise ValueError('paired update state has an invalid format')
        releases = state.get('releases')
        if not isinstance(releases, list) or not releases:
            raise ValueError('paired update state has no releases')
        for release in releases:
            update_security.validate_release_descriptor(
                release, release.get('channel', ''), check_compatibility=False
            )
        return state
    except Exception:
        return {}


def clear(path=STATE_PATH):
    try:
        os.remove(path)
    except OSError:
        pass


def begin(releases, application_sequence=0, firmware_sequence=0,
          application_version='', firmware_version='', path=STATE_PATH):
    releases = list(releases)
    if not releases:
        clear(path)
        return {}
    for release in releases:
        update_security.validate_release_descriptor(
            release, release.get('channel', ''), check_compatibility=False
        )
    state = {
        'format_version': FORMAT_VERSION,
        'status': 'planned',
        'releases': releases,
        'active_type': '',
        'completed': [],
        'last_error': '',
    }
    _refresh_state(
        state, application_sequence, firmware_sequence,
        application_version, firmware_version
    )
    if state['status'] == 'complete':
        clear(path)
        return state
    if not state.get('active_type'):
        clear(path)
        return {}
    _write(state, path)
    return state


def _refresh_state(state, application_sequence, firmware_sequence,
                   application_version, firmware_version):
    completed = []
    pending = []
    for release in state['releases']:
        release_type = release.get('type')
        installed_sequence = (
            application_sequence if release_type == 'application'
            else firmware_sequence
        )
        installed_version = (
            application_version if release_type == 'application'
            else firmware_version
        )
        offered = int(release.get('release_sequence', 0))
        installed = (
            offered <= int(installed_sequence)
            if int(installed_sequence) > 0 else
            str(release.get('version', '')) == str(installed_version)
        )
        (completed if installed else pending).append(release_type)
    state['completed'] = completed
    if not pending:
        state['status'] = 'complete'
        state['active_type'] = ''
        return state
    selected = release_update.select_release(
        state['releases'], application_sequence, firmware_sequence,
        application_version, firmware_version
    )
    state['active_type'] = selected.get('type', '') if selected else ''
    if state.get('status') not in ('staged', 'activating') or state.get('active_type') not in pending:
        state['status'] = 'planned'
    return state


def refresh(application_sequence=0, firmware_sequence=0,
            application_version='', firmware_version='', path=STATE_PATH):
    state = load(path)
    if not state:
        return {}
    previous_active = state.get('active_type')
    _refresh_state(
        state, application_sequence, firmware_sequence,
        application_version, firmware_version
    )
    if state['status'] == 'complete':
        clear(path)
    else:
        if previous_active and previous_active in state.get('completed', ()):
            state['status'] = 'planned'
        _write(state, path)
    return state


def next_release(path=STATE_PATH):
    state = load(path)
    if not state or state.get('status') == 'complete':
        return None
    active = state.get('active_type')
    return next(
        (release for release in state['releases'] if release.get('type') == active),
        None
    )


def mark_staged(release, path=STATE_PATH):
    state = load(path)
    if not state or state.get('active_type') != release.get('type'):
        return False
    state['status'] = 'staged'
    _write(state, path)
    return True


def mark_activating(release_type, path=STATE_PATH):
    state = load(path)
    if not state or state.get('active_type') != str(release_type):
        return False
    state['status'] = 'activating'
    _write(state, path)
    return True


def mark_failed(detail, path=STATE_PATH):
    state = load(path)
    if not state:
        return False
    state['status'] = 'failed'
    state['last_error'] = str(detail)[:192]
    _write(state, path)
    return True


def status(path=STATE_PATH):
    state = load(path)
    if not state:
        return {'status': 'idle', 'step': 0, 'total_steps': 0}
    completed = len(state.get('completed', ()))
    total = len(state.get('releases', ()))
    result = {
        'status': state.get('status', 'idle'),
        'step': min(total, completed + 1) if total else 0,
        'total_steps': total,
        'active_type': state.get('active_type', ''),
        'completed': list(state.get('completed', ())),
        'last_error': state.get('last_error', ''),
    }
    return result
