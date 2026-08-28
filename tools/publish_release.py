#!/usr/bin/env python3
"""Publish a signed IoT-MD application or firmware bundle to a static host tree."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_security
try:
    from .build_update import load_signing_key
    from .release_provenance import (
        clean_source_revision, embedded_source_revision,
        git_source_revision as _git_source_revision,
    )
except ImportError:  # Direct execution: python tools/publish_release.py ...
    from build_update import load_signing_key
    from release_provenance import (
        clean_source_revision, embedded_source_revision,
        git_source_revision as _git_source_revision,
    )


BUNDLE_TYPES = {
    b'IOTA1\n': 'application',
    b'IOTC1\n': 'firmware',
}


def git_source_revision(root, allow_dirty=False):
    return _git_source_revision(root, allow_dirty)


def notes_with_source(notes, source_revision=''):
    notes = str(notes).strip()
    source_revision = str(source_revision).strip().lower()
    if source_revision:
        clean_revision = source_revision.removesuffix('-dirty')
        if (
            len(clean_revision) != 40 or
            any(character not in '0123456789abcdef' for character in clean_revision)
        ):
            raise ValueError('source revision is invalid')
        notes = (notes + ' | ' if notes else '') + 'Source: ' + source_revision
    if len(notes) > 512:
        raise ValueError('release notes and source provenance exceed 512 characters')
    return notes


def read_bundle_manifest(path):
    with Path(path).open('rb') as stream:
        magic = stream.read(6)
        release_type = BUNDLE_TYPES.get(magic)
        if not release_type:
            raise ValueError('input is not an IoT-MD .iotapp or .iotcore bundle')
        length = int.from_bytes(stream.read(4), 'big')
        if length <= 0 or length > 65535:
            raise ValueError('bundle manifest length is invalid')
        manifest = json.loads(stream.read(length).decode())
    return release_type, manifest


def verify_bundle_manifest(release_type, manifest, private_key):
    public = update_security.public_key_bytes(private_key)
    point = (
        update_security._bytes_to_int(public[:32]),
        update_security._bytes_to_int(public[32:]),
    )
    signature = str(manifest.get('signature', ''))
    bundle_type = 'iotapp' if release_type == 'application' else 'iotcore'
    if not update_security.verify_manifest_signature(
        bundle_type, manifest, signature, point
    ):
        raise ValueError('bundle is not signed by the supplied release key')


def verify_bundle_payload(path, release_type, manifest):
    """Verify signed payload lengths/digests and return embedded provenance."""
    path = Path(path)
    with path.open('rb') as stream:
        stream.read(6)
        manifest_size = int.from_bytes(stream.read(4), 'big')
        stream.read(manifest_size)
        signed_content = bytearray()
        if release_type == 'application':
            for entry in manifest.get('files', []):
                size = int(entry.get('size', 0))
                if size < 0:
                    raise ValueError('bundle file size is invalid')
                payload = stream.read(size)
                if len(payload) != size:
                    raise ValueError('application bundle payload is truncated')
                if hashlib.sha256(payload).hexdigest() != str(
                    entry.get('sha256', '')
                ).lower():
                    raise ValueError(
                        'application bundle payload hash failed for ' +
                        str(entry.get('path', ''))
                    )
                signed_content.extend(payload)
        else:
            size = int(manifest.get('size', 0))
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError('firmware bundle payload is truncated')
            if hashlib.sha256(payload).hexdigest() != str(
                manifest.get('sha256', '')
            ).lower():
                raise ValueError('firmware bundle payload hash failed')
            signed_content.extend(payload)
        if stream.read(1):
            raise ValueError('bundle contains unsigned trailing content')
    return embedded_source_revision(signed_content)


def publish_release(
    bundle, output_root, base_url, channel, signing_key,
    notes='', published_at='', source_revision=''
):
    bundle = Path(bundle).resolve()
    output_root = Path(output_root).resolve()
    release_type, manifest = read_bundle_manifest(bundle)
    verify_bundle_manifest(release_type, manifest, signing_key)
    embedded_revision = verify_bundle_payload(bundle, release_type, manifest)
    if source_revision:
        expected_revision, _dirty = clean_source_revision(source_revision)
        if not embedded_revision:
            raise ValueError('bundle has no signed embedded source revision')
        if embedded_revision != expected_revision:
            raise ValueError(
                'bundle source revision ' + embedded_revision +
                ' does not match publisher revision ' + expected_revision
            )
    sequence = int(manifest.get('release_sequence', 0))
    if sequence <= 0:
        raise ValueError('bundle has no signed release sequence')

    bundle_directory = output_root / 'bundles'
    channel_directory = output_root / channel
    bundle_directory.mkdir(parents=True, exist_ok=True)
    channel_directory.mkdir(parents=True, exist_ok=True)
    published_bundle = bundle_directory / bundle.name
    if bundle != published_bundle:
        shutil.copy2(bundle, published_bundle)
    digest = hashlib.sha256(published_bundle.read_bytes()).hexdigest()
    base_url = str(base_url).rstrip('/')
    if not base_url.startswith('https://'):
        raise ValueError('base URL must use HTTPS')

    descriptor = {
        'format_version': 2,
        'target_board': str(manifest.get('target_board', manifest.get('platform', ''))),
        'channel': str(channel),
        'type': release_type,
        'version': str(manifest.get('version', '')),
        'release_sequence': sequence,
        'url': base_url + '/bundles/' + bundle.name,
        'size': published_bundle.stat().st_size,
        'sha256': digest,
        'minimum_core_api': int(manifest.get('minimum_core_api', 7)),
        'minimum_config_api': int(
            manifest.get('minimum_config_api', update_security.CONFIG_API_VERSION)
        ),
        'maximum_config_api': int(
            manifest.get('maximum_config_api', update_security.CONFIG_API_VERSION)
        ),
        'notes': notes_with_source(notes, source_revision),
        'published_at': published_at or datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat().replace('+00:00', 'Z'),
        'signature_scheme': update_security.SIGNATURE_SCHEME,
    }
    if release_type == 'application':
        descriptor['components'] = manifest.get('components', {})
    descriptor['signature'] = update_security.sign_manifest(
        'release', descriptor, signing_key
    )
    descriptor_path = channel_directory / 'latest.json'
    existing_releases = []
    if descriptor_path.is_file():
        try:
            existing = json.loads(descriptor_path.read_text())
            existing_releases = existing.get('releases', [existing])
        except (OSError, ValueError, TypeError):
            existing_releases = []
    releases_by_type = {}
    for existing in existing_releases:
        if (
            isinstance(existing, dict) and
            existing.get('type') in BUNDLE_TYPES.values()
        ):
            releases_by_type[existing['type']] = {
                key: value for key, value in existing.items()
                if key != 'releases'
            }
    releases_by_type[release_type] = descriptor
    releases = [
        releases_by_type[item]
        for item in ('application', 'firmware')
        if item in releases_by_type
    ]
    # Keep the application at the top level as a bridge for devices that
    # predate the multi-release index. Installing it adds multi-release
    # selection to the active application slot; the unchanged index can then
    # direct that device to firmware.
    fallback = releases_by_type.get('application', descriptor)
    channel_index = dict(fallback)
    channel_index['releases'] = releases
    descriptor_path.write_text(json.dumps(channel_index, indent=2) + '\n')
    if bundle.parent == output_root and bundle != published_bundle:
        bundle.unlink()
    return descriptor_path, published_bundle, descriptor


def main():
    parser = argparse.ArgumentParser(
        description='Create a static, signed IoT-MD stable/beta release tree'
    )
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--channel', required=True, choices=('stable', 'beta'))
    parser.add_argument('--signing-key', required=True)
    parser.add_argument('--notes', default='')
    parser.add_argument('--published-at', default='')
    parser.add_argument('--source-revision', default='')
    parser.add_argument(
        '--allow-dirty', action='store_true',
        help='permit a non-production descriptor stamped with a -dirty revision'
    )
    args = parser.parse_args()
    try:
        source_revision = args.source_revision or git_source_revision(
            Path(__file__).resolve().parents[1], args.allow_dirty
        )
        descriptor_path, published_bundle, descriptor = publish_release(
            args.bundle, args.output_root, args.base_url, args.channel,
            load_signing_key(args.signing_key), args.notes, args.published_at,
            source_revision
        )
    except ValueError as exc:
        raise SystemExit('publish failed: ' + str(exc))
    print('published bundle', published_bundle)
    print('published descriptor', descriptor_path)
    print('release', descriptor['channel'], descriptor['type'], descriptor['version'])
    print('release sequence', descriptor['release_sequence'])


if __name__ == '__main__':
    main()
