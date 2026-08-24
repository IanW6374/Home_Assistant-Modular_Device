#!/usr/bin/env python3
"""Structural accessibility checks for rendered device portal HTML."""

from html.parser import HTMLParser
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.duplicates = []
        self.images_without_alt = 0
        self.viewport = False
        self.language = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        identifier = values.get('id')
        if identifier in self.ids:
            self.duplicates.append(identifier)
        elif identifier:
            self.ids.add(identifier)
        if tag == 'img' and 'alt' not in values:
            self.images_without_alt += 1
        if tag == 'meta' and values.get('name') == 'viewport':
            self.viewport = True
        if tag == 'html' and values.get('lang'):
            self.language = True


def check(name, html):
    audit = Audit()
    audit.feed(html)
    failures = []
    if audit.duplicates:
        failures.append(name + ': duplicate ids ' + ', '.join(audit.duplicates))
    if audit.images_without_alt:
        failures.append(name + ': image missing alt text')
    if not audit.viewport:
        failures.append(name + ': viewport metadata missing')
    return failures


def main():
    import web_portal
    pages = {
        'portal overview': web_portal.render_page('csrf', 'INFO', ('INFO',), [], 5000),
        'portal upgrades': web_portal.render_updates_page('csrf'),
        'portal backup': web_portal.render_configuration_backup_page('csrf'),
    }
    failures = []
    for name, html in pages.items():
        failures.extend(check(name, html))
    if failures:
        raise SystemExit('\n'.join(failures))
    print('accessibility structure check passed')


if __name__ == '__main__':
    main()
