"""Verified ESP32 MicroPython application-partition OTA updates."""

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

try:
    import esp32
except ImportError:
    esp32 = None

import hardware_platform
import update_security
import update_support
try:
    import asyncio
except ImportError:
    asyncio = None


MAGIC = b'HAMF1\n'
STATE_PATH = '.firmware-update-state.json'
VERSION_PATH = '.firmware-version'
BLOCK_SIZE = 4096
MAX_MANIFEST_BYTES = 2048
DEFAULT_MAX_BYTES = 4 * 1024 * 1024


def _hex_digest(hasher):
    return binascii.hexlify(hasher.digest()).decode()


def _replace(source, target):
    try:
        os.remove(target)
    except OSError:
        pass
    os.rename(source, target)


def _write_json(path, value):
    temp = path + '.tmp'
    with open(temp, 'w') as stream:
        json.dump(value, stream)
    _replace(temp, path)


def _read_json(path):
    with open(path, 'r') as stream:
        return json.load(stream)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _partition_label(partition):
    return str(partition.info()[4])


def _running_partition():
    if esp32 is None:
        raise RuntimeError('ESP32 partition API is unavailable')
    return esp32.Partition(esp32.Partition.RUNNING)


def _target_partition():
    target = _running_partition().get_next_update()
    if target is None:
        raise RuntimeError('firmware has no inactive OTA partition')
    return target


def supported():
    return hardware_platform.firmware_ota_supported()


def update_status():
    try:
        return _read_json(STATE_PATH)
    except Exception:
        return {'status': 'idle'}


def running_version(fallback=''):
    try:
        with open(VERSION_PATH, 'r') as stream:
            return stream.read().strip() or fallback
    except Exception:
        return fallback


async def _read_exact(reader, size):
    result = bytearray()
    while len(result) < size:
        chunk = await reader.read(size - len(result))
        if not chunk:
            raise ValueError('firmware upload ended early')
        result.extend(chunk)
    return bytes(result)


async def _report_progress(callback, phase, completed, total):
    if not callback:
        return
    result = callback(phase, completed, total)
    if result is not None:
        await result


async def receive_bundle(
    reader, content_length, max_bytes=DEFAULT_MAX_BYTES, progress_callback=None
):
    update_support.acquire_update_lock()
    try:
        return await _receive_bundle_locked(
            reader, content_length, max_bytes, progress_callback
        )
    except Exception as exc:
        update_support.record_update_event('firmware', 'rejected', detail=str(exc))
        raise
    finally:
        update_support.release_update_lock()


async def _receive_bundle_locked(
    reader, content_length, max_bytes=DEFAULT_MAX_BYTES, progress_callback=None
):
    if not supported():
        raise ValueError('base firmware OTA is not supported by this runtime')
    content_length = int(content_length)
    if content_length < len(MAGIC) + 4 or content_length > int(max_bytes):
        raise ValueError('firmware bundle size is not allowed')
    if await _read_exact(reader, len(MAGIC)) != MAGIC:
        raise ValueError('invalid firmware bundle header')
    manifest_size = int.from_bytes(await _read_exact(reader, 4), 'big')
    if manifest_size <= 0 or manifest_size > MAX_MANIFEST_BYTES:
        raise ValueError('invalid firmware manifest size')
    try:
        manifest = json.loads((await _read_exact(reader, manifest_size)).decode())
    except Exception as exc:
        raise ValueError('invalid firmware manifest: ' + str(exc))

    update_security.validate_manifest('hamf', manifest)
    version = str(manifest.get('version', '')).strip()
    expected = str(manifest.get('sha256', '')).lower()
    image_size = int(manifest.get('size', 0))
    target_platform = str(manifest.get('platform', ''))
    if not version or len(expected) != 64 or image_size <= 0:
        raise ValueError('firmware manifest is incomplete')
    installed_version = running_version()
    if installed_version and version == installed_version:
        raise ValueError(
            'firmware version ' + version +
            ' is already running; build the replacement with a new version label'
        )
    if target_platform != 'esp32-s3':
        raise ValueError('firmware target platform is not supported')
    if hardware_platform.platform_id() != 'esp32-s3':
        raise ValueError('firmware requires ESP32-S3 hardware')
    expected_total = len(MAGIC) + 4 + manifest_size + image_size
    if content_length != expected_total:
        raise ValueError('firmware bundle length does not match manifest')

    target = _target_partition()
    partition_size = int(target.info()[3])
    if image_size > partition_size:
        raise ValueError('firmware image is larger than OTA partition')
    # Any write to the inactive partition invalidates a previously staged image.
    _remove(STATE_PATH)

    hasher = hashlib.sha256()
    block = bytearray(BLOCK_SIZE)
    block_number = 0
    block_used = 0
    remaining = image_size
    first_byte = None
    while remaining:
        chunk = await reader.read(min(1024, remaining))
        if not chunk:
            raise ValueError('firmware image ended early')
        if first_byte is None and chunk:
            first_byte = chunk[0]
        hasher.update(chunk)
        offset = 0
        while offset < len(chunk):
            count = min(BLOCK_SIZE - block_used, len(chunk) - offset)
            block[block_used:block_used + count] = chunk[offset:offset + count]
            block_used += count
            offset += count
            if block_used == BLOCK_SIZE:
                target.writeblocks(block_number, block)
                block_number += 1
                block_used = 0
        remaining -= len(chunk)

    if first_byte != 0xe9:
        raise ValueError('payload is not an ESP application image')
    if block_used:
        for index in range(block_used, BLOCK_SIZE):
            block[index] = 0xff
        target.writeblocks(block_number, block)
    if _hex_digest(hasher) != expected:
        raise ValueError('firmware image SHA-256 mismatch')

    verify = hashlib.sha256()
    verify_block = bytearray(BLOCK_SIZE)
    remaining = image_size
    block_number = 0
    verified = 0
    await _report_progress(
        progress_callback, 'verification', verified, image_size
    )
    while remaining:
        target.readblocks(block_number, verify_block)
        count = min(BLOCK_SIZE, remaining)
        verify.update(verify_block[:count])
        remaining -= count
        verified += count
        await _report_progress(
            progress_callback, 'verification', verified, image_size
        )
        block_number += 1
        if asyncio:
            await asyncio.sleep(0)
    if _hex_digest(verify) != expected:
        raise ValueError('firmware flash verification failed')

    state = {
        'status': 'ready',
        'version': version,
        'sha256': expected,
        'size': image_size,
        'target': _partition_label(target)
    }
    _write_json(STATE_PATH, state)
    update_support.record_update_event(
        'firmware', 'staged', version, digest=expected
    )
    return state


def activate_pending():
    update_support.acquire_update_lock()
    try:
        return _activate_pending_locked()
    finally:
        update_support.release_update_lock()


def _activate_pending_locked():
    state = update_status()
    if state.get('status') != 'ready':
        raise ValueError('no staged base firmware update')
    running = _running_partition()
    if _partition_label(running) == state.get('target'):
        # The boot selection may have completed while the state write or HTTP
        # response was interrupted.  Resume the health-confirmation phase
        # instead of treating the now-running staged partition as invalid.
        # Selecting it again also creates a valid otadata entry when ESP-IDF
        # booted ota_0 as the default because otadata was still empty.
        running.set_boot()
        state['status'] = 'trial'
        _write_json(STATE_PATH, state)
        update_support.record_update_event(
            'firmware', 'trial', state.get('version', ''),
            detail='recovered staged partition already running',
            digest=state.get('sha256', '')
        )
        return state
    target = running.get_next_update()
    if target is None:
        raise ValueError('firmware has no inactive OTA partition')
    if _partition_label(target) != state.get('target'):
        raise ValueError('staged OTA partition is no longer inactive')
    target.set_boot()
    state['status'] = 'trial'
    _write_json(STATE_PATH, state)
    update_support.record_update_event(
        'firmware', 'trial', state.get('version', ''), digest=state.get('sha256', '')
    )
    return state


def boot_status():
    state = update_status()
    if state.get('status') != 'trial' or esp32 is None:
        return state
    running = _partition_label(_running_partition())
    if running != state.get('target'):
        _remove(STATE_PATH)
        update_support.record_update_event(
            'firmware', 'rolled_back', state.get('version', ''),
            detail='bootloader returned to the previous OTA partition'
        )
        return {'status': 'rolled_back', 'version': state.get('version', '')}
    return state


def confirm_update():
    state = boot_status()
    if state.get('status') != 'trial':
        return False
    esp32.Partition.mark_app_valid_cancel_rollback()
    temp = VERSION_PATH + '.tmp'
    with open(temp, 'w') as stream:
        stream.write(str(state.get('version', '')))
    _replace(temp, VERSION_PATH)
    _remove(STATE_PATH)
    update_support.record_update_event(
        'firmware', 'confirmed', state.get('version', ''), digest=state.get('sha256', '')
    )
    return True


def cleanup_interrupted():
    return update_support.cleanup_interrupted_files((
        STATE_PATH + '.tmp', VERSION_PATH + '.tmp'
    ))
