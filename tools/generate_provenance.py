#!/usr/bin/env python3
"""Write a compact SLSA-compatible provenance statement for release artifacts."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_statement(root, artifacts, version):
    revision = subprocess.check_output(
        ('git', '-C', str(root), 'rev-parse', 'HEAD'), text=True
    ).strip()
    try:
        build_lock = json.loads((Path(root) / 'firmware/build-lock.json').read_text())
    except Exception:
        build_lock = {}
    dependencies = [{
        'uri': 'git+https://github.com/IanW6374/Home_Assistant-Modular_Device',
        'digest': {'gitCommit': revision},
    }]
    for name, uri in (
        ('micropython', 'git+https://github.com/micropython/micropython'),
        ('esp_idf', 'git+https://github.com/espressif/esp-idf'),
    ):
        commit = str(build_lock.get(name + '_commit', ''))
        if commit:
            dependencies.append({'uri': uri, 'digest': {'gitCommit': commit}})
    return {
        '_type': 'https://in-toto.io/Statement/v1',
        'subject': [
            {'name': Path(path).name, 'digest': {'sha256': digest(path)}}
            for path in artifacts
        ],
        'predicateType': 'https://slsa.dev/provenance/v1',
        'predicate': {
            'buildDefinition': {
                'buildType': 'https://hamd.example/build/v2',
                'externalParameters': {'version': version},
                'internalParameters': {},
                'resolvedDependencies': dependencies,
            },
            'runDetails': {'builder': {'id': 'hamd/tools'}, 'metadata': {
                'invocationId': revision + ':' + version,
                'python': sys.version.split()[0], 'platform': platform.platform(),
            }},
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('artifacts', nargs='+', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(
        build_statement(args.root.resolve(), args.artifacts, args.version),
        indent=2, sort_keys=True
    ) + '\n')


if __name__ == '__main__':
    main()
