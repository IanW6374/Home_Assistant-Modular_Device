#!/usr/bin/env python3
"""Check local Markdown links used by release documentation."""

import re
import sys
from pathlib import Path
from urllib.parse import unquote


LINK = re.compile(r'(?<!!)\[[^]]+\]\(([^)]+)\)')


def documentation_files(root):
    for name in ('README.md', 'CHANGELOG.md', 'SECURITY.md'):
        path = root / name
        if path.is_file():
            yield path
    yield from sorted((root / 'docs').rglob('*.md'))


def broken_links(root):
    failures = []
    for document in documentation_files(root):
        for match in LINK.finditer(document.read_text()):
            target = match.group(1).strip().split()[0].strip('<>')
            if target.startswith(('http://', 'https://', 'mailto:', '#')):
                continue
            relative = unquote(target.split('#', 1)[0])
            if relative and not (document.parent / relative).resolve().exists():
                failures.append(
                    str(document.relative_to(root)) + ': missing link target ' + relative
                )
    return failures


def missing_module_guides(root):
    sys.path.insert(0, str(root))
    try:
        from device_modules.driver_index import DRIVER_MODULES
    finally:
        sys.path.pop(0)
    index = (root / 'docs' / 'modules' / 'README.md').read_text()
    failures = []
    for module_type in sorted(DRIVER_MODULES):
        module_class, subclass = module_type.split(':', 1)
        marker = '| `' + module_class + '` | `' + subclass + '` |'
        if marker not in index:
            failures.append('module guide index omits supported type: ' + module_type)
    return failures


def main():
    root = Path(__file__).resolve().parents[1]
    failures = broken_links(root) + missing_module_guides(root)
    if failures:
        raise SystemExit('\n'.join(failures))
    print('documentation link check passed')


if __name__ == '__main__':
    main()
