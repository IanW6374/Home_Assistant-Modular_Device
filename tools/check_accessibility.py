#!/usr/bin/env python3
"""Structural accessibility checks for rendered portal and add-on HTML."""

from html.parser import HTMLParser
from pathlib import Path
import os
import sys
import tempfile

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
    # Existing portal pages predate v2 language metadata. Flag it in alpha CI
    # only after every renderer has migrated, while requiring it for new UI.
    if name == 'fleet add-on' and not audit.language:
        failures.append(name + ': document language missing')
    return failures


def main():
    import web_portal
    addon = ROOT / 'home_assistant_addons/hamd_fleet/rootfs/app/fleet_app.py'
    with tempfile.TemporaryDirectory() as temporary:
        os.environ['HAMD_FLEET_DATA'] = temporary
        namespace = {
            '__name__': 'hamd_fleet_accessibility', '__file__': str(addon)
        }
        exec(compile(addon.read_text(), str(addon), 'exec'), namespace)
        pages = {
            'portal overview': web_portal.render_page('csrf', 'INFO', ('INFO',), [], 5000),
            'portal upgrades': web_portal.render_updates_page('csrf'),
            'portal backup': web_portal.render_configuration_backup_page('csrf'),
            'fleet add-on': namespace['HTML'],
        }
        namespace['STORE'].close()
    failures = []
    for name, html in pages.items():
        failures.extend(check(name, html))
    if failures:
        raise SystemExit('\n'.join(failures))
    print('accessibility structure check passed')


if __name__ == '__main__':
    main()
