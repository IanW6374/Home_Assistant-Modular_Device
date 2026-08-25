"""Asymmetric update authenticity and recovery compatibility checks.

Only a public ECDSA P-256 verification key is provisioned on the device at
``/.update-verification-key``.  The private signing key remains offline.
"""

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii


RECOVERY_API_VERSION = 6
CORE_API_VERSION = 9
CONFIG_API_VERSION = 3
VERIFICATION_KEY_PATH = '.update-verification-key'
SIGNATURE_SCHEME = 'ecdsa-p256-sha256'
TARGET_BOARD = 'esp32-s3'

_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_A = _P - 3
_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
_GX = 0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296
_GY = 0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_G = (_GX, _GY)


def installed_recovery_api():
    return RECOVERY_API_VERSION


def installed_core_api():
    return CORE_API_VERSION


def _bytes_to_int(value):
    result = 0
    for byte in bytes(value):
        result = (result << 8) | byte
    return result


def _int_to_bytes(value, length=32):
    result = bytearray(length)
    for index in range(length - 1, -1, -1):
        result[index] = value & 0xff
        value >>= 8
    return bytes(result)


def _inverse(value, modulus):
    return pow(value % modulus, modulus - 2, modulus)


def _jacobian_double(point):
    x, y, z = point
    if y == 0 or z == 0:
        return (0, 1, 0)
    yy = (y * y) % _P
    yyyy = (yy * yy) % _P
    zz = (z * z) % _P
    s = (4 * x * yy) % _P
    m = (3 * x * x + _A * zz * zz) % _P
    nx = (m * m - 2 * s) % _P
    ny = (m * (s - nx) - 8 * yyyy) % _P
    nz = (2 * y * z) % _P
    return nx, ny, nz


def _jacobian_add_affine(point, affine):
    if point[2] == 0:
        return affine[0], affine[1], 1
    x1, y1, z1 = point
    x2, y2 = affine
    z1z1 = (z1 * z1) % _P
    u2 = (x2 * z1z1) % _P
    s2 = (y2 * z1 * z1z1) % _P
    h = (u2 - x1) % _P
    r = (2 * (s2 - y1)) % _P
    if h == 0:
        return _jacobian_double(point) if r == 0 else (0, 1, 0)
    i = (2 * h) * (2 * h) % _P
    j = h * i % _P
    v = x1 * i % _P
    nx = (r * r - j - 2 * v) % _P
    ny = (r * (v - nx) - 2 * y1 * j) % _P
    nz = ((z1 + h) * (z1 + h) - z1z1 - h * h) % _P
    return nx, ny, nz


def _to_affine(point):
    if point[2] == 0:
        return None
    inverse = _inverse(point[2], _P)
    inverse2 = inverse * inverse % _P
    return point[0] * inverse2 % _P, point[1] * inverse2 * inverse % _P


def _highest_bit(value):
    """Return the highest set bit without relying on CPython's int.bit_length."""
    value = int(value)
    bit = 0
    while value > 0:
        bit = 1 if bit == 0 else bit << 1
        value >>= 1
    return bit


def _scalar_multiply(scalar, point):
    result = (0, 1, 0)
    scalar = int(scalar)
    if scalar <= 0:
        return result
    bit = _highest_bit(scalar)
    while bit:
        result = _jacobian_double(result)
        if scalar & bit:
            result = _jacobian_add_affine(result, point)
        bit >>= 1
    return result


def _point_is_valid(point):
    if point is None:
        return False
    x, y = point
    return 0 <= x < _P and 0 <= y < _P and (
        y * y - (x * x * x + _A * x + _B)
    ) % _P == 0


def public_key_bytes(private_key):
    """Derive a raw 64-byte public key; intended for host provisioning tools."""
    private = _bytes_to_int(private_key)
    if not 1 <= private < _N:
        raise ValueError('update private key is outside the P-256 range')
    point = _to_affine(_scalar_multiply(private, _G))
    return _int_to_bytes(point[0]) + _int_to_bytes(point[1])


def _public_key(path=VERIFICATION_KEY_PATH):
    try:
        with open(path, 'rb') as stream:
            value = stream.read().strip()
    except OSError:
        try:
            import credential_store
            value = credential_store.update_verification_key()
        except Exception:
            value = b''
        if not value:
            return None
    if len(value) == 128:
        try:
            value = binascii.unhexlify(value)
        except Exception:
            raise ValueError('update verification key is not valid hexadecimal')
    if len(value) != 64:
        raise ValueError('update verification key must contain exactly 64 bytes')
    point = (_bytes_to_int(value[:32]), _bytes_to_int(value[32:]))
    if not _point_is_valid(point):
        raise ValueError('update verification key is not a valid P-256 point')
    return point


def signing_enabled(path=VERIFICATION_KEY_PATH):
    return _public_key(path) is not None


def signing_status(path=VERIFICATION_KEY_PATH):
    try:
        return 'required' if signing_enabled(path) else 'not provisioned'
    except Exception as exc:
        return 'invalid key: ' + str(exc)


def _component_fields(components):
    components = components if isinstance(components, dict) else {}
    modules = components.get('modules', {})
    if not isinstance(modules, dict):
        modules = {}
    fields = [str(components.get('runtime', '')), str(len(modules))]
    for name in sorted(modules):
        fields.extend((str(name), str(modules[name])))
    return fields


def validate_components(components):
    if not isinstance(components, dict):
        raise ValueError('application update has no signed component versions')
    if int(components.get('runtime', 0)) <= 0:
        raise ValueError('application runtime version must be positive')
    modules = components.get('modules')
    if not isinstance(modules, dict):
        raise ValueError('application module versions must be an object')
    allowed = 'abcdefghijklmnopqrstuvwxyz0123456789_'
    for name, version in modules.items():
        if (
            not isinstance(name, str) or not name or len(name) > 64 or
            any(character not in allowed for character in name)
        ):
            raise ValueError('application module version has an invalid name')
        if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
            raise ValueError('application module version must be a positive integer')
    return components


def manifest_message(bundle_type, manifest):
    format_version = int(manifest.get('format_version', 1))
    fields = [
        str(bundle_type),
        str(format_version),
        str(manifest.get('target_board', manifest.get('platform', ''))),
    ]
    if bundle_type in ('hamd', 'iotapp'):
        fields.extend((
            str(manifest.get('min_recovery_api', 1)),
            str(manifest.get('max_recovery_api', RECOVERY_API_VERSION)),
            str(manifest.get('version', '')),
        ))
        fields.extend((
            str(manifest.get('release_sequence', '')),
            str(manifest.get('minimum_core_api', '')),
            str(manifest.get('minimum_config_api', '')),
            str(manifest.get('maximum_config_api', '')),
        ))
        fields.extend(_component_fields(manifest.get('components')))
        entries = []
        for entry in manifest.get('files', []):
            entries.append((
                str(entry.get('path', '')),
                str(entry.get('size', '')),
                str(entry.get('sha256', '')).lower(),
            ))
        for entry in sorted(entries):
            fields.extend(entry)
    elif bundle_type in ('hamf', 'iotcore'):
        fields.append(str(manifest.get('version', '')))
        fields.extend((
            str(manifest.get('release_sequence', '')),
            str(manifest.get('minimum_core_api', '')),
        ))
        fields.extend((
            str(manifest.get('size', '')),
            str(manifest.get('sha256', '')).lower(),
        ))
    elif bundle_type in ('hamu', 'iotuni'):
        fields.extend((
            str(manifest.get('version', '')),
            str(manifest.get('release_sequence', '')),
        ))
        for name in ('firmware', 'application'):
            component = manifest.get(name, {})
            fields.extend((
                name,
                str(component.get('version', '')),
                str(component.get('release_sequence', '')),
                str(component.get('size', '')),
                str(component.get('sha256', '')).lower(),
            ))
        if format_version >= 2:
            fields.extend((
                ','.join(str(value) for value in manifest.get('activation_order', ())),
                str(bool(manifest.get('maintenance_required', False))),
                str(manifest.get('rollback_policy', '')),
                str(manifest.get('trial_timeout_s', '')),
            ))
    elif bundle_type == 'release':
        fields.extend((
            str(manifest.get('channel', '')),
            str(manifest.get('type', '')),
            str(manifest.get('version', '')),
            str(manifest.get('release_sequence', '')),
            str(manifest.get('url', '')),
            str(manifest.get('size', '')),
            str(manifest.get('sha256', '')).lower(),
            str(manifest.get('minimum_core_api', '')),
            str(manifest.get('minimum_config_api', '')),
            str(manifest.get('maximum_config_api', '')),
            str(manifest.get('notes', '')),
            str(manifest.get('published_at', '')),
        ))
        fields.extend(_component_fields(manifest.get('components')))
    elif bundle_type == 'fleet-policy':
        fields.extend((
            str(manifest.get('policy_sequence', '')),
            str(manifest.get('issued_at', '')),
            str(manifest.get('not_before', '')),
            str(manifest.get('expires_at', '')),
            str(manifest.get('target_device', '')),
            str(manifest.get('target_cohort', '')),
        ))
        maintenance = manifest.get('maintenance', {}) or {}
        weekdays = maintenance.get('weekdays', ()) or ()
        fields.extend((
            ','.join(str(value) for value in weekdays),
            str(maintenance.get('start_minute', '')),
            str(maintenance.get('duration_minutes', '')),
        ))
        updates = manifest.get('updates', {}) or {}
        fields.extend((
            str(updates.get('channel', '')),
            str(bool(updates.get('automatic_download', False))),
            str(bool(updates.get('automatic_activation', False))),
            str(updates.get('maximum_consecutive_failures', '')),
        ))
        telemetry = manifest.get('telemetry', {}) or {}
        fields.extend((
            str(bool(telemetry.get('enabled', False))),
            str(telemetry.get('minimum_interval_s', '')),
            ','.join(str(value) for value in telemetry.get('severities', ()) or ()),
        ))
        commands = manifest.get('commands', ()) or ()
        fields.append(str(len(commands)))
        for command in commands:
            fields.extend((
                str(command.get('id', '')),
                str(command.get('action', '')),
                str(command.get('release_sequence', '')),
            ))
    else:
        raise ValueError('unsupported signed message type: ' + str(bundle_type))
    return ('\n'.join(fields) + '\n').encode()


def _hmac_sha256(key, message):
    key = bytes(key)
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key += b'\x00' * (64 - len(key))
    inner = bytearray(64)
    outer = bytearray(64)
    for index in range(64):
        inner[index] = key[index] ^ 0x36
        outer[index] = key[index] ^ 0x5c
    return hashlib.sha256(outer + hashlib.sha256(inner + message).digest()).digest()


def _deterministic_nonce(private_key, digest):
    value = b'\x01' * 32
    key = b'\x00' * 32
    material = bytes(private_key) + bytes(digest)
    key = _hmac_sha256(key, value + b'\x00' + material)
    value = _hmac_sha256(key, value)
    key = _hmac_sha256(key, value + b'\x01' + material)
    value = _hmac_sha256(key, value)
    while True:
        value = _hmac_sha256(key, value)
        nonce = _bytes_to_int(value)
        if 1 <= nonce < _N:
            return nonce
        key = _hmac_sha256(key, value + b'\x00')
        value = _hmac_sha256(key, value)


def sign_message(message, private_key):
    """Sign canonical bytes on the host; private keys never go to devices."""
    private_key = bytes(private_key)
    private = _bytes_to_int(private_key)
    if len(private_key) != 32 or not 1 <= private < _N:
        raise ValueError('update private key must be a valid 32-byte P-256 scalar')
    digest = hashlib.sha256(bytes(message)).digest()
    nonce = _deterministic_nonce(private_key, digest)
    point = _to_affine(_scalar_multiply(nonce, _G))
    r = point[0] % _N
    s = (_inverse(nonce, _N) * (_bytes_to_int(digest) + r * private)) % _N
    if s > _N // 2:
        s = _N - s
    return binascii.hexlify(_int_to_bytes(r) + _int_to_bytes(s)).decode()


def sign_manifest(bundle_type, manifest, private_key):
    """Sign a current-format manifest on the host."""
    return sign_message(manifest_message(bundle_type, manifest), private_key)


def verify_message_signature(message, signature, public_key):
    try:
        raw_signature = binascii.unhexlify(signature)
    except Exception:
        return False
    if len(raw_signature) != 64:
        return False
    r = _bytes_to_int(raw_signature[:32])
    s = _bytes_to_int(raw_signature[32:])
    if not 1 <= r < _N or not 1 <= s <= _N // 2:
        return False
    digest = hashlib.sha256(bytes(message)).digest()
    inverse = _inverse(s, _N)
    first = _scalar_multiply(_bytes_to_int(digest) * inverse % _N, _G)
    second = _to_affine(_scalar_multiply(r * inverse % _N, public_key))
    if second is None:
        return False
    combined = _to_affine(_jacobian_add_affine(first, second))
    return combined is not None and combined[0] % _N == r


def verify_manifest_signature(bundle_type, manifest, signature, public_key):
    return verify_message_signature(
        manifest_message(bundle_type, manifest), signature, public_key
    )


def validate_manifest(bundle_type, manifest, key_path=VERIFICATION_KEY_PATH):
    format_version = int(manifest.get('format_version', 0))
    if format_version != 6:
        raise ValueError('unsupported update format version: ' + str(format_version))
    if bundle_type in ('hamd', 'iotapp'):
        validate_components(manifest.get('components'))
        minimum = int(manifest.get('min_recovery_api', 0))
        maximum = int(manifest.get('max_recovery_api', 0))
        installed_api = installed_recovery_api()
        if installed_api < minimum or installed_api > maximum:
            raise ValueError(
                'update requires recovery API ' + str(minimum) + '..' + str(maximum) +
                '; installed API is ' + str(installed_api) +
                '. Install the matching base firmware first'
            )
        sequence = int(manifest.get('release_sequence', 0))
        if sequence <= 0:
            raise ValueError('application update has no valid release sequence')
        minimum_core = int(manifest.get('minimum_core_api', 0))
        if installed_core_api() < minimum_core:
            raise ValueError(
                'application requires core API ' + str(minimum_core) +
                '; installed core API is ' + str(installed_core_api())
            )
        minimum_config = int(manifest.get('minimum_config_api', 0))
        maximum_config = int(manifest.get('maximum_config_api', 0))
        if not minimum_config <= CONFIG_API_VERSION <= maximum_config:
            raise ValueError(
                'application requires configuration API ' +
                str(minimum_config) + '..' + str(maximum_config) +
                '; installed API is ' + str(CONFIG_API_VERSION)
            )
    elif bundle_type in ('hamf', 'iotcore'):
        if int(manifest.get('release_sequence', 0)) <= 0:
            raise ValueError('firmware update has no valid release sequence')
        minimum_core = int(manifest.get('minimum_core_api', 0))
        if installed_core_api() < minimum_core:
            raise ValueError(
                'firmware update requires core API ' + str(minimum_core) +
                '; installed core API is ' + str(installed_core_api())
            )
    target = str(manifest.get('target_board', manifest.get('platform', '')))
    if target != TARGET_BOARD:
        raise ValueError('update target board is not supported: ' + target)

    public_key = _public_key(key_path)
    if public_key is None:
        raise ValueError('update verification key is not provisioned')
    signature = str(manifest.get('signature', '')).lower()
    scheme = str(manifest.get('signature_scheme', ''))
    if scheme != SIGNATURE_SCHEME or len(signature) != 128:
        raise ValueError('ECDSA-signed updates are required by this device')
    if not verify_manifest_signature(bundle_type, manifest, signature, public_key):
        raise ValueError('update signature verification failed')
    return {'signed': True, 'required': True}


def validate_universal_manifest(
    manifest, key_path=VERIFICATION_KEY_PATH, bundle_type='hamu'
):
    """Validate a signed manifest binding one core and one application bundle."""
    if bundle_type not in ('hamu', 'iotuni'):
        raise ValueError('universal update bundle type is invalid')
    if not isinstance(manifest, dict) or int(manifest.get('format_version', 0)) != 2:
        raise ValueError('unsupported universal update format')
    if str(manifest.get('target_board', '')) != TARGET_BOARD:
        raise ValueError('universal update target board is not supported')
    if not str(manifest.get('version', '')).strip():
        raise ValueError('universal update has no version')
    universal_version = str(manifest.get('version', '')).strip()
    sequence = int(manifest.get('release_sequence', 0))
    if sequence <= 0:
        raise ValueError('universal update has no valid release sequence')
    for name in ('firmware', 'application'):
        component = manifest.get(name)
        if not isinstance(component, dict):
            raise ValueError('universal update has no ' + name + ' component')
        if not str(component.get('version', '')).strip():
            raise ValueError('universal ' + name + ' has no version')
        if str(component.get('version', '')).strip() != universal_version:
            raise ValueError('universal component version labels do not match')
        if int(component.get('release_sequence', 0)) != sequence:
            raise ValueError('universal component release sequences do not match')
        if int(component.get('size', 0)) <= 0:
            raise ValueError('universal ' + name + ' size is invalid')
        digest = str(component.get('sha256', '')).lower()
        if len(digest) != 64 or any(
            character not in '0123456789abcdef' for character in digest
        ):
            raise ValueError('universal ' + name + ' SHA-256 is invalid')
    if manifest.get('activation_order') not in (
        ['application', 'firmware'], ['firmware', 'application']
    ):
        raise ValueError('universal activation order is invalid')
    if not isinstance(manifest.get('maintenance_required'), bool):
        raise ValueError('universal maintenance policy is invalid')
    if manifest.get('rollback_policy') not in ('paired', 'independent', 'manual'):
        raise ValueError('universal rollback policy is invalid')
    timeout = int(manifest.get('trial_timeout_s', 0))
    if timeout < 30 or timeout > 3600:
        raise ValueError('universal trial timeout is invalid')
    public_key = _public_key(key_path)
    if public_key is None:
        raise ValueError('update verification key is not provisioned')
    signature = str(manifest.get('signature', '')).lower()
    if (
        manifest.get('signature_scheme') != SIGNATURE_SCHEME or
        len(signature) != 128 or
        not verify_manifest_signature(bundle_type, manifest, signature, public_key)
    ):
        raise ValueError('universal update signature verification failed')
    return {'signed': True, 'required': True}


def validate_release_compatibility(descriptor):
    """Validate whether a structurally verified descriptor applies now."""
    minimum_core = int(descriptor.get('minimum_core_api', 0))
    if installed_core_api() < minimum_core:
        raise ValueError(
            'release requires core API ' + str(minimum_core) +
            '; installed core API is ' + str(installed_core_api())
        )
    minimum_config = int(descriptor.get('minimum_config_api', CONFIG_API_VERSION))
    maximum_config = int(descriptor.get('maximum_config_api', CONFIG_API_VERSION))
    if not minimum_config <= CONFIG_API_VERSION <= maximum_config:
        raise ValueError('release is incompatible with the installed configuration API')
    return descriptor


def release_is_compatible(descriptor):
    try:
        validate_release_compatibility(descriptor)
        return True
    except (TypeError, ValueError):
        return False


def validate_release_descriptor(
    descriptor, channel='', key_path=VERIFICATION_KEY_PATH, check_compatibility=True
):
    """Validate signed metadata used to discover remotely hosted bundles."""
    if not isinstance(descriptor, dict):
        raise ValueError('release descriptor must be an object')
    if int(descriptor.get('format_version', 0)) != 2:
        raise ValueError('unsupported release descriptor format')
    if str(descriptor.get('target_board', '')) != TARGET_BOARD:
        raise ValueError('release target board is not supported')
    release_channel = str(descriptor.get('channel', ''))
    if release_channel not in ('stable', 'beta'):
        raise ValueError('release descriptor channel is invalid')
    if channel and release_channel != str(channel):
        raise ValueError('release descriptor channel does not match the request')
    if descriptor.get('type') not in ('application', 'firmware'):
        raise ValueError('release descriptor type is invalid')
    if not str(descriptor.get('version', '')).strip():
        raise ValueError('release descriptor has no version')
    if int(descriptor.get('release_sequence', 0)) <= 0:
        raise ValueError('release descriptor has no valid release sequence')
    if not str(descriptor.get('url', '')).startswith('https://'):
        raise ValueError('release bundle URL must use HTTPS')
    if int(descriptor.get('size', 0)) <= 0:
        raise ValueError('release descriptor size is invalid')
    digest = str(descriptor.get('sha256', '')).lower()
    if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
        raise ValueError('release descriptor SHA-256 is invalid')
    if check_compatibility:
        validate_release_compatibility(descriptor)
    if descriptor.get('type') == 'application':
        validate_components(descriptor.get('components'))

    public_key = _public_key(key_path)
    if public_key is None:
        raise ValueError('update verification key is not provisioned')
    signature = str(descriptor.get('signature', '')).lower()
    if (
        descriptor.get('signature_scheme') != SIGNATURE_SCHEME or
        len(signature) != 128 or
        not verify_manifest_signature('release', descriptor, signature, public_key)
    ):
        raise ValueError('release descriptor signature verification failed')
    return descriptor
