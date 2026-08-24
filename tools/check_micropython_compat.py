#!/usr/bin/env python3
"""Catch CPython-only APIs in files shipped in a MicroPython application."""

import ast
from pathlib import Path

from build_update import collect_files


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_IMPORTS = {'dataclasses', 'pathlib', 'subprocess', 'multiprocessing'}
FORBIDDEN_METHODS = {
    'isalnum': 'MicroPython str does not provide isalnum()',
    'capitalize': 'MicroPython str does not provide capitalize()',
    'title': 'MicroPython str does not provide title()',
}


def compatibility_errors(path):
    path = Path(path)
    tree = ast.parse(path.read_text(), filename=str(path))
    errors = []
    hash_objects = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and
            isinstance(node.func, ast.Attribute) and
            node.func.attr in FORBIDDEN_METHODS
        ):
            errors.append(
                FORBIDDEN_METHODS[node.func.attr] + ' at line ' +
                str(node.lineno)
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.', 1)[0] in FORBIDDEN_IMPORTS:
                    errors.append('CPython-only import ' + alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split('.', 1)[0] in FORBIDDEN_IMPORTS:
                errors.append('CPython-only import ' + node.module)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if (
                isinstance(value, ast.Call) and
                isinstance(value.func, ast.Attribute) and
                value.func.attr == 'sha256' and
                isinstance(value.func.value, ast.Name) and
                value.func.value.id in ('hashlib', 'uhashlib')
            ):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                hash_objects.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
            node.func.attr == 'hexdigest' and
            isinstance(node.func.value, ast.Name) and
            node.func.value.id in hash_objects
        ):
            errors.append(
                'MicroPython SHA-256 object uses CPython-only hexdigest() at line ' +
                str(node.lineno)
            )
    return errors


def main():
    failures = []
    for relative, path in collect_files(ROOT, universal=True):
        if not relative.endswith('.py'):
            continue
        for error in compatibility_errors(path):
            failures.append(relative + ': ' + error)
    if failures:
        raise SystemExit('\n'.join(failures))
    print('MicroPython compatibility contract check passed')


if __name__ == '__main__':
    main()
