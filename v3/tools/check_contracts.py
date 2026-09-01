#!/usr/bin/env python3
"""Validate the executable v3 native/runtime contract examples."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def main():
    root = Path(__file__).resolve().parents[1]
    contracts = root / 'contracts'
    pairs = (
        (
            contracts / 'examples' / 'platform-capabilities.json',
            contracts / 'platform-capabilities.schema.json',
        ),
    )
    for instance_path, schema_path in pairs:
        schema = json.loads(schema_path.read_text())
        instance = json.loads(instance_path.read_text())
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            details = []
            for error in errors:
                location = '.'.join(
                    str(item) for item in error.absolute_path
                ) or '<root>'
                details.append(
                    str(instance_path.relative_to(root)) + ':' + location +
                    ': ' + error.message
                )
            raise SystemExit('\n'.join(details))
        print(
            'validated', instance_path.relative_to(root), 'against',
            schema_path.relative_to(root)
        )


if __name__ == '__main__':
    main()
