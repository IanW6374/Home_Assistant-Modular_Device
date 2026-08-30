#!/usr/bin/env python3
"""Enforce the inward dependency rules documented for IoT-MD v2."""

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

# These ceilings prevent the former monoliths from silently growing back.
# They are deliberately just above the v2 baselines and should only move
# down as responsibilities are extracted; increasing one requires an explicit
# architecture review.
LINE_LIMITS = {
    'iotmd.py': 20,
    'iotmd_runtime.py': 3360,
    'web_portal.py': 1320,
    'setup_wizard.py': 450,
    'certificate_manager.py': 700,
    'credential_store.py': 800,
    'app_update.py': 755,
    'device_modules/modbus_transport.py': 850,
}
FUNCTION_LIMITS = {
    ('web_portal.py', 'start_web_portal'): 1280,
    ('setup_wizard.py', 'serve'): 350,
    ('iotmd_runtime.py', 'main'): 260,
}
BYTE_LIMITS = {
    # v2.3.4 exhausted the trial heap compiling a 126 KiB source entry.
    # Keep the recovery-compatible entry tiny and import the precompiled runtime.
    'iotmd.py': 1024,
}
RETIRED_SOURCE_MARKERS = {
    'settings_loader.py': ('ha_discovery_cleanup_legacy',),
    'factory_config.py': ('SETUP_CA_CERT_PATH',),
    'release_update.py': ('_release_manifest_request_url',),
}
REQUIRED_APPLICATION_MODULES = (
    'iotmd_runtime.py',
    'certificate_status.py', 'portal_http.py', 'portal_live_views.py', 'portal_presenters.py',
    'portal_settings_views.py', 'services/home_assistant_service.py',
)
REQUIRED_FROZEN_MODULES = (
    'application_storage.py', 'certificate_codec.py', 'credential_schema.py',
    'setup_workflow.py', 'setup_wizard_views.py',
)
LAZY_IMPORT_BOUNDARIES = {
    'certificate_portal_actions.py': {
        'certificate_enrollment_service', 'certificate_trust',
    },
    'certificate_portal_transport.py': {'certificate_portal_views'},
    'portal_settings_views.py': {'certificate_portal_views'},
    'web_portal.py': {'certificate_portal_transport'},
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


def module_imported_roots(path):
    """Return imports executed while the module itself is initialized."""
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    tree = ast.parse(path.read_text(), filename=str(path))
    result = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            result.update(alias.name.split('.', 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module.split('.', 1)[0])
        elif isinstance(node, ast.Try):
            # Compatibility imports commonly live in a module-level try block.
            for child in node.body + node.handlers + node.orelse + node.finalbody:
                candidates = child.body if isinstance(child, ast.ExceptHandler) else (child,)
                for candidate in candidates:
                    if isinstance(candidate, ast.Import):
                        result.update(
                            alias.name.split('.', 1)[0] for alias in candidate.names
                        )
                    elif isinstance(candidate, ast.ImportFrom) and candidate.module:
                        result.add(candidate.module.split('.', 1)[0])
    return result


def architecture_errors(root=ROOT):
    root = Path(root)
    errors = []
    for relative, forbidden_imports in LAZY_IMPORT_BOUNDARIES.items():
        eager = module_imported_roots(root / relative) & forbidden_imports
        if eager:
            errors.append(
                relative + ' eagerly imports memory-heavy administration: ' +
                ', '.join(sorted(eager))
            )
    for relative, maximum in LINE_LIMITS.items():
        path = root / relative
        count = len(path.read_text().splitlines())
        if count > maximum:
            errors.append(
                relative + ' exceeds architecture line limit: ' +
                str(count) + ' > ' + str(maximum)
            )
    for relative, maximum in BYTE_LIMITS.items():
        path = root / relative
        count = len(path.read_bytes())
        if count > maximum:
            errors.append(
                relative + ' exceeds boot entry byte limit: ' +
                str(count) + ' > ' + str(maximum)
            )
    for (relative, function_name), maximum in FUNCTION_LIMITS.items():
        path = root / relative
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                count = node.end_lineno - node.lineno + 1
                if count > maximum:
                    errors.append(
                        relative + ':' + function_name +
                        ' exceeds architecture function limit: ' +
                        str(count) + ' > ' + str(maximum)
                    )
                break
        else:
            errors.append(relative + ' is missing required boundary ' + function_name)
    for relative, markers in RETIRED_SOURCE_MARKERS.items():
        source = (root / relative).read_text()
        for marker in markers:
            if marker in source:
                errors.append(relative + ' restores retired compatibility: ' + marker)
    if 'recovery_boot' in imported_roots(root / 'update_security.py'):
        errors.append('update_security.py restores the recovery/update import cycle')
    application_builder = (root / 'tools/build_update.py').read_text()
    for relative in REQUIRED_APPLICATION_MODULES:
        if repr(relative) not in application_builder:
            errors.append('application builder omits extracted module: ' + relative)
    frozen_manifest = (root / 'firmware/manifest.py').read_text()
    for relative in REQUIRED_FROZEN_MODULES:
        if 'module("' + relative + '"' not in frozen_manifest:
            errors.append('frozen manifest omits extracted module: ' + relative)
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
