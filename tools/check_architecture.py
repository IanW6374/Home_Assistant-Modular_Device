#!/usr/bin/env python3
"""Enforce the inward dependency rules documented for HAMD v2."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INWARD_FILES = tuple((ROOT / name) for name in ('application', 'services'))
FORBIDDEN_INWARD_IMPORTS = {
    'web_portal', 'web_portal_ui', 'device_api', 'mqtt_as', 'portal_auth',
    'credential_store', 'machine', 'network', 'esp32',
}
TRANSPORT_FILES = (
    ROOT / 'web_portal.py', ROOT / 'device_api.py', ROOT / 'portal_contracts.py'
)
FORBIDDEN_TRANSPORT_IMPORTS = {
    'app_update', 'firmware_update', 'universal_update', 'machine', 'esp32',
    'credential_store',
}


def imported_roots(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name.split('.', 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module.split('.', 1)[0])
    return result


def architecture_errors(root=ROOT):
    root = Path(root)
    errors = []
    for directory_name in ('application', 'services'):
        for path in sorted((root / directory_name).glob('*.py')):
            forbidden = imported_roots(path) & FORBIDDEN_INWARD_IMPORTS
            if forbidden:
                errors.append(
                    str(path.relative_to(root)) + ' imports outward layer: ' +
                    ', '.join(sorted(forbidden))
                )
    for relative in ('web_portal.py', 'device_api.py', 'portal_contracts.py'):
        path = root / relative
        forbidden = imported_roots(path) & FORBIDDEN_TRANSPORT_IMPORTS
        if forbidden:
            errors.append(
                relative + ' bypasses application services: ' +
                ', '.join(sorted(forbidden))
            )
    fleet_app = (root / 'home_assistant_addons/hamd_fleet/rootfs/app/fleet_app.py')
    fleet_tree = ast.parse(fleet_app.read_text(), filename=str(fleet_app))
    forbidden_classes = {
        node.name for node in fleet_tree.body
        if isinstance(node, ast.ClassDef) and node.name in (
            'DeviceClient', 'FleetController', 'FleetRepository', 'PolicySigner'
        )
    }
    if forbidden_classes:
        errors.append(
            'fleet_app.py contains service/repository classes: ' +
            ', '.join(sorted(forbidden_classes))
        )
    device_api = (root / 'device_api.py').read_text()
    if '/api/v1/' in device_api:
        errors.append('device_api.py exposes the retired v1 namespace')
    universal_builder = (root / 'tools/build_universal_update.py').read_text()
    if '--format-version' in universal_builder or 'format_version=1' in universal_builder:
        errors.append('universal builder exposes the retired bootstrap format')
    return errors


def main():
    errors = architecture_errors()
    if errors:
        raise SystemExit('\n'.join(errors))
    print('architecture dependency check passed')


if __name__ == '__main__':
    main()
