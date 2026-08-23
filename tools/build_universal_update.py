#!/usr/bin/env python3
"""Build a signed universal HAMD core-and-application update bundle."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_security
try:
    from .build_update import load_signing_key
    from .publish_release import (
        read_bundle_manifest, verify_bundle_manifest, verify_bundle_payload,
    )
except ImportError:
    from build_update import load_signing_key
    from publish_release import (
        read_bundle_manifest, verify_bundle_manifest, verify_bundle_payload,
    )


MAGIC = b'HAMU1\n'


def _component(path, expected_type, signing_key):
    path = Path(path)
    release_type, manifest = read_bundle_manifest(path)
    if release_type != expected_type:
        raise ValueError(
            str(path) + ' is ' + release_type + ', expected ' + expected_type
        )
    verify_bundle_manifest(release_type, manifest, signing_key)
    source_revision = verify_bundle_payload(path, release_type, manifest)
    return {
        'path': path,
        'version': str(manifest.get('version', '')),
        'release_sequence': int(manifest.get('release_sequence', 0)),
        'size': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'source_revision': source_revision,
    }


def build_universal_bundle(
    output, application_bundle, firmware_bundle, version,
    release_sequence, signing_key, activation_order=None,
    maintenance_required=True, rollback_policy='paired', trial_timeout_s=180
):
    application = _component(application_bundle, 'application', signing_key)
    firmware = _component(firmware_bundle, 'firmware', signing_key)
    release_sequence = int(release_sequence)
    if release_sequence <= 0:
        raise ValueError('universal release sequence must be positive')
    if (
        application['release_sequence'] != release_sequence or
        firmware['release_sequence'] != release_sequence
    ):
        raise ValueError(
            'inner application, firmware and universal release sequences must match'
        )
    expected_version = str(version)
    if (
        application['version'] != expected_version or
        firmware['version'] != expected_version
    ):
        raise ValueError(
            'inner application, firmware and universal version labels must match'
        )
    if bool(application['source_revision']) != bool(firmware['source_revision']):
        raise ValueError('universal components have inconsistent source provenance')
    if (
        application['source_revision'] and
        application['source_revision'] != firmware['source_revision']
    ):
        raise ValueError('universal components were built from different source revisions')
    activation_order = activation_order or ['application', 'firmware']
    if activation_order not in (
        ['application', 'firmware'], ['firmware', 'application']
    ):
        raise ValueError('universal activation order is invalid')
    if rollback_policy not in ('paired', 'independent', 'manual'):
        raise ValueError('universal rollback policy is invalid')
    trial_timeout_s = int(trial_timeout_s)
    if trial_timeout_s < 30 or trial_timeout_s > 3600:
        raise ValueError('universal trial timeout is invalid')
    manifest_object = {
        'format_version': 2,
        'target_board': 'esp32-s3',
        'version': str(version),
        'release_sequence': release_sequence,
        'firmware': {
            key: firmware[key]
            for key in ('version', 'release_sequence', 'size', 'sha256')
        },
        'application': {
            key: application[key]
            for key in ('version', 'release_sequence', 'size', 'sha256')
        },
        'signature_scheme': update_security.SIGNATURE_SCHEME,
    }
    manifest_object.update({
        'activation_order': activation_order,
        'maintenance_required': bool(maintenance_required),
        'rollback_policy': rollback_policy,
        'trial_timeout_s': trial_timeout_s,
    })
    manifest_object['signature'] = update_security.sign_manifest(
        'hamu', manifest_object, signing_key
    )
    manifest = json.dumps(manifest_object, separators=(',', ':')).encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as stream:
        stream.write(MAGIC)
        stream.write(len(manifest).to_bytes(4, 'big'))
        stream.write(manifest)
        for component in (firmware, application):
            with component['path'].open('rb') as source:
                while True:
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    stream.write(chunk)
    return manifest_object


def main():
    parser = argparse.ArgumentParser(
        description='Build a signed .hamu universal upgrade bundle'
    )
    parser.add_argument('output')
    parser.add_argument('--application', required=True)
    parser.add_argument('--firmware', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--release-sequence', required=True, type=int)
    parser.add_argument('--signing-key', required=True)
    parser.add_argument(
        '--activation-order', choices=('application-first', 'firmware-first'),
        default='application-first'
    )
    parser.add_argument(
        '--no-maintenance-window', action='store_true',
        help='permit activation outside a fleet maintenance window'
    )
    parser.add_argument(
        '--rollback-policy', choices=('paired', 'independent', 'manual'),
        default='paired'
    )
    parser.add_argument('--trial-timeout-s', type=int, default=180)
    args = parser.parse_args()
    try:
        manifest = build_universal_bundle(
            args.output, args.application, args.firmware, args.version,
            args.release_sequence, load_signing_key(args.signing_key),
            ['application', 'firmware'] if args.activation_order == 'application-first'
            else ['firmware', 'application'],
            not args.no_maintenance_window, args.rollback_policy,
            args.trial_timeout_s
        )
    except ValueError as exc:
        raise SystemExit('build failed: ' + str(exc))
    print('created', args.output)
    print('application:', manifest['application']['version'])
    print('firmware:', manifest['firmware']['version'])
    print('signature:', update_security.SIGNATURE_SCHEME)


if __name__ == '__main__':
    main()
