#!/usr/bin/env python3
"""Generate an offline update private key and provision only its public key."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update_security import _N, public_key_bytes


def load_private_key(path):
    try:
        value = path.read_bytes().strip()
    except OSError as exc:
        raise ValueError('private key could not be read: ' + str(exc))
    if len(value) == 64:
        try:
            value = bytes.fromhex(value.decode())
        except ValueError:
            pass
    if len(value) != 32 or not 1 <= int.from_bytes(value, 'big') < _N:
        raise ValueError('private key must be a valid 32-byte P-256 scalar')
    return value


def main():
    parser = argparse.ArgumentParser(description='Provision asymmetric OTA update verification')
    parser.add_argument('--private-key', required=True, help='Offline host private-key file')
    parser.add_argument('--generate', action='store_true', help='Generate the private key if absent')
    parser.add_argument('--mount', help='Mounted MicroPython VFS to receive the public key')
    parser.add_argument('--public-key-output', help='Optional host public-key output file')
    args = parser.parse_args()

    private_path = Path(args.private_key).expanduser().resolve()
    if args.generate:
        if private_path.exists():
            raise SystemExit('refusing to overwrite existing private key: ' + str(private_path))
        private_path.parent.mkdir(parents=True, exist_ok=True)
        private = 0
        while not 1 <= private < _N:
            private = int.from_bytes(os.urandom(32), 'big')
        private_path.write_text(private.to_bytes(32, 'big').hex() + '\n')
        try:
            private_path.chmod(0o600)
        except OSError:
            pass
        print('generated private key', private_path)
    try:
        private_key = load_private_key(private_path)
    except ValueError as exc:
        raise SystemExit(str(exc))
    public_hex = public_key_bytes(private_key).hex() + '\n'

    if args.public_key_output:
        public_path = Path(args.public_key_output).expanduser().resolve()
        public_path.parent.mkdir(parents=True, exist_ok=True)
        public_path.write_text(public_hex)
        print('wrote public key', public_path)

    if args.mount:
        mount = Path(args.mount).expanduser().resolve()
        if not mount.is_dir():
            raise SystemExit('mount path not found: ' + str(mount))
        legacy = mount / '.update-signing-key'
        if legacy.exists():
            raise SystemExit(
                'legacy device signing key exists; erase/rebuild the device before provisioning'
            )
        destination = mount / '.update-verification-key'
        destination.write_text(public_hex)
        print('provisioned public verification key', destination)
    elif not args.public_key_output:
        print('private key validated; pass --mount to provision its public key')


if __name__ == '__main__':
    main()
