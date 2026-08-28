#!/usr/bin/env python3
"""Generate an independent IoT-MD fleet-policy P-256 signing keypair."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_security


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-output', required=True)
    parser.add_argument('--public-output', required=True)
    args = parser.parse_args()
    private_path = Path(args.private_output)
    public_path = Path(args.public_output)
    if private_path.exists() or public_path.exists():
        raise SystemExit('refusing to overwrite an existing fleet signing key')
    while True:
        private = os.urandom(32)
        try:
            public = update_security.public_key_bytes(private)
            break
        except ValueError:
            pass
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(private)
    public_path.write_bytes(public)
    os.chmod(private_path, 0o600)
    os.chmod(public_path, 0o644)
    print('created fleet private key', private_path)
    print('created device verification key', public_path)


if __name__ == '__main__':
    main()
