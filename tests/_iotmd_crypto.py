"""Host-test stand-in for the firmware-only native IoTMD crypto module."""

import hashlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def pbkdf2_sha256(password, salt, iterations):
    return hashlib.pbkdf2_hmac('sha256', password, salt, iterations, dklen=32)


def aes_gcm_encrypt(key, nonce, plaintext, associated_data=b''):
    return AESGCM(bytes(key)).encrypt(
        bytes(nonce), bytes(plaintext), bytes(associated_data)
    )


def aes_gcm_decrypt(key, nonce, ciphertext_and_tag, associated_data=b''):
    return AESGCM(bytes(key)).decrypt(
        bytes(nonce), bytes(ciphertext_and_tag), bytes(associated_data)
    )
