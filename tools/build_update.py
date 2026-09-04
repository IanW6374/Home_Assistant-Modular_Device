#!/usr/bin/env python3
"""Build a hash-verified application bundle for portal upload."""

import argparse
import ast
import fnmatch
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.release_provenance import git_source_revision, source_marker
from update_security import SIGNATURE_SCHEME, sign_manifest


MAGIC = b'IOTA1\n'
CORE_FILES = (
    'iotmd.py',
    'iotmd_runtime.py',
    'application_upload.py',
    'app_settings.json',
    'component_versions.py',
    'certificate_lifecycle.py',
    'certificate_status.py',
    'certificate_enrollment_service.py',
    'certificate_portal_actions.py',
    'certificate_portal_transport.py',
    'certificate_portal_views.py',
    'certificate_trust.py',
    'settings_loader.py',
    'display.py',
    'portal_server.py',
    'web_portal_ui.py',
    'web_portal.py',
    'portal_http.py',
    'portal_live_views.py',
    'portal_presenters.py',
    'portal_settings_views.py',
    'api_security.py',
    'fleet_management.py',
    'configuration_manager.py',
    'api_contracts.py',
    'device_api.py',
    'device_api_inventory.py',
    'feature_flags.py',
    'network_transports.py',
    'tls_sessions.py',
    'message_broker.py',
    'portal_auth.py',
    'portal_contracts.py',
    'portal_routes.py',
    'portal_view_models.py',
    'portal_sessions.py',
    'runtime_health.py',
    'support_bundle.py',
    'remote_logging.py',
    'resumable_upload.py',
    'timezone_rules.py',
    'update_orchestrator.py',
    'universal_upload.py',
    'services/__init__.py',
    'services/network_service.py',
    'services/messaging_service.py',
    'services/home_assistant_service.py',
    'services/portal_service.py',
    'services/update_service.py',
    'services/event_service.py',
    'services/event_sinks.py',
    'services/module_runtime.py',
    'services/startup_service.py',
    'application/__init__.py',
    'application/context.py',
    'application/lifecycle.py',
    'application/boot_health.py',
)
V3_ALPHA_FILES = (
    'v3/__init__.py',
    'v3/runtime/__init__.py',
    'v3/runtime/iotmd_next/__init__.py',
    'v3/runtime/iotmd_next/configuration.py',
    'v3/runtime/iotmd_next/connectivity.py',
    'v3/runtime/iotmd_next/drivers.py',
    'v3/runtime/iotmd_next/fleet.py',
    'v3/runtime/iotmd_next/identity.py',
    'v3/runtime/iotmd_next/kernel.py',
    'v3/runtime/iotmd_next/migration.py',
    'v3/runtime/iotmd_next/paired_update.py',
    'v3/runtime/iotmd_next/platform.py',
    'v3/runtime/iotmd_next/presentation.py',
    'v3/runtime/iotmd_next/product_transports.py',
    'v3/runtime/iotmd_next/reference_sensor.py',
    'v3/runtime/iotmd_next/resources.py',
    'v3/runtime/iotmd_next/storage.py',
    'v3/runtime/iotmd_next/supervisor.py',
    'v3/runtime/iotmd_next/transport_contracts.py',
)
CORE_DEVICE_MODULES = (
    'device_modules/__init__.py',
    'device_modules/loader.py',
    'device_modules/driver_index.py',
    'device_modules/base.py',
    'device_modules/contracts.py',
    'device_modules/resources.py',
    'device_modules/logging.py',
    'device_modules/validation.py',
)
CORE_LIB_FILES = (
    'lib/mqtt_as.py',
    'lib/primitives/__init__.py',
    'lib/primitives/encoder.py',
)
LOADER_EXCLUDED_MODULES = {
    '__init__.py', 'loader.py', 'base.py', 'logging.py', 'sensor.py',
    'spi_bus.py', 'template.py', 'validation.py', 'modbus_codec.py'
}
IGNORE_FILE = '.build_update_ignore'
MPY_SOURCE_FILES = frozenset(('iotmd.py', 'component_versions.py'))
MPY_SOURCE_ALIASES = {
    # A new module identity prevents an older active A/B generation from
    # satisfying the portal import during a trial boot.  The source-tree file
    # remains a lightweight CPython/development adapter.
    'portal_server.py': 'web_portal.py',
}

# MicroPython loads the complete raw-code child tree for a nested coroutine as
# one allocation.  Keeping these large dispatchers nested under handle_client
# therefore recreates the portal import failure even when the source itself is
# precompiled.  The application builder promotes them to independent modules
# and leaves small closure-preserving wrappers in portal_server.mpy.
PORTAL_ROUTE_SPLITS = (
    (
        'handle_access_routes', 'portal_route_access',
        (
            'authenticator', 'cached_page', 'credential_security', 'csrf_error',
            'csrf_token', 'factory_reset_handler', 'form_params', 'is_asset',
            'is_device_control', 'is_factory_default', 'is_login',
            'is_password_change', 'is_user_settings', 'log_output',
            'login_failures', 'login_url', 'method',
            'network_trial_confirmer', 'password_change_required',
            'password_setter', 'password_verifier', 'path', 'peer_address',
            'restart_request_handler', 'restart_status_getter', 'route',
            'secure_cookie', 'send_redirect', 'send_response', 'session',
            'session_id', 'session_role', 'session_username', 'session_valid',
            'sessions', 'settings_getter', 'shutdown_request_handler',
            'user_password_setter', 'username', 'writer',
        ),
        (
            'login_failures', 'password_verifier',
            'password_change_required', 'session', 'session_id', 'csrf_token',
            'session_role', 'session_username',
        ),
    ),
    (
        'handle_settings_routes', 'portal_route_settings',
        (
            'action_handler', 'action_path', 'audit_log_getter', 'body',
            'cached_page', 'certificate_info_getter',
            'certificate_upload_handler', 'certificate_validate_handler',
            'config_import_apply_handler', 'config_import_preview_handler',
            'csrf_token', 'form_params', 'headers', 'is_audit_logging',
            'is_certificate_request', 'is_configuration_backup',
            'is_diagnostics', 'is_health_history', 'is_logging',
            'is_module_settings', 'is_operational_settings', 'is_updates',
            'is_user_management', 'levels', 'log_getter', 'log_output',
            'log_refresh_ms', 'loglevel_getter', 'method',
            'module_settings_getter', 'module_settings_setter',
            'module_snapshot', 'portal_user_add', 'portal_user_getter',
            'portal_user_remove', 'portal_user_update', 'reader', 'route',
            'secure_config_backup_getter',
            'secure_config_import_apply_handler',
            'secure_config_import_preview_handler', 'secure_cookie',
            'send_redirect', 'send_response', 'session_role',
            'session_username', 'settings_getter', 'settings_setter',
            'status_snapshot', 'update_preferences_setter',
            'value_refresh_ms', 'writer', '_handle_certificate_request',
        ),
        (),
    ),
    (
        'handle_upload_routes', 'portal_route_upload',
        (
            'action_path', 'asyncio', 'body', 'complete_resumable_update',
            'headers', 'log_output', 'method', 'portal', 'progress_state',
            'reader', 'resumable_append', 'resumable_begin',
            'resumable_complete', 'resumable_status', 'route',
            'send_response', 'upload_progress_by_id', 'writer',
        ),
        (),
    ),
    (
        'handle_live_routes', 'portal_route_live',
        (
            'action_handler', 'action_path', 'audit_log_getter',
            'config_backup_getter', 'csrf_token', 'form_params',
            'is_json_validation', 'levels', 'log_buffer_lines_setter',
            'log_getter', 'log_output', 'login_url', 'loglevel_setter',
            'method', 'module_snapshot', 'path', 'secure_cookie',
            'send_log_download', 'send_redirect', 'send_response',
            'session_id', 'session_role', 'sessions', 'status_snapshot',
            'task_status_getter', 'upload_progress_by_id',
            'value_refresh_ms', 'wifi_scan_getter', 'writer',
        ),
        (),
    ),
)

PORTAL_ROUTE_IMPORTS = (
    "try:\n    import ujson as json\nexcept ImportError:\n    import json\n\n"
    "try:\n    import uasyncio as asyncio\nexcept ImportError:\n    import asyncio\n\n"
    "import web_portal_ui as portal_ui\n"
    "import portal_auth\n"
    "from portal_http import *\n"
    "from portal_settings_views import *\n"
    "from portal_live_views import *\n"
    "from portal_presenters import *\n\n"
)

COMPACT_MPY_SIZE_LIMITS = {
    # The 2.3.7/2.3.8 hardware trials proved that aggregate nested route code
    # can exceed the largest contiguous block even with ample total free heap.
    # Bound both the transport and each independently loaded dispatcher.
    'portal_server.mpy': 10000,
    'portal_route_access.mpy': 6500,
    'portal_route_settings.mpy': 6000,
    'portal_route_upload.mpy': 3500,
    'portal_route_live.mpy': 5500,
}

# A .mpy import materialises every string in its object table before executing
# the module.  Large renderer-local HTML/JavaScript constants can therefore
# require a large contiguous heap block during boot, even though the renderer
# is not being called.  Keep the stored chunks small and join them only when
# that renderer is used.  Module-level constants are intentionally left alone:
# joining those during import would still need the same contiguous allocation.
MAX_RUNTIME_STRING_CHUNK_BYTES = 2048


def _string_chunks(value, maximum_bytes):
    """Split text without breaking a UTF-8 code point or the byte limit."""
    chunks = []
    current = []
    current_bytes = 0
    for character in value:
        encoded_bytes = len(character.encode('utf-8'))
        if current and current_bytes + encoded_bytes > maximum_bytes:
            chunks.append(''.join(current))
            current = []
            current_bytes = 0
        current.append(character)
        current_bytes += encoded_bytes
    if current:
        chunks.append(''.join(current))
    return chunks


class _RuntimeStringChunker(ast.NodeTransformer):
    def __init__(self, maximum_bytes):
        self.maximum_bytes = int(maximum_bytes)
        self.function_depth = 0

    def _visit_function(self, node):
        self.function_depth += 1
        try:
            return self.generic_visit(node)
        finally:
            self.function_depth -= 1

    def visit_FunctionDef(self, node):
        return self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        return self._visit_function(node)

    def visit_Constant(self, node):
        value = node.value
        if (
            self.function_depth <= 0 or not isinstance(value, str) or
            len(value.encode('utf-8')) <= self.maximum_bytes
        ):
            return node
        chunks = _string_chunks(value, self.maximum_bytes)
        replacement = ast.Call(
            func=ast.Attribute(
                value=ast.Constant(value=''), attr='join', ctx=ast.Load()
            ),
            args=[ast.Tuple(
                elts=[ast.Constant(value=chunk) for chunk in chunks],
                ctx=ast.Load(),
            )],
            keywords=[],
        )
        return ast.copy_location(replacement, node)


def chunk_runtime_string_literals(source, maximum_bytes=MAX_RUNTIME_STRING_CHUNK_BYTES):
    """Defer large renderer-local string assembly until the function runs."""
    was_bytes = isinstance(source, bytes)
    text = source.decode('utf-8') if was_bytes else str(source)
    tree = ast.parse(text)
    tree = _RuntimeStringChunker(maximum_bytes).visit(tree)
    ast.fix_missing_locations(tree)
    transformed = ast.unparse(tree) + '\n'
    return transformed.encode('utf-8') if was_bytes else transformed


def split_portal_route_modules(source):
    """Return a compact portal source plus independently compiled routes."""
    if isinstance(source, bytes):
        source = source.decode('utf-8')
    generated = {}
    imports = []
    for function_name, module_name, arguments, mutable_arguments in PORTAL_ROUTE_SPLITS:
        marker = '        async def ' + function_name + '():\n'
        start = source.find(marker)
        if start < 0:
            continue
        next_function = source.find('\n        async def ', start + len(marker))
        next_try = source.find('\n        try:\n', start + len(marker))
        candidates = tuple(value for value in (next_function, next_try) if value >= 0)
        if not candidates:
            raise ValueError('portal route has no boundary: ' + function_name)
        end = min(candidates) + 1
        block = source[start:end]
        top_level = ''.join(
            line[8:] if line.startswith('        ') else line
            for line in block.splitlines(True)
        )
        if mutable_arguments:
            transformed = []
            for line in top_level.splitlines(True):
                stripped = line.strip()
                if stripped.startswith('nonlocal '):
                    continue
                if stripped in ('return False', 'return True'):
                    indent = line[:len(line) - len(line.lstrip())]
                    handled = 'False' if stripped.endswith('False') else 'True'
                    line = (
                        indent + 'return (' + handled + ', ' +
                        ', '.join(mutable_arguments) + ')\n'
                    )
                transformed.append(line)
            top_level = ''.join(transformed)
        signature = (
            'async def ' + function_name + '(\n    ' +
            ',\n    '.join(arguments) + '\n):\n'
        )
        top_level = top_level.replace(
            'async def ' + function_name + '():\n', signature, 1
        )
        generated[module_name + '.py'] = (
            PORTAL_ROUTE_IMPORTS + top_level
        ).encode('utf-8')
        if mutable_arguments:
            wrapper = (
                '        async def ' + function_name + '():\n'
                '            nonlocal ' + ', '.join(mutable_arguments) + '\n'
                '            result = await ' + module_name + '.' + function_name + '(\n'
                '                ' + ',\n                '.join(arguments) + '\n'
                '            )\n'
                '            handled, ' + ', '.join(mutable_arguments) + ' = result\n'
                '            return handled\n'
            )
        else:
            wrapper = (
                '        async def ' + function_name + '():\n'
                '            return await ' + module_name + '.' + function_name + '(\n'
                '                ' + ',\n                '.join(arguments) + '\n'
                '            )\n'
            )
        source = source[:start] + wrapper + source[end:]
        imports.append('import ' + module_name + '\n')
    if generated:
        anchor = 'from portal_presenters import *\n'
        if anchor not in source:
            raise ValueError('portal route import anchor is missing')
        source = source.replace(anchor, anchor + ''.join(imports), 1)
    return source.encode('utf-8'), generated


def compact_application_files(files, content_overrides, compiler):
    """Compile importable Python modules while retaining boot/provenance sources."""
    compiler = Path(compiler).resolve()
    if not compiler.is_file():
        raise ValueError('mpy-cross compiler not found: ' + str(compiler))
    files = list(files)
    compact_files = []
    compact_overrides = dict(content_overrides or {})
    targets = set()
    portal_source = None
    portal_path = None
    for relative, path in files:
        if relative == 'portal_server.py':
            portal_path = path
            portal_source = path.with_name(
                MPY_SOURCE_ALIASES['portal_server.py']
            ).read_bytes()
            break
    if portal_source is not None:
        portal_source, route_sources = split_portal_route_modules(portal_source)
        compact_overrides['portal_server.py'] = portal_source
        for relative, source in route_sources.items():
            files.append((relative, portal_path))
            compact_overrides[relative] = source
    with tempfile.TemporaryDirectory(prefix='iotmd-mpy-') as temporary:
        temporary = Path(temporary)
        for index, (relative, path) in enumerate(files):
            if not relative.endswith('.py') or relative in MPY_SOURCE_FILES:
                compact_files.append((relative, path))
                targets.add(relative)
                continue
            target = relative[:-3] + '.mpy'
            if target in targets:
                raise ValueError('compact application has duplicate path: ' + target)
            source = compact_overrides.pop(relative, None)
            if source is None:
                alias = MPY_SOURCE_ALIASES.get(relative)
                source = (
                    path.with_name(alias).read_bytes()
                    if alias else path.read_bytes()
                )
            source = chunk_runtime_string_literals(source)
            source_path = temporary / ('source-' + str(index) + '.py')
            output_path = temporary / ('module-' + str(index) + '.mpy')
            source_path.write_bytes(source)
            try:
                result = subprocess.run(
                    (
                        str(compiler), '-O3', '-s', relative,
                        '-o', str(output_path), str(source_path),
                    ),
                    capture_output=True, text=True, check=False,
                )
            except OSError as exc:
                raise ValueError('mpy-cross could not run: ' + str(exc))
            if result.returncode or not output_path.is_file():
                detail = (result.stderr or result.stdout or 'unknown compiler error').strip()
                raise ValueError('mpy-cross failed for ' + relative + ': ' + detail)
            maximum = COMPACT_MPY_SIZE_LIMITS.get(target)
            compiled_size = output_path.stat().st_size
            if maximum is not None and compiled_size > maximum:
                raise ValueError(
                    target + ' exceeds compact bytecode limit: ' +
                    str(compiled_size) + ' > ' + str(maximum)
                )
            compact_files.append((target, path))
            compact_overrides[target] = output_path.read_bytes()
            targets.add(target)
    return compact_files, compact_overrides


def load_ignore_patterns(root):
    path = root / IGNORE_FILE
    if not path.is_file():
        return []
    patterns = []
    for line in path.read_text().splitlines():
        pattern = line.strip()
        if pattern and not pattern.startswith('#'):
            patterns.append(pattern.replace('\\', '/'))
    return patterns


def is_ignored(relative, patterns):
    relative = str(relative).replace('\\', '/').lstrip('/')
    parts = relative.split('/')
    for pattern in patterns:
        if pattern.endswith('/'):
            directory = pattern.rstrip('/')
            if '/' in directory:
                if relative == directory or relative.startswith(directory + '/'):
                    return True
            elif directory in parts[:-1]:
                return True
            continue
        if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(parts[-1], pattern):
            return True
    return False


def load_json_object(path, label):
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        raise ValueError(label + ' file not found: ' + str(path))
    except json.JSONDecodeError as exc:
        raise ValueError('invalid ' + label + ' JSON: ' + str(exc))
    if not isinstance(value, dict):
        raise ValueError(label + ' must contain a JSON object')
    return value


def device_type_registry(root):
    registry = {}
    directory = root / 'device_modules'
    for path in sorted(directory.glob('*.py')):
        if path.name in LOADER_EXCLUDED_MODULES:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        device_types = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if 'DEVICE_TYPE' in names or 'SWITCH_DEVICE_TYPE' in names:
                    try:
                        device_types.append(ast.literal_eval(node.value))
                    except Exception:
                        continue
        for device_type in device_types:
            if not isinstance(device_type, dict):
                continue
            device_class = device_type.get('class')
            subclasses = device_type.get('subclass', {})
            subclass_names = subclasses.keys() if isinstance(subclasses, dict) else subclasses
            for subclass in subclass_names:
                key = (str(device_class), str(subclass))
                if key in registry and registry[key] != path:
                    raise ValueError(
                        'multiple drivers support ' + key[0] + ':' + key[1] +
                        ' - ' + registry[key].name + ', ' + path.name
                    )
                registry[key] = path
    return registry


def configured_driver_files(root, module_config):
    devices = module_config.get('devices')
    if not isinstance(devices, list):
        raise ValueError('module settings must contain a devices list')
    registry = device_type_registry(root)
    selected = set()
    configured_types = []
    for index, device in enumerate(devices):
        if not isinstance(device, dict) or not isinstance(device.get('type'), dict):
            raise ValueError('module settings device ' + str(index) + ' has no valid type')
        key = (
            str(device['type'].get('class', '')),
            str(device['type'].get('subclass', ''))
        )
        if key not in registry:
            raise ValueError('no driver found for configured type ' + key[0] + ':' + key[1])
        selected.add(registry[key])
        configured_types.append(key[0] + ':' + key[1])
    return selected, configured_types


def relative_device_dependencies(path, root):
    dependencies = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        modules = []
        if node.module:
            modules.append(node.module.split('.')[0])
        else:
            modules.extend(alias.name.split('.')[0] for alias in node.names)
        for module in modules:
            candidate = root / 'device_modules' / (module + '.py')
            if candidate.is_file():
                dependencies.add(candidate)
    return dependencies


def expand_device_dependencies(selected, root):
    expanded = set(selected)
    pending = list(selected)
    while pending:
        path = pending.pop()
        for dependency in relative_device_dependencies(path, root):
            if dependency not in expanded:
                expanded.add(dependency)
                pending.append(dependency)
    return expanded


def selected_library_files(selected_drivers, root):
    files = {root / name for name in CORE_LIB_FILES}
    names = {path.name for path in selected_drivers}
    if names.intersection({'switch_onoff.py', 'switch_dimmer.py'}):
        files.add(root / 'lib/primitives/pushbutton.py')
        files.add(root / 'lib/primitives/delay_ms.py')
    if 'hcsr04.py' in names:
        files.add(root / 'lib/uhcsr04/hcsr04.py')
    return files


def _integer_constant(path, constant):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if constant in names:
            value = ast.literal_eval(node.value)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    raise ValueError(str(path) + ' must define positive integer ' + constant)


def application_components(root):
    modules = {}
    for path in sorted(set(device_type_registry(root).values())):
        modules[path.stem] = _integer_constant(path, 'MODULE_VERSION')
    return {
        'runtime': _integer_constant(root / 'component_versions.py', 'RUNTIME_VERSION'),
        'modules': modules,
    }


def generated_driver_index(root):
    entries = []
    for key, path in sorted(device_type_registry(root).items()):
        entries.append("    %r: %r," % (key[0] + ':' + key[1], path.stem))
    versions = []
    for name, version in sorted(application_components(root)['modules'].items()):
        versions.append("    %r: %d," % (name, version))
    return (
        '"""Generated mapping used to import only configured IoT-MD device drivers."""\n\n'
        'DRIVER_MODULES = {\n' + '\n'.join(entries) + '\n}\n\n'
        'DRIVER_VERSIONS = {\n' + '\n'.join(versions) + '\n}\n'
    ).encode()


def certificate_entry(specification):
    """Resolve an optional target-relative certificate specification."""
    value = str(specification)
    if '=' in value:
        target, source = value.split('=', 1)
    else:
        source = value
        target = Path(source).name
    target = target.replace('\\', '/')
    parts = target.split('/')
    if (
        not source or not target or target.startswith('/') or
        any(part in ('', '.', '..') for part in parts)
    ):
        raise ValueError(
            'certificate target must be a safe path relative to certs/: ' + target
        )
    return 'certs/' + target, Path(source).resolve()


def collect_files(
    root,
    include_protected=False,
    certificates=(),
    protected_only=False,
    include_settings=False,
    device_settings_path=None,
    module_settings_path=None,
    universal=False
):
    paths = []
    ignore_patterns = load_ignore_patterns(root)
    if device_settings_path is not None:
        raise ValueError(
            'device_settings.json is no longer supported; device policy is '
            'frozen and app policy is carried by app_settings.json'
        )
    if not protected_only:
        settings_requested = bool(include_settings or module_settings_path is not None)
        if universal:
            selected_drivers = set(device_type_registry(root).values())
            module_path = None
            if settings_requested:
                if include_settings or module_settings_path is not None:
                    candidate = Path(
                        module_settings_path or root / 'module_settings.json'
                    ).resolve()
                    if candidate.is_file():
                        load_json_object(candidate, 'module settings')
                        module_path = candidate
                    elif module_settings_path is not None:
                        raise ValueError('module settings file not found: ' + str(candidate))
        else:
            module_path = Path(
                module_settings_path or root / 'module_settings.json'
            ).resolve()
            module_config = load_json_object(module_path, 'module settings')
            selected_drivers, configured_types = configured_driver_files(root, module_config)
        selected_drivers = expand_device_dependencies(selected_drivers, root)

        for name in CORE_FILES + CORE_DEVICE_MODULES:
            path = root / name
            if not path.is_file():
                raise ValueError('required runtime file not found: ' + name)
            paths.append((name, path))
        # Alpha branches carry the next-generation runtime beside the proven
        # product runtime.  Treat it as an atomic package when the v3 contract
        # root exists, while keeping the generic/v2 bundle builder reusable by
        # synthetic roots and maintenance tooling that deliberately omit v3.
        if (root / 'v3').is_dir():
            for name in V3_ALPHA_FILES:
                path = root / name
                if not path.is_file():
                    raise ValueError('required v3 alpha runtime file not found: ' + name)
                paths.append((name, path))
        for path in sorted(selected_drivers | selected_library_files(selected_drivers, root)):
            relative = path.relative_to(root).as_posix()
            if not path.is_file():
                raise ValueError('required dependency not found: ' + relative)
            if not is_ignored(relative, ignore_patterns):
                paths.append((relative, path))
        if settings_requested:
            if module_path is not None:
                paths.append(('module_settings.json', module_path))
    if include_protected:
        for cert in certificates:
            relative, path = certificate_entry(cert)
            paths.append((relative, path))
    deduplicated = {}
    for relative, path in paths:
        if relative in deduplicated and deduplicated[relative] != path:
            raise ValueError('multiple source files target ' + relative)
        deduplicated[relative] = path
    return sorted(deduplicated.items())


def load_signing_key(path):
    if not path:
        return b''
    try:
        value = Path(path).read_bytes().strip()
    except OSError as exc:
        raise ValueError('signing key could not be read: ' + str(exc))
    if len(value) == 64:
        try:
            value = bytes.fromhex(value.decode())
        except ValueError:
            pass
    if len(value) != 32:
        raise ValueError('signing key must be exactly 32 bytes')
    return value


def build_bundle(
    output, version, files, content_overrides=None, signing_key=b'',
    release_sequence=1,
    minimum_core_api=8, minimum_config_api=3, maximum_config_api=3,
    components=None
):
    output.parent.mkdir(parents=True, exist_ok=True)
    content_overrides = content_overrides or {}
    entries = []
    for relative, path in files:
        data = content_overrides.get(relative)
        if data is None:
            data = path.read_bytes()
        entries.append({
            'path': relative,
            'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest()
        })
    manifest_object = {
        'format_version': 6,
        'target_board': 'esp32-s3',
        'min_recovery_api': 6,
        'max_recovery_api': 6,
        'version': version,
        'release_sequence': int(release_sequence),
        'minimum_core_api': int(minimum_core_api),
        'minimum_config_api': int(minimum_config_api),
        'maximum_config_api': int(maximum_config_api),
        'components': components or {'runtime': 1, 'modules': {}},
        'files': entries
    }
    if signing_key:
        manifest_object['signature_scheme'] = SIGNATURE_SCHEME
        manifest_object['signature'] = sign_manifest(
            'iotapp', manifest_object, signing_key
        )
    manifest = json.dumps(
        manifest_object,
        separators=(',', ':')
    ).encode()
    with output.open('wb') as bundle:
        bundle.write(MAGIC)
        bundle.write(len(manifest).to_bytes(4, 'big'))
        bundle.write(manifest)
        for relative, path in files:
            override = content_overrides.get(relative)
            if override is not None:
                bundle.write(override)
            else:
                with path.open('rb') as source:
                    while True:
                        chunk = source.read(65536)
                        if not chunk:
                            break
                        bundle.write(chunk)
    return entries


def main():
    parser = argparse.ArgumentParser(description='Build a MicroPython application update bundle')
    parser.add_argument('output', help='Output .iotapp bundle path')
    parser.add_argument('--version', required=True, help='Application version label')
    parser.add_argument(
        '--universal', action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--release-sequence', required=True, type=int,
        help='Fleet-wide monotonically increasing signed release number'
    )
    parser.add_argument('--include-protected', action='store_true', help='Include explicitly selected certificates')
    parser.add_argument('--protected-only', action='store_true', help='Exclude application files and build only certificate maintenance content')
    parser.add_argument(
        '--include-module-settings', action='store_true',
        help='Include module_settings.json as an optional user configuration overwrite'
    )
    parser.add_argument(
        '--module-settings',
        help='Module settings JSON to package instead of the default module_settings.json'
    )
    parser.add_argument(
        '--certificate', action='append', default=[],
        help='Certificate/key as PATH or TARGET=PATH; TARGET is relative to certs/'
    )
    parser.add_argument(
        '--signing-key',
        required=True,
        help='32-byte raw or 64-character hex ECDSA P-256 private key; never copy it to a device'
    )
    parser.add_argument(
        '--allow-dirty', action='store_true',
        help='permit a non-production bundle stamped with the current dirty revision'
    )
    parser.add_argument(
        '--mpy-cross',
        help='Compile importable application modules to compact .mpy bytecode'
    )
    args = parser.parse_args()

    if args.protected_only and (
        args.include_module_settings or
        args.module_settings
    ):
        parser.error(
            '--protected-only cannot be combined with settings options; '
            'build an application/settings bundle separately'
        )
    universal = not args.protected_only
    if universal and (args.include_protected or args.certificate):
        parser.error('application releases cannot embed certificates')
    if args.release_sequence <= 0:
        parser.error('--release-sequence must be positive')

    root = Path(__file__).resolve().parents[1]
    include_protected = args.include_protected or args.protected_only or bool(args.certificate)
    try:
        source_revision = git_source_revision(root, args.allow_dirty)
        signing_key = load_signing_key(args.signing_key)
        files = collect_files(
            root,
            include_protected,
            args.certificate,
            args.protected_only,
            args.include_module_settings,
            None,
            args.module_settings,
            universal
        )
        if not args.protected_only and not universal:
            module_path = Path(
                args.module_settings or root / 'module_settings.json'
            ).resolve()
            module_config = load_json_object(module_path, 'module settings')
            _, configured_types = configured_driver_files(root, module_config)
            print('module settings:', module_path)
            print('configured types:', ', '.join(configured_types))
    except ValueError as exc:
        raise SystemExit('build failed: ' + str(exc))
    if not files:
        raise SystemExit('no files selected for the update bundle')
    content_overrides = {}
    if not args.protected_only:
        content_overrides['device_modules/driver_index.py'] = generated_driver_index(root)
        component_versions = (root / 'component_versions.py').read_bytes()
        content_overrides['component_versions.py'] = (
            component_versions + b'\nSOURCE_REVISION = ' + repr(source_revision).encode() +
            b'\nSOURCE_REVISION_MARKER = ' + repr(source_marker(source_revision)).encode() +
            b'\n'
        )
        if args.mpy_cross:
            try:
                files, content_overrides = compact_application_files(
                    files, content_overrides, args.mpy_cross
                )
            except ValueError as exc:
                raise SystemExit('build failed: ' + str(exc))
    entries = build_bundle(
        Path(args.output),
        args.version,
        files,
        content_overrides,
        signing_key,
        release_sequence=args.release_sequence,
        components=application_components(root) if not args.protected_only else {
            'runtime': 1, 'modules': {}
        }
    )
    print('created', args.output, 'with', len(entries), 'files')
    for entry in entries:
        print('  ', entry['path'])
    print('signature:', SIGNATURE_SCHEME)
    print('source revision:', source_revision)


if __name__ == '__main__':
    main()
