import os
import tempfile
import unittest
from pathlib import Path

from tools.build_firmware_update import build_firmware_bundle
from tools.build_micropython_firmware import (
    REQUIRED_PRODUCTION_SDKCONFIG, clear_module_registration_cache,
    validate_linked_component_policy, validate_ota_headroom,
    validate_production_sdkconfig, write_core_metadata,
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
            Path('application.iotapp'), '1.9.0', [('component_versions.py', source)],
            signing_key=self.private_key, release_sequence=1900,
        )
        _descriptor, _bundle, published = publish_release(
            'application.iotapp', 'site', 'https://updates.example/iotmd',
            'stable', self.private_key, source_revision=self.revision,
        )
        self.assertIn(self.revision, published['notes'])
        with self.assertRaisesRegex(ValueError, 'does not match'):
            publish_release(
                'application.iotapp', 'other-site', 'https://updates.example/iotmd',
                'stable', self.private_key, source_revision='2' * 40,
            )

        damaged = bytearray(Path('application.iotapp').read_bytes())
        damaged[-1] ^= 1
        Path('damaged.iotapp').write_bytes(damaged)
        with self.assertRaisesRegex(ValueError, 'payload hash failed'):
            publish_release(
                'damaged.iotapp', 'damaged-site', 'https://updates.example/iotmd',
                'stable', self.private_key,
            )

    def test_core_metadata_provenance_is_covered_by_firmware_hash(self):
        metadata = write_core_metadata('generated', '1.9.0', 1900, self.revision)
        marker = source_marker(self.revision)
        self.assertIn(marker, metadata.read_bytes())
        image = Path('micropython.bin')
        image.write_bytes(b'\xe9' + metadata.read_bytes())
        build_firmware_bundle(
            image, Path('firmware.iotcore'), '1.9.0', signing_key=self.private_key,
            release_sequence=1900,
        )
        publish_release(
            'firmware.iotcore', 'firmware-site', 'https://updates.example/iotmd',
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

    def test_production_core_policy_accepts_size_optimised_minimal_config(self):
        validate_production_sdkconfig('\n'.join(REQUIRED_PRODUCTION_SDKCONFIG))

    def test_production_core_policy_rejects_unused_transports(self):
        config = '\n'.join(REQUIRED_PRODUCTION_SDKCONFIG + (
            'CONFIG_BT_ENABLED=y',
            'CONFIG_LWIP_PPP_SUPPORT=y',
            'CONFIG_ETH_USE_SPI_ETHERNET=y',
        ))
        with self.assertRaisesRegex(ValueError, 'CONFIG_BT_ENABLED=y'):
            validate_production_sdkconfig(config)

    def test_linker_policy_rejects_bluetooth_archives(self):
        lock = {'forbidden_linked_archives': ['libbt.a', 'libbtdm_app.a']}
        validate_linked_component_policy('libmain.a(runtime.c.obj)', lock)
        with self.assertRaisesRegex(ValueError, 'libbt.a'):
            validate_linked_component_policy(
                'esp-idf/bt/libbt.a(nimble.c.obj)', lock
            )

    def test_module_registration_cache_is_cleared_for_board_changes(self):
        build = Path('build')
        module_cache = build / 'genhdr' / 'module'
        module_cache.mkdir(parents=True)
        (module_cache / 'bluetooth.module').write_text('stale')
        for name in ('moduledefs.collected', 'moduledefs.h', 'moduledefs.split'):
            (build / 'genhdr' / name).write_text('stale')
        clear_module_registration_cache(build)
        self.assertFalse(module_cache.exists())
        self.assertFalse((build / 'genhdr' / 'moduledefs.h').exists())

    def test_secure_boot_helper_uses_esp_idf_55_command_name(self):
        command = generation_command('/idf', '/tmp/key.pem', 'python')
        self.assertIn('generate_signing_key', command)
        self.assertNotIn('generate-signing-key', command)


if __name__ == '__main__':
    unittest.main()
