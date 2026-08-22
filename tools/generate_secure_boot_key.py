#!/usr/bin/env python3
"""Generate an ESP32-S3 Secure Boot v2 RSA-3072 private key."""

import argparse
import subprocess
import sys
from pathlib import Path


def generation_command(root, output, python_executable=None):
    helper = (
        Path(root) / 'components' / 'esptool_py' / 'esptool' / 'espsecure.py'
    )
    return [
        python_executable or sys.executable, str(helper),
        'generate_signing_key', '--version', '2', '--scheme', 'rsa3072',
        str(output),
    ]


def main():
    parser = argparse.ArgumentParser(description='Generate the production secure-boot key')
    parser.add_argument('--esp-idf-root', required=True)
    parser.add_argument('--output', required=True, help='Offline PEM private-key path')
    args = parser.parse_args()
    root = Path(args.esp_idf_root).expanduser().resolve()
    helper = root / 'components' / 'esptool_py' / 'esptool' / 'espsecure.py'
    if not helper.is_file():
        raise SystemExit('espsecure.py not found under ESP-IDF root: ' + str(root))
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit('refusing to overwrite existing secure-boot key: ' + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(generation_command(root, output), check=True)
    output.chmod(0o600)
    print('generated Secure Boot v2 private key', output)
    print('keep this key offline; losing it prevents future core firmware updates')


if __name__ == '__main__':
    main()
