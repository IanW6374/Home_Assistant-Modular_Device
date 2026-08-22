import asyncio
import os
import tempfile
import unittest
from pathlib import Path

import firmware_update
import update_security
from tools.build_firmware_update import build_firmware_bundle
from tools.build_firmware_update import legacy_api4_manifest_message


class FakePartition:
    def __init__(self, label, size=16384):
        self.label = label
        self.data = bytearray(b'\xff' * size)
        self.boot_selected = False
        self.next_partition = None

    def info(self):
        return (0, 0, 0, len(self.data), self.label, False)

    def get_next_update(self):
        return self.next_partition

    def writeblocks(self, block, data):
        offset = block * firmware_update.BLOCK_SIZE
        self.data[offset:offset + len(data)] = data

    def readblocks(self, block, data):
        offset = block * firmware_update.BLOCK_SIZE
        data[:] = self.data[offset:offset + len(data)]

    def set_boot(self):
        self.boot_selected = True


class FakeEsp32:
    running = None
    marked_valid = False

    class Partition:
        RUNNING = 1

        def __new__(cls, identifier):
            return FakeEsp32.running

        @staticmethod
        def mark_app_valid_cancel_rollback():
            FakeEsp32.marked_valid = True


class Reader:
    def __init__(self, data):
        self.data = data

    async def read(self, size):
        chunk = self.data[:size]
        self.data = self.data[size:]
        return chunk


class FirmwareUpdateTests(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        self.original_esp32 = firmware_update.esp32
        self.original_supported = firmware_update.supported
        self.original_platform_id = firmware_update.hardware_platform.platform_id
        self.original_core_metadata = firmware_update.core_metadata
        self.running = FakePartition('ota_0')
        self.target = FakePartition('ota_1')
        self.running.next_partition = self.target
        FakeEsp32.running = self.running
        FakeEsp32.marked_valid = False
        firmware_update.esp32 = FakeEsp32
        firmware_update.supported = lambda: True
        firmware_update.hardware_platform.platform_id = lambda: 'esp32-s3'
        self.private_key = bytes(range(1, 33))
        Path(update_security.VERIFICATION_KEY_PATH).write_bytes(
            update_security.public_key_bytes(self.private_key)
        )

    def tearDown(self):
        firmware_update.esp32 = self.original_esp32
        firmware_update.supported = self.original_supported
        firmware_update.hardware_platform.platform_id = self.original_platform_id
        firmware_update.core_metadata = self.original_core_metadata
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def make_bundle(self, payload=None, version='mp-1.28.0', release_sequence=1):
        payload = payload or (b'\xe9' + bytes(range(256)) * 20)
        Path('micropython.app-bin').write_bytes(payload)
        build_firmware_bundle(
            'micropython.app-bin', 'firmware.hamf', version, 'esp32-s3',
            self.private_key, release_sequence=release_sequence
        )
        return payload, Path('firmware.hamf').read_bytes()

    def test_receive_activate_and_confirm_firmware(self):
        payload, bundle = self.make_bundle()
        progress = []

        state = asyncio.run(firmware_update.receive_bundle(
            Reader(bundle), len(bundle), progress_callback=lambda *value: progress.append(value)
        ))

        self.assertEqual(state['status'], 'ready')
        self.assertEqual(state['target'], 'ota_1')
        self.assertEqual(state['release_sequence'], 1)
        self.assertEqual(progress[0], ('writing', 0, len(payload)))
        writing = [value for value in progress if value[0] == 'writing']
        verification = [value for value in progress if value[0] == 'verification']
        self.assertEqual(writing[-1], ('writing', len(payload), len(payload)))
        self.assertEqual(verification[0], ('verification', 0, len(payload)))
        self.assertEqual(progress[-1], ('verification', len(payload), len(payload)))
        self.assertEqual(self.target.data[:len(payload)], payload)
        firmware_update.activate_pending()
        self.assertTrue(self.target.boot_selected)
        self.assertEqual(firmware_update.update_status()['status'], 'trial')

        FakeEsp32.running = self.target
        self.target.next_partition = self.running
        self.assertTrue(firmware_update.confirm_update())
        self.assertTrue(FakeEsp32.marked_valid)
        self.assertEqual(firmware_update.running_version(), 'mp-1.28.0')
        self.assertEqual(firmware_update.running_release_sequence(), 1)

    def test_frozen_core_package_identity_precedes_micropython_fallback(self):
        class Metadata:
            CORE_FIRMWARE_VERSION = '1.9.0-rc.1'
            RELEASE_SEQUENCE = 1930

        firmware_update.core_metadata = Metadata
        Path(firmware_update.VERSION_PATH).write_text('stale-filesystem-version')
        Path(firmware_update.RELEASE_SEQUENCE_PATH).write_text('1')

        self.assertEqual(
            firmware_update.running_version('1.28.0'),
            '1.9.0-rc.1'
        )
        self.assertEqual(firmware_update.running_release_sequence(), 1930)

    def test_legacy_firmware_bundle_format_is_not_built(self):
        payload = b'\xe9' + bytes(range(64))
        Path('micropython.app-bin').write_bytes(payload)
        with self.assertRaisesRegex(ValueError, 'format must be 6'):
            build_firmware_bundle(
                'micropython.app-bin', 'firmware.hamf', 'legacy',
                'esp32-s3', self.private_key, format_version=4
            )

    def test_rejects_remote_firmware_sequence_downgrade(self):
        _, bundle = self.make_bundle(version='new', release_sequence=10)
        asyncio.run(firmware_update.receive_bundle(Reader(bundle), len(bundle)))
        firmware_update.activate_pending()
        FakeEsp32.running = self.target
        self.target.next_partition = self.running
        firmware_update.confirm_update()

        _, older = self.make_bundle(version='older', release_sequence=9)
        with self.assertRaisesRegex(ValueError, 'not newer'):
            asyncio.run(firmware_update.receive_bundle(Reader(older), len(older)))

    def test_rejects_tampered_firmware_payload(self):
        _, bundle = self.make_bundle()
        tampered = bundle[:-1] + bytes([bundle[-1] ^ 0xff])

        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            asyncio.run(firmware_update.receive_bundle(Reader(tampered), len(tampered)))

    def test_accepts_same_version_with_newer_signed_sequence(self):
        _, bundle = self.make_bundle(release_sequence=2)
        Path(firmware_update.VERSION_PATH).write_text('mp-1.28.0')
        Path(firmware_update.RELEASE_SEQUENCE_PATH).write_text('1')

        state = asyncio.run(
            firmware_update.receive_bundle(Reader(bundle), len(bundle))
        )

        self.assertEqual(state['version'], 'mp-1.28.0')
        self.assertEqual(state['release_sequence'], 2)
        self.assertEqual(self.target.data[0], 0xe9)

    def test_detects_bootloader_rollback(self):
        _, bundle = self.make_bundle()
        asyncio.run(firmware_update.receive_bundle(Reader(bundle), len(bundle)))
        firmware_update.activate_pending()

        state = firmware_update.boot_status()

        self.assertEqual(state['status'], 'rolled_back')
        self.assertEqual(firmware_update.update_status()['status'], 'idle')

    def test_activation_recovers_when_staged_partition_is_already_running(self):
        _, bundle = self.make_bundle()
        asyncio.run(firmware_update.receive_bundle(Reader(bundle), len(bundle)))
        FakeEsp32.running = self.target
        self.target.next_partition = self.running

        state = firmware_update.activate_pending()

        self.assertEqual(state['status'], 'trial')
        self.assertTrue(self.target.boot_selected)
        self.assertTrue(firmware_update.confirm_update())
        self.assertTrue(FakeEsp32.marked_valid)
