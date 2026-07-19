#!/usr/bin/env python3
"""Generate or provision the shared OTA bundle signing key."""

import argparse
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Provision OTA update signing')
    parser.add_argument('--key', required=True, help='Host key file (hex format)')
    parser.add_argument('--generate', action='store_true', help='Generate the host key if absent')
    parser.add_argument('--mount', help='Mounted MicroPython VFS to provision')
    args = parser.parse_args()

    key_path = Path(args.key).resolve()
    if args.generate:
        if key_path.exists():
            raise SystemExit('refusing to overwrite existing key: ' + str(key_path))
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(secrets.token_hex(32) + '\n')
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        print('generated', key_path)
    if not key_path.is_file():
        raise SystemExit('key file not found: ' + str(key_path))
    value = key_path.read_text().strip()
    if len(value) != 64:
        raise SystemExit('key must be 64 hexadecimal characters')
    bytes.fromhex(value)

    if args.mount:
        mount = Path(args.mount).resolve()
        if not mount.is_dir():
            raise SystemExit('mount path not found: ' + str(mount))
        destination = mount / '.update-signing-key'
        destination.write_text(value + '\n')
        print('provisioned', destination)
    else:
        print('key validated; pass --mount to provision a connected device')


if __name__ == '__main__':
    main()
