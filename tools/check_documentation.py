#!/usr/bin/env python3
"""Check local Markdown links used by release documentation."""

import re
from pathlib import Path
from urllib.parse import unquote


LINK = re.compile(r'(?<!!)\[[^]]+\]\(([^)]+)\)')


def documentation_files(root):
    for name in ('README.md', 'CHANGELOG.md', 'SECURITY.md'):
        path = root / name
        if path.is_file():
            yield path
    yield from sorted((root / 'docs').glob('*.md'))


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


def main():
    root = Path(__file__).resolve().parents[1]
    failures = broken_links(root)
    if failures:
        raise SystemExit('\n'.join(failures))
    print('documentation link check passed')


if __name__ == '__main__':
    main()
