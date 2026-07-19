"""Update authenticity and recovery compatibility checks.

The signing key is provisioned over USB at ``/.update-signing-key`` as either
32 raw bytes or 64 hexadecimal characters.  Once present, unsigned updates are
rejected.  Application bundles cannot update this protected recovery file.
"""

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii


RECOVERY_API_VERSION = 2
SIGNING_KEY_PATH = '.update-signing-key'
SIGNATURE_SCHEME = 'hmac-sha256'
TARGET_BOARD = 'esp32-s3'


def installed_recovery_api():
    """Return the API exported by the frozen recovery supervisor.

    Recovery firmware predating the explicit API contract is API 1.  Importing
    lazily avoids a circular import while recovery_boot starts app_update.
    """
    try:
        import recovery_boot
        return int(getattr(recovery_boot, 'RECOVERY_API_VERSION', 1))
    except Exception:
        return 1


def _hex(value):
    return binascii.hexlify(value).decode()


def _key_bytes(path=SIGNING_KEY_PATH):
    try:
        with open(path, 'rb') as stream:
            value = stream.read().strip()
    except OSError:
        return b''
    if len(value) == 64:
        try:
            value = binascii.unhexlify(value)
        except Exception:
            raise ValueError('update signing key is not valid hexadecimal')
    if len(value) < 32:
        raise ValueError('update signing key must contain at least 32 bytes')
    return bytes(value)


def signing_enabled(path=SIGNING_KEY_PATH):
    return bool(_key_bytes(path))


def signing_status(path=SIGNING_KEY_PATH):
    try:
        return 'required' if signing_enabled(path) else 'not provisioned'
    except Exception as exc:
        return 'invalid key: ' + str(exc)


def _hmac_sha256(key, message):
    block_size = 64
    if len(key) > block_size:
        key = hashlib.sha256(key).digest()
    key = key + (b'\x00' * (block_size - len(key)))
    inner = bytearray(block_size)
    outer = bytearray(block_size)
    for index in range(block_size):
        inner[index] = key[index] ^ 0x36
        outer[index] = key[index] ^ 0x5c
    return hashlib.sha256(outer + hashlib.sha256(inner + message).digest()).digest()


def _constant_time_equal(left, right):
    left = bytes(left)
    right = bytes(right)
    different = len(left) ^ len(right)
    length = min(len(left), len(right))
    for index in range(length):
        different |= left[index] ^ right[index]
    return different == 0


def manifest_message(bundle_type, manifest):
    """Return a deterministic signed representation of a bundle manifest."""
    fields = [
        str(bundle_type),
        str(manifest.get('format_version', 1)),
        str(manifest.get('target_board', manifest.get('platform', ''))),
        str(manifest.get('min_recovery_api', 1)),
        str(manifest.get('max_recovery_api', RECOVERY_API_VERSION)),
        str(manifest.get('version', '')),
    ]
    if bundle_type == 'hamd':
        entries = []
        for entry in manifest.get('files', []):
            entries.append((
                str(entry.get('path', '')),
                str(entry.get('size', '')),
                str(entry.get('sha256', '')).lower(),
            ))
        for entry in sorted(entries):
            fields.extend(entry)
    else:
        fields.extend((
            str(manifest.get('size', '')),
            str(manifest.get('sha256', '')).lower(),
        ))
    return ('\n'.join(fields) + '\n').encode()


def sign_manifest(bundle_type, manifest, key):
    return _hex(_hmac_sha256(bytes(key), manifest_message(bundle_type, manifest)))


def validate_manifest(bundle_type, manifest, key_path=SIGNING_KEY_PATH):
    format_version = int(manifest.get('format_version', 1))
    if format_version not in (1, 2):
        raise ValueError('unsupported update format version: ' + str(format_version))
    if bundle_type == 'hamd':
        minimum = int(manifest.get('min_recovery_api', 1))
        maximum = int(manifest.get('max_recovery_api', RECOVERY_API_VERSION))
        installed_api = installed_recovery_api()
        if installed_api < minimum or installed_api > maximum:
            raise ValueError(
                'update requires recovery API ' + str(minimum) + '..' + str(maximum) +
                '; installed API is ' + str(installed_api) +
                '. Install the matching base firmware (.hamf) first'
            )
    target = str(manifest.get('target_board', manifest.get('platform', '')))
    if format_version >= 2 and target != TARGET_BOARD:
        raise ValueError('update target board is not supported: ' + target)

    key = _key_bytes(key_path)
    signature = str(manifest.get('signature', '')).lower()
    scheme = str(manifest.get('signature_scheme', ''))
    if not key:
        return {'signed': False, 'required': False}
    if scheme != SIGNATURE_SCHEME or len(signature) != 64:
        raise ValueError('signed updates are required by this device')
    expected = sign_manifest(bundle_type, manifest, key)
    if not _constant_time_equal(signature.encode(), expected.encode()):
        raise ValueError('update signature verification failed')
    return {'signed': True, 'required': True}
