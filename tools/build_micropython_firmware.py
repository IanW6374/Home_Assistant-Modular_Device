#!/usr/bin/env python3
"""Reproducibly build and package the HAM ESP32-S3 MicroPython firmware."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from build_firmware_update import build_firmware_bundle, load_signing_key


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


def main():
    parser = argparse.ArgumentParser(description='Build HAM ESP32-S3 OTA firmware')
    parser.add_argument('--micropython-root', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--signing-key')
    parser.add_argument('--allow-version-mismatch', action='store_true')
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    micropython = Path(args.micropython_root).resolve()
    port = micropython / 'ports' / 'esp32'
    if not (port / 'Makefile').is_file():
        raise SystemExit('MicroPython ESP32 port not found: ' + str(port))
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
    build_dir = 'build-' + lock['board'] + '-' + lock['variant']
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
    ]
    partition_target = port / 'partitions-HAM-8MiB-ota.csv'
    try:
        shutil.copy2(
            project / 'firmware' / 'partitions-8MiB-ota.csv', partition_target
        )
        run(configure_command, port, env=build_env)
        run(command, port, env=build_env)
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
        )
        print('created', result['output'])
        print('image bytes', result['size'], 'of', lock['ota_partition_bytes'])
    finally:
        try:
            partition_target.unlink()
        except OSError:
            pass


if __name__ == '__main__':
    main()
