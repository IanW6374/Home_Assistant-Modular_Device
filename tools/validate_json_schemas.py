#!/usr/bin/env python3
"""Validate checked-in configuration and generated release JSON."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def validate_file(instance_path, schema_path):
    instance_path = Path(instance_path)
    schema_path = Path(schema_path)
    instance = json.loads(instance_path.read_text())
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        details = []
        for error in errors:
            location = '.'.join(str(item) for item in error.absolute_path) or '<root>'
            details.append(str(instance_path) + ':' + location + ': ' + error.message)
        raise ValueError('\n'.join(details))
    print('validated', instance_path, 'against', schema_path)


def main():
    root = Path(__file__).resolve().parents[1]
    validate_file(root / 'app_settings.json', root / 'app_settings.schema.json')
    validate_file(root / 'module_settings.json', root / 'module_settings.schema.json')
    for descriptor in sorted((root / 'releases').glob('release-site-*/**/latest.json')):
        validate_file(descriptor, root / 'release_descriptor.schema.json')


if __name__ == '__main__':
    main()
