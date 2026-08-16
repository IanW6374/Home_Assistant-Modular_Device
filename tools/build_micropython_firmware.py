#!/usr/bin/env python3
"""Reproducibly build and package the HAMD ESP32-S3 MicroPython firmware."""

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from build_firmware_update import build_firmware_bundle, load_signing_key
from update_security import public_key_bytes


NVS_OFFSET = 0x11000
NVS_SIZE = 0x6000
NVS_KEYS_OFFSET = 0x1A000
NVS_KEYS_SIZE = 0x1000


def write_core_metadata(directory, version, release_sequence):
    """Create build-specific frozen metadata without modifying the source tree."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / 'core_metadata.py'
    output.write_text(
        '"""Generated immutable HAMD core package identity."""\n\n'
        'CORE_FIRMWARE_VERSION = ' + repr(str(version)) + '\n'
        'RELEASE_SEQUENCE = ' + str(int(release_sequence)) + '\n'
    )
    return output


def run(command, cwd=None, capture=False, env=None):
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            env=env,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
        )
    except FileNotFoundError:
        raise SystemExit(str(command[0]) + ' was not found; activate the required build environment')
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            str(command[0]) + ' failed with exit status ' + str(exc.returncode)
        ) from None


def provision_factory_setup_nvs(
    factory_image, password_output, esp_idf, update_private_key
):
    """Embed a unique setup AP key and its per-device NVS encryption keys."""
    password_output = Path(password_output).expanduser().resolve()
    if password_output.exists():
        raise SystemExit(
            'refusing to overwrite existing factory setup password: ' +
            str(password_output)
        )
    password = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip('=')[:32]
    verification_key = public_key_bytes(update_private_key)
    generator = (
        esp_idf / 'components' / 'nvs_flash' / 'nvs_partition_generator' /
        'nvs_partition_gen.py'
    )
    if not generator.is_file():
        raise SystemExit('ESP-IDF NVS partition generator not found: ' + str(generator))
    with tempfile.TemporaryDirectory(prefix='ham-factory-nvs-') as temporary_name:
        temporary = Path(temporary_name)
        csv_path = temporary / 'setup.csv'
        nvs_path = temporary / 'nvs.bin'
        key_name = 'nvs-keys.bin'
        csv_path.write_text(
            'key,type,encoding,value\n'
            'ham_config,namespace,,\n'
            'bootkey,data,hex2bin,' + password.encode().hex() + '\n'
            'verifykey,data,hex2bin,' + verification_key.hex() + '\n'
        )
        run([
            os.environ.get('PYTHON', 'python3'), str(generator), 'encrypt',
            str(csv_path), str(nvs_path), hex(NVS_SIZE), '--keygen',
            '--keyfile', key_name, '--outdir', str(temporary)
        ], cwd=temporary)
        key_path = next((path for path in (
            temporary / 'keys' / key_name, temporary / key_name
        ) if path.is_file()), None)
        if not nvs_path.is_file() or key_path is None:
            raise SystemExit('encrypted factory NVS generation did not produce both partitions')
        nvs_data = nvs_path.read_bytes()
        key_data = key_path.read_bytes()
        if len(nvs_data) != NVS_SIZE or len(key_data) != NVS_KEYS_SIZE:
            raise SystemExit('factory NVS partition sizes do not match the partition table')
        with Path(factory_image).open('r+b') as output:
            output.seek(NVS_OFFSET)
            output.write(nvs_data)
            output.seek(NVS_KEYS_OFFSET)
            output.write(key_data)

    password_output.parent.mkdir(parents=True, exist_ok=True)
    password_output.write_text(password + '\n')
    os.chmod(password_output, 0o600)
    return password_output


def main():
    parser = argparse.ArgumentParser(description='Build HAMD ESP32-S3 OTA firmware')
    parser.add_argument('--micropython-root', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--release-sequence', required=True, type=int)
    parser.add_argument('--output', required=True)
    parser.add_argument(
        '--factory-output', required=True,
        help='Full first-flash image path outside the deployable release-site tree'
    )
    parser.add_argument('--signing-key', required=True)
    parser.add_argument(
        '--production-security', action='store_true', required=True,
        help='Acknowledge that first boot permanently enables secure boot and flash encryption'
    )
    parser.add_argument(
        '--secure-boot-signing-key', required=True,
        help='ESP-IDF Secure Boot v2 RSA-3072 private key (PEM)'
    )
    parser.add_argument(
        '--factory-setup-password-output', required=True,
        help='Mode-0600 output file for the unique first-boot AP password/label'
    )
    parser.add_argument('--allow-version-mismatch', action='store_true')
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    esp_idf = Path(os.environ.get('IDF_PATH', '')).resolve()
    if not (esp_idf / 'components').is_dir():
        raise SystemExit('IDF_PATH must identify the active ESP-IDF checkout')
    micropython = Path(args.micropython_root).resolve()
    port = micropython / 'ports' / 'esp32'
    if not (port / 'Makefile').is_file():
        raise SystemExit('MicroPython ESP32 port not found: ' + str(port))
    secure_boot_key = Path(args.secure_boot_signing_key).expanduser().resolve()
    if not secure_boot_key.is_file():
        raise SystemExit('secure boot signing key not found: ' + str(secure_boot_key))
    lock = json.loads((project / 'firmware' / 'build-lock.json').read_text())
    if not args.allow_version_mismatch:
        description = run(
            ['git', 'describe', '--tags', '--always'], micropython, True
        ).stdout.strip()
        if not description.startswith(lock['micropython']):
            raise SystemExit(
                'MicroPython version mismatch: expected ' + lock['micropython'] +
                ', found ' + description + '; use --allow-version-mismatch intentionally'
            )
        idf_description = run(['idf.py', '--version'], capture=True).stdout.strip()
        if lock['esp_idf'].lstrip('v') not in idf_description:
            raise SystemExit(
                'ESP-IDF version mismatch: expected ' + lock['esp_idf'] +
                ', found ' + idf_description +
                '; activate the pinned ESP-IDF environment or use '
                '--allow-version-mismatch intentionally'
            )

    board_dir = project / 'firmware' / 'boards' / lock['board']
    user_c_modules = project / 'firmware' / 'native'
    if not (user_c_modules / 'micropython.cmake').is_file():
        raise SystemExit('HAMD native module definition not found: ' + str(user_c_modules))
    build_dir = 'build-' + lock['board'] + '-' + lock['variant'] + '-secure'
    core_metadata_dir = port / build_dir / 'hamd-generated'
    write_core_metadata(core_metadata_dir, args.version, args.release_sequence)
    mpy_cross_dir = micropython / 'mpy-cross'
    mpy_cross = mpy_cross_dir / 'build' / 'mpy-cross'

    # Build the host compiler outside the recursive ESP32 make.  Otherwise
    # GNU make propagates BUILD and FROZEN_MANIFEST into mpy-cross, causing it
    # to use the ESP32 build directory and reference mp_qstr_frozen_const_pool.
    run(['make', '-C', str(mpy_cross_dir)])
    if not mpy_cross.is_file():
        raise SystemExit('mpy-cross build did not create ' + str(mpy_cross))
    build_env = os.environ.copy()
    build_env['MICROPY_MPYCROSS'] = str(mpy_cross)

    # Environment changes are not dependencies of an existing CMake cache.
    # Reconfigure explicitly so a build that previously generated the broken
    # recursive mpy-cross rule is repaired without deleting the whole build.
    configure_command = [
        'idf.py',
        '-D', 'MICROPY_BOARD=' + lock['board'],
        '-D', 'MICROPY_BOARD_DIR=' + str(board_dir),
        '-D', 'MICROPY_BOARD_VARIANT=' + lock['variant'],
        '-D', 'MICROPY_FROZEN_MANIFEST=' + str(project / 'firmware' / 'manifest.py'),
        '-D', 'MICROPY_MANIFEST_CORE_METADATA_DIR=' + str(core_metadata_dir),
        '-D', 'USER_C_MODULES=' + str(user_c_modules),
        '-D', 'HAM_PRODUCTION_SECURITY=ON',
        '-D', 'HAM_SECURE_BOOT_SIGNING_KEY=' + str(secure_boot_key),
        '-B', build_dir,
        'reconfigure',
    ]
    command = [
        'make',
        'BOARD=' + lock['board'],
        'BOARD_DIR=' + str(board_dir),
        'BOARD_VARIANT=' + lock['variant'],
        'BUILD=' + build_dir,
        'FROZEN_MANIFEST=' + str(project / 'firmware' / 'manifest.py'),
        'USER_C_MODULES=' + str(user_c_modules),
        'CMAKE_ARGS=-DHAM_PRODUCTION_SECURITY=ON -DHAM_SECURE_BOOT_SIGNING_KEY=' +
        str(secure_boot_key) + ' -DMICROPY_MANIFEST_CORE_METADATA_DIR=' +
        str(core_metadata_dir),
    ]
    partition_target = port / 'partitions-HAM-8MiB-ota.csv'
    try:
        shutil.copy2(
            project / 'firmware' / 'partitions-8MiB-ota.csv', partition_target
        )
        # sdkconfig values override defaults, so retaining this generated file
        # can silently preserve obsolete or insecure settings. Recreate it from
        # the project-owned fragments on every reproducible build.
        generated_sdkconfig = port / build_dir / 'sdkconfig'
        try:
            generated_sdkconfig.unlink()
        except FileNotFoundError:
            pass
        run(configure_command, port, env=build_env)
        run(command, port, env=build_env)
        compile_commands = port / build_dir / 'compile_commands.json'
        if (
            not compile_commands.is_file()
            or 'hamd_crypto.c' not in compile_commands.read_text()
        ):
            raise SystemExit('refusing to package firmware without the native HAMD crypto module')
        sdkconfig = (port / build_dir / 'sdkconfig').read_text()
        required_security = (
            'CONFIG_SECURE_BOOT_V2_ENABLED=y',
            'CONFIG_SECURE_BOOT_BUILD_SIGNED_BINARIES=y',
            'CONFIG_SECURE_FLASH_ENC_ENABLED=y',
            'CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE=y',
            'CONFIG_NVS_ENCRYPTION=y',
        )
        missing = [value for value in required_security if value not in sdkconfig]
        if missing:
            raise SystemExit(
                'refusing to package an insecure production build; missing: ' +
                ', '.join(missing)
            )
        # ESP-IDF names the OTA application image ``micropython.bin``.  Some
        # distributed MicroPython builds call the same application-only image
        # ``micropython.app-bin``.  Never select ``firmware.bin`` here because
        # that is the combined USB image containing the bootloader and table.
        candidates = (
            port / build_dir / 'micropython.app-bin',
            port / build_dir / 'micropython.bin',
        )
        image = next((candidate for candidate in candidates if candidate.is_file()), None)
        if image is None:
            matches = list((port / build_dir).glob('*.app-bin'))
            if len(matches) != 1:
                raise SystemExit(
                    'built OTA application image was not found in ' +
                    str(port / build_dir)
                )
            image = matches[0]
        result = build_firmware_bundle(
            image,
            args.output,
            args.version,
            'esp32-s3',
            load_signing_key(args.signing_key),
            lock['ota_partition_bytes'],
            args.release_sequence,
        )
        combined = port / build_dir / 'firmware.bin'
        if not combined.is_file():
            raise SystemExit('combined factory image was not created: ' + str(combined))
        factory_output = Path(args.factory_output)
        if factory_output.exists():
            raise SystemExit(
                'refusing to overwrite existing factory image: ' +
                str(factory_output)
            )
        factory_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(combined, factory_output)
        setup_password_output = provision_factory_setup_nvs(
            factory_output, args.factory_setup_password_output, esp_idf,
            load_signing_key(args.signing_key)
        )
        print('created', result['output'])
        print('created irreversible first-flash image', factory_output)
        print('created unique setup password file', setup_password_output)
        print('image bytes', result['size'], 'of', lock['ota_partition_bytes'])
    finally:
        try:
            partition_target.unlink()
        except OSError:
            pass


if __name__ == '__main__':
    main()
