#!/usr/bin/env python3
"""Wrap an ESP32 MicroPython .app-bin image in a verified .hamf bundle."""

import argparse
import hashlib
import json
from pathlib import Path


MAGIC = b'HAMF1\n'


def build_firmware_bundle(output, image, version, platform='esp32-s3'):
    image = Path(image)
    if not image.is_file():
        raise ValueError('firmware image not found: ' + str(image))
    size = image.stat().st_size
    if size <= 0:
        raise ValueError('firmware image is empty')
    with image.open('rb') as stream:
        first = stream.read(1)
        if first != b'\xe9':
            raise ValueError('input is not an ESP application image (.app-bin)')
        digest = hashlib.sha256()
        digest.update(first)
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    manifest = json.dumps({
        'version': str(version),
        'platform': platform,
        'size': size,
        'sha256': digest.hexdigest()
    }, separators=(',', ':')).encode()
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
    parser.add_argument('image', help='MicroPython ESP application image (.app-bin)')
    parser.add_argument('output', help='Output .hamf bundle')
    parser.add_argument('--version', required=True, help='Base firmware version label')
    parser.add_argument('--platform', choices=('esp32', 'esp32-s3'), default='esp32-s3')
    args = parser.parse_args()
    try:
        result = build_firmware_bundle(args.output, args.image, args.version, args.platform)
    except ValueError as exc:
        raise SystemExit('build failed: ' + str(exc))
    print('created', result['output'])
    print('  version:', result['version'])
    print('  platform:', result['platform'])
    print('  image bytes:', result['size'])
    print('  sha256:', result['sha256'])


if __name__ == '__main__':
    main()
