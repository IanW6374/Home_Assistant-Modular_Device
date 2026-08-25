"""Signed universal core-and-application update container support."""

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

try:
    import uos as os
except ImportError:
    import os

import app_update
import firmware_update
import update_security
import update_support


MAGIC = b'IOTU1\n'
BUNDLE_TYPES = {MAGIC: 'iotuni'}
STATE_PATH = '.universal-update-state.json'
MAX_MANIFEST_BYTES = 4096
DEFAULT_MAX_BYTES = 4 * 1024 * 1024


def _hex_digest(hasher):
    return binascii.hexlify(hasher.digest()).decode()


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _replace(source, target):
    _remove(target)
    os.rename(source, target)


def _write_state(state):
    temporary = STATE_PATH + '.tmp'
    with open(temporary, 'w') as stream:
        json.dump(state, stream)
    _replace(temporary, STATE_PATH)


def update_status():
    try:
        with open(STATE_PATH, 'r') as stream:
            state = json.load(stream)
        return state if isinstance(state, dict) else {'status': 'idle'}
    except Exception:
        return {'status': 'idle'}


async def _read_exact(reader, size):
    result = bytearray()
    while len(result) < size:
        chunk = await reader.read(size - len(result))
        if not chunk:
            raise ValueError('universal update ended early')
        result.extend(chunk)
    return bytes(result)


async def _report(callback, phase, completed=0, total=0):
    if not callback:
        return
    result = callback(phase, completed, total)
    if result is not None:
        await result


class _ComponentReader:
    def __init__(self, reader, size):
        self.reader = reader
        self.remaining = int(size)
        self.count = 0
        self.hasher = hashlib.sha256()

    async def read(self, size):
        if self.remaining <= 0:
            return b''
        chunk = await self.reader.read(min(int(size), self.remaining))
        if not chunk:
            return b''
        self.remaining -= len(chunk)
        self.count += len(chunk)
        self.hasher.update(chunk)
        return chunk

    def hexdigest(self):
        return _hex_digest(self.hasher)


async def _consume_component(reader, phase, progress_callback=None):
    """Consume and hash an already-installed component without staging it."""
    total = reader.remaining
    while reader.remaining:
        chunk = await reader.read(min(4096, reader.remaining))
        if not chunk:
            break
        await _report(progress_callback, phase, reader.count, total)


def _component(manifest, name):
    value = manifest.get(name)
    if not isinstance(value, dict):
        raise ValueError('universal update has no ' + name + ' component')
    return value


async def _adopt_application_bundle(
    path, allow_protected=False, selections=None, progress_callback=None
):
    """Turn the compacted universal tail into the pending application."""
    update_support.acquire_update_lock()
    adopted = False
    try:
        manifest = await app_update.validate_bundle_async(
            path, allow_protected, progress_callback
        )
        if str(path) != app_update.BUNDLE_PATH:
            _replace(str(path), app_update.BUNDLE_PATH)
            adopted = True
        state = app_update.stage_bundle(
            app_update.BUNDLE_PATH, allow_protected, selections,
            manifest=manifest
        )
        update_support.record_update_event(
            'application', 'staged', state.get('version', ''),
            digest=str(manifest.get('signature', ''))
        )
        return state
    except Exception as exc:
        if adopted:
            _remove(app_update.BUNDLE_PATH)
            _remove(app_update.STATE_PATH)
        update_support.record_update_event(
            'application', 'rejected', detail=str(exc)
        )
        raise
    finally:
        update_support.release_update_lock()


async def receive_bundle(
    reader, content_length, max_bytes=DEFAULT_MAX_BYTES, progress_callback=None,
    firmware_receiver=None, application_receiver=None, application_adopter=None
):
    """Verify and stage both inner bundles from one streaming upload."""
    content_length = int(content_length)
    if content_length < len(MAGIC) + 4 or content_length > int(max_bytes):
        raise ValueError('universal update size is not allowed')
    bundle_type = BUNDLE_TYPES.get(await _read_exact(reader, len(MAGIC)))
    if not bundle_type:
        raise ValueError('invalid universal update header')
    manifest_size = int.from_bytes(await _read_exact(reader, 4), 'big')
    if manifest_size <= 0 or manifest_size > MAX_MANIFEST_BYTES:
        raise ValueError('invalid universal update manifest size')
    try:
        manifest = json.loads((await _read_exact(reader, manifest_size)).decode())
    except Exception as exc:
        raise ValueError('invalid universal update manifest: ' + str(exc))
    update_security.validate_universal_manifest(manifest, bundle_type=bundle_type)
    firmware = _component(manifest, 'firmware')
    application = _component(manifest, 'application')
    firmware_size = int(firmware.get('size', 0))
    application_size = int(application.get('size', 0))
    expected_total = len(MAGIC) + 4 + manifest_size + firmware_size + application_size
    if content_length != expected_total:
        raise ValueError('universal update length does not match its manifest')

    firmware_receiver = firmware_receiver or firmware_update.receive_bundle
    file_backed_application = (
        application_receiver is None and
        hasattr(reader, 'compact_remaining')
    )
    application_receiver = application_receiver or app_update.receive_bundle
    application_adopter = application_adopter or _adopt_application_bundle
    firmware_required = (
        firmware_update.running_release_sequence() <
        int(firmware.get('release_sequence', 0))
    )
    application_required = (
        app_update.running_release_sequence() <
        int(application.get('release_sequence', 0))
    )

    async def firmware_progress(phase, completed, total):
        await _report(
            progress_callback, 'firmware_' + str(phase), completed, total
        )

    async def application_progress(phase, completed, total):
        await _report(
            progress_callback, 'application_' + str(phase), completed, total
        )

    firmware_reader = _ComponentReader(reader, firmware_size)
    firmware_staged = False
    application_staged = False
    application_compacted = False
    try:
        if firmware_required:
            firmware_state = await firmware_receiver(
                firmware_reader, firmware_size, firmware_update.DEFAULT_MAX_BYTES,
                progress_callback=firmware_progress
            )
            firmware_staged = True
        else:
            await _consume_component(
                firmware_reader, 'firmware_verification', progress_callback
            )
            firmware_state = {
                'version': str(firmware.get('version', '')),
                'release_sequence': int(firmware.get('release_sequence', 0)),
            }
        if firmware_reader.remaining or firmware_reader.count != firmware_size:
            raise ValueError('universal core bundle ended early')
        if firmware_reader.hexdigest() != str(firmware.get('sha256', '')).lower():
            raise ValueError('universal core bundle SHA-256 mismatch')
        if (
            str(firmware_state.get('version', '')) != str(firmware.get('version', '')) or
            int(firmware_state.get('release_sequence', 0)) !=
            int(firmware.get('release_sequence', 0))
        ):
            raise ValueError('universal core metadata does not match the inner bundle')

        application_reader = _ComponentReader(reader, application_size)
        if application_required:
            # A resumable universal upload remains on the filesystem until
            # both components verify. If it crowds application staging,
            # discard only the inactive A/B generation; the active generation
            # is never touched.
            if not file_backed_application:
                try:
                    update_support.require_free_space(application_size)
                except ValueError:
                    reclaimed = app_update.reclaim_inactive_slot()
                    update_support.require_free_space(application_size)
                    if reclaimed:
                        update_support.record_update_event(
                            'application', 'reclaimed',
                            detail='inactive slot reclaimed for universal staging'
                        )
            if file_backed_application:
                adopted = await reader.compact_remaining(
                    application_size, application_progress
                )
                application_compacted = True
                application_reader.remaining = 0
                application_reader.count = application_size
                application_digest = str(adopted.get('sha256', '')).lower()
                if application_digest != str(
                    application.get('sha256', '')
                ).lower():
                    raise ValueError('universal application bundle SHA-256 mismatch')
                application_state = await application_adopter(
                    adopted.get('path', ''), False,
                    progress_callback=application_progress
                )
            else:
                application_state = await application_receiver(
                    application_reader, application_size, False,
                    app_update.DEFAULT_MAX_BUNDLE_BYTES,
                    progress_callback=application_progress
                )
            application_staged = True
        else:
            await _consume_component(
                application_reader, 'application_verification', progress_callback
            )
            application_state = {
                'version': str(application.get('version', '')),
                'release_sequence': int(application.get('release_sequence', 0)),
            }
        if application_reader.remaining or application_reader.count != application_size:
            raise ValueError('universal application bundle ended early')
        if (
            not application_compacted and
            application_reader.hexdigest() !=
            str(application.get('sha256', '')).lower()
        ):
            raise ValueError('universal application bundle SHA-256 mismatch')
        if (
            str(application_state.get('version', '')) != str(application.get('version', '')) or
            int(application_state.get('release_sequence', 0)) !=
            int(application.get('release_sequence', 0))
        ):
            raise ValueError('universal application metadata does not match the inner bundle')
        if not firmware_required and not application_required:
            raise ValueError('universal update is not newer than the installed release')
    except Exception:
        if application_staged:
            try:
                app_update.discard_pending_update()
            except Exception:
                pass
        if firmware_staged:
            try:
                firmware_update.discard_pending_update()
            except Exception:
                pass
        _remove(STATE_PATH)
        update_support.record_update_event(
            'universal', 'rejected', str(manifest.get('version', ''))
        )
        raise

    state = {
        'status': 'ready',
        'version': str(manifest.get('version', '')),
        'release_sequence': int(manifest.get('release_sequence', 0)),
        'firmware_version': str(firmware.get('version', '')),
        'firmware_sequence': int(firmware.get('release_sequence', 0)),
        'application_version': str(application.get('version', '')),
        'application_sequence': int(application.get('release_sequence', 0)),
        'firmware_required': firmware_required,
        'application_required': application_required,
        'activation_order': list(manifest.get(
            'activation_order', ('application', 'firmware')
        )),
        'maintenance_required': bool(manifest.get('maintenance_required')),
        'rollback_policy': str(manifest.get('rollback_policy', 'paired')),
        'trial_timeout_s': int(manifest.get('trial_timeout_s', 180)),
    }
    _write_state(state)
    update_support.record_update_event(
        'universal', 'staged', state['version']
    )
    await _report(progress_callback, 'complete', 1, 1)
    return state


def activate_pending(maintenance_allowed=True):
    state = update_status()
    if state.get('status') != 'ready':
        raise ValueError('no staged universal update')
    if state.get('maintenance_required') and not maintenance_allowed:
        raise ValueError('universal update requires an active maintenance window')
    application_required = state.get('application_required', True)
    firmware_required = state.get('firmware_required', True)
    if application_required and app_update.update_status().get('status') != 'ready':
        raise ValueError('universal application is not ready')
    if firmware_required and firmware_update.update_status().get('status') != 'ready':
        raise ValueError('universal core firmware is not ready')
    for component in state.get('activation_order', ('application', 'firmware')):
        if component == 'application' and application_required:
            app_update.configure_pending_update({})
        elif component == 'firmware' and firmware_required:
            firmware_update.activate_pending()
    state['status'] = 'activating'
    _write_state(state)
    update_support.record_update_event(
        'universal', 'trial', state.get('version', '')
    )
    return state


def trial_timeout_ms(default_ms=180000):
    state = update_status()
    if state.get('status') != 'activating':
        return int(default_ms)
    seconds = int(state.get('trial_timeout_s', int(default_ms) // 1000))
    return max(30000, min(3600000, seconds * 1000))


def confirm_update():
    state = update_status()
    if state.get('status') == 'idle':
        return False
    application_installed = (
        app_update.running_release_sequence() >=
        int(state.get('application_sequence', 0))
    )
    firmware_installed = (
        firmware_update.running_release_sequence() >=
        int(state.get('firmware_sequence', 0))
    )
    if application_installed and firmware_installed:
        _remove(STATE_PATH)
        update_support.record_update_event(
            'universal', 'confirmed', state.get('version', '')
        )
        return True
    return False


def discard_pending_update():
    state = update_status()
    discarded = False
    if (
        state.get('application_required', True) and
        app_update.update_status().get('status') == 'ready'
    ):
        discarded = bool(app_update.discard_pending_update()) or discarded
    if (
        state.get('firmware_required', True) and
        firmware_update.update_status().get('status') == 'ready'
    ):
        discarded = bool(firmware_update.discard_pending_update()) or discarded
    _remove(STATE_PATH)
    return discarded


def cleanup_interrupted():
    return update_support.cleanup_interrupted_files((STATE_PATH + '.tmp',))
