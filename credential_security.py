"""Password verifier helpers shared by the portal and frozen recovery layer.

Passwords are represented as salted PBKDF2-HMAC-SHA256 verifiers so the
original portal password never needs to be stored on the device.  The modest
iteration count is intentional for ESP32-class hardware; use long, randomly
generated passwords as the primary defence against offline guessing.
"""

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


PASSWORD_SCHEME = 'pbkdf2-sha256'
PASSWORD_ITERATIONS = 120000
PASSWORD_MIN_ITERATIONS = 20000
PASSWORD_SALT_BYTES = 16
PASSWORD_DIGEST_BYTES = 32
PASSWORD_MAX_ITERATIONS = 1000000
PASSWORD_MAX_SALT_BYTES = 64
MIN_PASSWORD_LENGTH = 16
LONG_PASSPHRASE_LENGTH = 20
_progress_callback = None


COMMON_PASSWORDS = (
    '1234567890123456',
    'adminadminadminadmin',
    'changemechangeme',
    'letmeinletmeinletmein',
    'passwordpassword',
    'password12345678',
    'qwertyqwertyqwerty',
)


def _is_lower(character):
    return 'a' <= character <= 'z'


def _is_upper(character):
    return 'A' <= character <= 'Z'


def _is_digit(character):
    return '0' <= character <= '9'


def _is_alnum(character):
    return _is_lower(character) or _is_upper(character) or _is_digit(character)


def set_progress_callback(callback=None):
    """Register lightweight servicing work for long password calculations."""
    global _progress_callback
    _progress_callback = callback if callable(callback) else None


def _report_progress(active):
    if _progress_callback:
        _progress_callback(bool(active))


def validate_password_strength(password):
    """Apply a small, deterministic password policy suitable for frozen firmware."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError('passwords must contain at least 16 characters')
    if len(password) > 256:
        raise ValueError('passwords must not exceed 256 characters')

    lowered = password.lower()
    compact = ''.join(character for character in lowered if _is_alnum(character))
    if lowered in COMMON_PASSWORDS or compact in COMMON_PASSWORDS:
        raise ValueError('password is too common')
    if len(set(password)) < 5:
        raise ValueError('password contains too much repeated text')
    for sequence in ('012345', '123456', 'abcdef', 'qwerty', 'password', 'letmein'):
        if sequence in compact:
            raise ValueError('password contains a common or predictable sequence')

    classes = 0
    classes += any(_is_lower(character) for character in password)
    classes += any(_is_upper(character) for character in password)
    classes += any(_is_digit(character) for character in password)
    classes += any(not _is_alnum(character) for character in password)
    required_classes = 2 if len(password) >= LONG_PASSPHRASE_LENGTH else 3
    if classes < required_classes:
        raise ValueError(
            'password needs more character variety or a passphrase of at least 20 characters'
        )
    return True


def _constant_time_equal(left, right):
    left = bytes(left)
    right = bytes(right)
    different = len(left) ^ len(right)
    longest = max(len(left), len(right))
    for index in range(longest):
        left_value = left[index] if index < len(left) else 0
        right_value = right[index] if index < len(right) else 0
        different |= left_value ^ right_value
    return different == 0


def _pbkdf2_sha256(password, salt, iterations):
    """Derive a key using the mandatory native ESP-IDF/mbedTLS module."""
    try:
        import _iotmd_crypto
    except ImportError:
        raise RuntimeError(
            'IoT-MD native PBKDF2 support is required; install compatible core firmware'
        )
    _report_progress(True)
    try:
        return _iotmd_crypto.pbkdf2_sha256(
            bytes(password), bytes(salt), int(iterations)
        )
    finally:
        _report_progress(False)


def password_verifier(password, salt, iterations=PASSWORD_ITERATIONS):
    """Create a verifier using caller-supplied cryptographic random salt."""
    validate_password_strength(password)
    salt = bytes(salt)
    if not PASSWORD_SALT_BYTES <= len(salt) <= PASSWORD_MAX_SALT_BYTES:
        raise ValueError('password salt must contain between 16 and 64 bytes')
    iterations = int(iterations)
    if not PASSWORD_ITERATIONS <= iterations <= PASSWORD_MAX_ITERATIONS:
        raise ValueError('password verifier iteration count is out of range')
    digest = _pbkdf2_sha256(password.encode(), salt, iterations)
    return '$'.join((
        PASSWORD_SCHEME,
        str(iterations),
        binascii.hexlify(salt).decode(),
        binascii.hexlify(digest).decode(),
    ))


def parse_password_verifier(verifier):
    if not isinstance(verifier, str):
        raise ValueError('password verifier must be text')
    parts = verifier.split('$')
    if len(parts) != 4 or parts[0] != PASSWORD_SCHEME:
        raise ValueError('password verifier format is not supported')
    try:
        iterations = int(parts[1])
        salt = binascii.unhexlify(parts[2])
        expected = binascii.unhexlify(parts[3])
    except Exception:
        raise ValueError('password verifier is malformed')
    if not PASSWORD_MIN_ITERATIONS <= iterations <= PASSWORD_MAX_ITERATIONS:
        raise ValueError('password verifier iteration count is out of range')
    if (
        not PASSWORD_SALT_BYTES <= len(salt) <= PASSWORD_MAX_SALT_BYTES
        or len(expected) != PASSWORD_DIGEST_BYTES
    ):
        raise ValueError('password verifier has invalid parameters')
    return iterations, salt, expected


def verify_password(password, verifier):
    """Verify a candidate without ever materialising the original password."""
    try:
        iterations, salt, expected = parse_password_verifier(verifier)
    except ValueError:
        return False
    if not isinstance(password, str) or len(password) > 256:
        return False
    actual = _pbkdf2_sha256(password.encode(), salt, iterations)
    return _constant_time_equal(actual, expected)


async def verify_password_async(password, verifier):
    """Verify a password through native mbedTLS without blocking Wi-Fi tasks."""
    try:
        iterations, salt, expected = parse_password_verifier(verifier)
    except ValueError:
        return False
    if not isinstance(password, str) or len(password) > 256:
        return False
    if hasattr(asyncio, 'sleep_ms'):
        await asyncio.sleep_ms(0)
    else:
        await asyncio.sleep(0)
    actual = _pbkdf2_sha256(password.encode(), salt, iterations)
    if hasattr(asyncio, 'sleep_ms'):
        await asyncio.sleep_ms(0)
    else:
        await asyncio.sleep(0)
    return _constant_time_equal(actual, expected)
