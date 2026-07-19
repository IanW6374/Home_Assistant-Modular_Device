#!/usr/bin/env python3
"""Build a hash-verified application bundle for portal upload."""

import argparse
import ast
import fnmatch
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update_security import SIGNATURE_SCHEME, sign_manifest


MAGIC = b'HAMD1\n'
CORE_FILES = (
    'HA-Device.py',
    'settings_loader.py',
    'local_display.py',
    'web_portal.py',
    'release_update.py',
)
CORE_DEVICE_MODULES = (
    'device_modules/__init__.py',
    'device_modules/loader.py',
    'device_modules/base.py',
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
    'spi_bus.py', 'template.py', 'validation.py'
}
IGNORE_FILE = '.build_update_ignore'


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
    if not isinstance(devices, list) or not devices:
        raise ValueError('module settings must contain a non-empty devices list')
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


def resolve_settings_paths(root, device_settings_path=None, module_settings_path=None):
    device_path = Path(device_settings_path or root / 'device_settings.json').resolve()
    device_config = load_json_object(device_path, 'device settings')
    if not device_config.get('device', {}).get('module_settings_file'):
        raise ValueError('device settings does not define device.module_settings_file')
    module_path = Path(module_settings_path or root / 'module_settings.json').resolve()
    module_config = load_json_object(module_path, 'module settings')
    return device_path, device_config, module_path, module_config


def normalized_device_settings(device_config):
    normalized = json.loads(json.dumps(device_config))
    normalized['device']['module_settings_file'] = 'module_settings.json'
    return normalized


def collect_files(
    root,
    include_protected=False,
    certificates=(),
    protected_only=False,
    include_settings=False,
    device_settings_path=None,
    module_settings_path=None
):
    paths = []
    ignore_patterns = load_ignore_patterns(root)
    if not protected_only:
        device_path, _, module_path, module_config = resolve_settings_paths(
            root, device_settings_path, module_settings_path
        )
        selected_drivers, configured_types = configured_driver_files(root, module_config)
        selected_drivers = expand_device_dependencies(selected_drivers, root)

        for name in CORE_FILES + CORE_DEVICE_MODULES:
            path = root / name
            if not path.is_file():
                raise ValueError('required runtime file not found: ' + name)
            paths.append((name, path))
        for path in sorted(selected_drivers | selected_library_files(selected_drivers, root)):
            relative = path.relative_to(root).as_posix()
            if not path.is_file():
                raise ValueError('required dependency not found: ' + relative)
            if not is_ignored(relative, ignore_patterns):
                paths.append((relative, path))
        include_selected_settings = (
            include_settings or
            device_settings_path is not None or
            module_settings_path is not None
        )
        if include_selected_settings:
            paths.append(('device_settings.json', device_path))
            paths.append(('module_settings.json', module_path))
    if include_protected:
        secrets = root / 'secrets.py'
        if secrets.is_file():
            paths.append(('secrets.py', secrets))
        for cert in certificates:
            path = Path(cert).resolve()
            paths.append(('certs/' + path.name, path))
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
    if len(value) < 32:
        raise ValueError('signing key must contain at least 32 bytes')
    return value


def build_bundle(output, version, files, content_overrides=None, signing_key=b''):
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
        'format_version': 2,
        'target_board': 'esp32-s3',
        'min_recovery_api': 2,
        'max_recovery_api': 2,
        'version': version,
        'files': entries
    }
    if signing_key:
        manifest_object['signature_scheme'] = SIGNATURE_SCHEME
        manifest_object['signature'] = sign_manifest(
            'hamd', manifest_object, signing_key
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
    parser.add_argument('output', help='Output .hamd bundle path')
    parser.add_argument('--version', required=True, help='Application version label')
    parser.add_argument('--include-protected', action='store_true', help='Include local secrets.py')
    parser.add_argument('--protected-only', action='store_true', help='Exclude application files and build a secrets/certificate maintenance bundle')
    parser.add_argument('--include-settings', action='store_true', help='Include device_settings.json and module_settings.json')
    parser.add_argument('--device-settings', help='Device settings JSON used to select the active module settings file')
    parser.add_argument('--module-settings', help='Module settings JSON to analyse instead of the filename in device settings')
    parser.add_argument('--certificate', action='append', default=[], help='Certificate/key file to place under certs/')
    parser.add_argument(
        '--signing-key',
        help='32-byte raw or 64-character hex HMAC key; signed bundles are required once the same key is provisioned on the device'
    )
    args = parser.parse_args()

    if args.protected_only and (
        args.include_settings or
        args.device_settings or
        args.module_settings
    ):
        parser.error(
            '--protected-only cannot be combined with settings options; '
            'build an application/settings bundle separately'
        )

    root = Path(__file__).resolve().parents[1]
    include_protected = args.include_protected or args.protected_only or bool(args.certificate)
    try:
        signing_key = load_signing_key(args.signing_key)
        files = collect_files(
            root,
            include_protected,
            args.certificate,
            args.protected_only,
            args.include_settings,
            args.device_settings,
            args.module_settings
        )
        if not args.protected_only:
            device_path, device_config, module_path, module_config = resolve_settings_paths(
                root, args.device_settings, args.module_settings
            )
            _, configured_types = configured_driver_files(root, module_config)
            print('device settings:', device_path)
            print('module settings:', module_path)
            print('configured types:', ', '.join(configured_types))
    except ValueError as exc:
        raise SystemExit('build failed: ' + str(exc))
    if not files:
        raise SystemExit('no files selected for the update bundle')
    content_overrides = {}
    settings_included = any(relative == 'device_settings.json' for relative, _ in files)
    if settings_included:
        content_overrides['device_settings.json'] = json.dumps(
            normalized_device_settings(device_config),
            indent=2
        ).encode()
    entries = build_bundle(
        Path(args.output),
        args.version,
        files,
        content_overrides,
        signing_key
    )
    print('created', args.output, 'with', len(entries), 'files')
    for entry in entries:
        print('  ', entry['path'])
    print('signature:', 'hmac-sha256' if signing_key else 'unsigned development bundle')


if __name__ == '__main__':
    main()
