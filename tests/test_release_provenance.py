import os
import tempfile
import unittest
from pathlib import Path

from tools.build_firmware_update import build_firmware_bundle
from tools.build_micropython_firmware import (
    validate_ota_headroom, write_core_metadata,
)
from tools.build_update import build_bundle
from tools.generate_secure_boot_key import generation_command
from tools.publish_release import publish_release
from tools.release_provenance import embedded_source_revision, source_marker


class ReleaseProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temporary = tempfile.TemporaryDirectory()
        os.chdir(self.temporary.name)
        self.private_key = bytes(range(1, 33))
        self.revision = '1' * 40

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.temporary.cleanup()

    def test_marker_is_unambiguous(self):
        payload = b'prefix' + source_marker(self.revision) + b'suffix'
        self.assertEqual(embedded_source_revision(payload), self.revision)
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            embedded_source_revision(payload + source_marker('2' * 40))

    def test_publisher_requires_matching_signed_application_provenance(self):
        source = Path('component_versions.py')
        source.write_bytes(b'VALUE=1\nMARKER=' + repr(source_marker(self.revision)).encode())
        build_bundle(
            Path('application.hamd'), '1.9.0', [('component_versions.py', source)],
            signing_key=self.private_key, release_sequence=1900,
        )
        _descriptor, _bundle, published = publish_release(
            'application.hamd', 'site', 'https://updates.example/hamd',
            'stable', self.private_key, source_revision=self.revision,
        )
        self.assertIn(self.revision, published['notes'])
        with self.assertRaisesRegex(ValueError, 'does not match'):
            publish_release(
                'application.hamd', 'other-site', 'https://updates.example/hamd',
                'stable', self.private_key, source_revision='2' * 40,
            )

        damaged = bytearray(Path('application.hamd').read_bytes())
        damaged[-1] ^= 1
        Path('damaged.hamd').write_bytes(damaged)
        with self.assertRaisesRegex(ValueError, 'payload hash failed'):
            publish_release(
                'damaged.hamd', 'damaged-site', 'https://updates.example/hamd',
                'stable', self.private_key,
            )

    def test_core_metadata_provenance_is_covered_by_firmware_hash(self):
        metadata = write_core_metadata('generated', '1.9.0', 1900, self.revision)
        marker = source_marker(self.revision)
        self.assertIn(marker, metadata.read_bytes())
        image = Path('micropython.bin')
        image.write_bytes(b'\xe9' + metadata.read_bytes())
        build_firmware_bundle(
            image, Path('firmware.hamf'), '1.9.0', signing_key=self.private_key,
            release_sequence=1900,
        )
        publish_release(
            'firmware.hamf', 'firmware-site', 'https://updates.example/hamd',
            'stable', self.private_key, source_revision=self.revision,
        )

    def test_ota_headroom_warns_and_fails_at_locked_thresholds(self):
        lock = {
            'ota_partition_bytes': 1000,
            'ota_warning_percent': 85,
            'ota_failure_percent': 95,
        }
        self.assertEqual(validate_ota_headroom(840, lock), (84.0, False))
        self.assertEqual(validate_ota_headroom(850, lock), (85.0, True))
        with self.assertRaisesRegex(ValueError, '95.0%'):
            validate_ota_headroom(950, lock)

    def test_secure_boot_helper_uses_esp_idf_55_command_name(self):
        command = generation_command('/idf', '/tmp/key.pem', 'python')
        self.assertIn('generate_signing_key', command)
        self.assertNotIn('generate-signing-key', command)


if __name__ == '__main__':
    unittest.main()
