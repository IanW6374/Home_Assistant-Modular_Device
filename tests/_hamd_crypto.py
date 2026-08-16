"""Host-test stand-in for the firmware-only native HAMD crypto module."""

import hashlib


def pbkdf2_sha256(password, salt, iterations):
    return hashlib.pbkdf2_hmac('sha256', password, salt, iterations, dklen=32)
