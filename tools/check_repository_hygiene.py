#!/usr/bin/env python3
"""Reject secrets, generated caches, and platform noise from tracked files."""

import subprocess
from pathlib import Path


FORBIDDEN_NAMES = {'.DS_Store', 'secrets.py'}
FORBIDDEN_SUFFIXES = ('.pyc', '.pyo', '.private-key', '.signing-key')
PRIVATE_KEY_MARKERS = tuple(
    ('-----BEGIN ' + key_type + '-----').encode()
    for key_type in ('PRIVATE KEY', 'EC PRIVATE KEY', 'RSA PRIVATE KEY')
)


def tracked_files(root):
    output = subprocess.check_output(
        ('git', '-C', str(root), 'ls-files', '-z')
    )
    return [item.decode() for item in output.split(b'\0') if item]


def main():
    root = Path(__file__).resolve().parents[1]
    failures = []
    for relative in tracked_files(root):
        path = Path(relative)
        absolute = root / path
        if not absolute.exists():
            continue
        if (
            path.name in FORBIDDEN_NAMES or '__pycache__' in path.parts or
            path.name.endswith(FORBIDDEN_SUFFIXES)
        ):
            failures.append('forbidden tracked path: ' + relative)
            continue
        try:
            payload = absolute.read_bytes()
        except OSError:
            continue
        if any(marker in payload for marker in PRIVATE_KEY_MARKERS):
            failures.append('private key material in tracked file: ' + relative)
    if failures:
        raise SystemExit('\n'.join(failures))
    print('repository hygiene check passed')


if __name__ == '__main__':
    main()
