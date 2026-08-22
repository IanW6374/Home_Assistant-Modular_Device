#!/usr/bin/env python3
"""Wrap an ESP32 MicroPython application image in a verified .hamf bundle."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update_security import SIGNATURE_SCHEME, sign_manifest, sign_message


MAGIC = b'HAMF1\n'


def legacy_api4_manifest_message(manifest):
    """Canonical message used by the installed recovery API-4 verifier."""
    fields = (
        'hamf',
        str(manifest.get('format_version', 1)),
        str(manifest.get('target_board', manifest.get('platform', ''))),
        str(manifest.get('min_recovery_api', 1)),
        str(manifest.get('max_recovery_api', 4)),
        str(manifest.get('version', '')),
        str(manifest.get('size', '')),
        str(manifest.get('sha256', '')).lower(),
    )
    return ('\n'.join(fields) + '\n').encode()


def load_signing_key(path):
    if not path:
        return b''
    try:
        value = Path(path).read_bytes().strip()
    except OSError as exc:
        raise ValueError('signing key could not be read: ' + str(exc))
    if len(value) == 64:
        try:
            value = bytes.fromhex(value.decode())
        except ValueError:
            pass
    if len(value) != 32:
        raise ValueError('signing key must be exactly 32 bytes')
    return value


def build_firmware_bundle(
    image, output, version, platform='esp32-s3', signing_key=b'',
    max_image_bytes=2 * 1024 * 1024, release_sequence=1,
    minimum_core_api=8, format_version=6
):
    image = Path(image)
    if not image.is_file():
        raise ValueError('firmware image not found: ' + str(image))
    size = image.stat().st_size
    if size <= 0:
        raise ValueError('firmware image is empty')
    if size > int(max_image_bytes):
        raise ValueError(
            'firmware image exceeds OTA partition limit of ' +
            str(int(max_image_bytes)) + ' bytes'
        )
    with image.open('rb') as stream:
        first = stream.read(1)
        if first != b'\xe9':
            raise ValueError(
                'input is not an ESP application-only image '
                '(micropython.bin or .app-bin)'
            )
        digest = hashlib.sha256()
        digest.update(first)
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    if int(format_version) != 6:
        raise ValueError('firmware bundle format must be 6')
    manifest_object = {
        'format_version': int(format_version),
        'target_board': platform,
        'version': str(version),
        'platform': platform,
        'size': size,
        'sha256': digest.hexdigest()
    }
    manifest_object['release_sequence'] = int(release_sequence)
    manifest_object['minimum_core_api'] = int(minimum_core_api)
    if signing_key:
        manifest_object['signature_scheme'] = SIGNATURE_SCHEME
        manifest_object['signature'] = sign_manifest('hamf', manifest_object, signing_key)
    manifest = json.dumps(manifest_object, separators=(',', ':')).encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as bundle, image.open('rb') as stream:
        bundle.write(MAGIC)
        bundle.write(len(manifest).to_bytes(4, 'big'))
        bundle.write(manifest)
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            bundle.write(chunk)
    return {
        'output': output,
        'version': str(version),
        'platform': platform,
        'size': size,
        'sha256': digest.hexdigest()
    }


def main():
    parser = argparse.ArgumentParser(description='Build an ESP32 base firmware OTA bundle')
    parser.add_argument(
        '--input', dest='image', required=True,
        help='Input MicroPython ESP application-only image (micropython.bin or .app-bin)'
    )
    parser.add_argument(
        '--output', required=True,
        help='Output remote-upgrade bundle (.hamf)'
    )
    parser.add_argument('--version', required=True, help='Base firmware version label')
    parser.add_argument(
        '--release-sequence', type=int,
        help='Fleet-wide monotonically increasing signed firmware release number'
    )
    parser.add_argument('--platform', choices=('esp32-s3',), default='esp32-s3')
    parser.add_argument(
        '--signing-key', required=True,
        help='32-byte raw or 64-character hex ECDSA P-256 private key; never copy it to a device'
    )
    parser.add_argument('--max-image-bytes', type=int, default=2 * 1024 * 1024)
    args = parser.parse_args()
    if args.release_sequence is None or args.release_sequence <= 0:
        parser.error('--release-sequence must be a positive integer')
    try:
        result = build_firmware_bundle(
            args.image, args.output, args.version, args.platform,
            load_signing_key(args.signing_key), args.max_image_bytes,
            args.release_sequence
        )
    except ValueError as exc:
        raise SystemExit('build failed: ' + str(exc))
    print('created', result['output'])
    print('  version:', result['version'])
    print('  platform:', result['platform'])
    print('  image bytes:', result['size'])
    print('  sha256:', result['sha256'])
    print('  signature:', SIGNATURE_SCHEME)


if __name__ == '__main__':
    main()
