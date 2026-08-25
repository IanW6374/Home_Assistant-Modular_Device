#!/usr/bin/env python3
"""Generate a deterministic CycloneDX SBOM for a IoTMD release source tree."""

import argparse
import hashlib
import json
from pathlib import Path


INCLUDED_SUFFIXES = {'.py', '.c', '.h', '.json', '.yaml', '.yml'}
EXCLUDED_PARTS = {'.git', '__pycache__', 'releases'}


def source_components(root):
    values = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in INCLUDED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        payload = path.read_bytes()
        values.append({
            'type': 'file', 'name': relative.as_posix(),
            'hashes': [{'alg': 'SHA-256', 'content': hashlib.sha256(payload).hexdigest()}],
        })
    return values


def build_sbom(root, version):
    root = Path(root)
    try:
        build_lock = json.loads((root / 'firmware/build-lock.json').read_text())
    except Exception:
        build_lock = {}
    components = source_components(root)
    components.extend((
        {
            'type': 'framework', 'name': 'MicroPython',
            'version': str(build_lock.get('micropython', 'unknown')),
            'properties': [{'name': 'git.commit', 'value': str(
                build_lock.get('micropython_commit', '')
            )}],
        },
        {
            'type': 'framework', 'name': 'ESP-IDF',
            'version': str(build_lock.get('esp_idf', 'unknown')),
            'properties': [{'name': 'git.commit', 'value': str(
                build_lock.get('esp_idf_commit', '')
            )}],
        },
        {
            'type': 'library', 'name': 'IoTMD native cryptography',
            'version': str(version),
            'properties': [{'name': 'source.path', 'value': 'firmware/native'}],
        },
    ))
    return {
        'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'serialNumber': None,
        'version': 1,
        'metadata': {'component': {
            'type': 'firmware', 'name': 'IoTMD', 'version': str(version)
        }},
        'components': components,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = build_sbom(args.root.resolve(), args.version)
    identifier = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()[:32]
    value['serialNumber'] = 'urn:uuid:' + '-'.join((
        identifier[:8], identifier[8:12], identifier[12:16],
        identifier[16:20], identifier[20:]
    ))
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
