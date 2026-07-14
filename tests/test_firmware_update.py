import asyncio
import os
import tempfile
import unittest
from pathlib import Path

import firmware_update
from tools.build_firmware_update import build_firmware_bundle


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
        self.running = FakePartition('ota_0')
        self.target = FakePartition('ota_1')
        self.running.next_partition = self.target
        FakeEsp32.running = self.running
        FakeEsp32.marked_valid = False
        firmware_update.esp32 = FakeEsp32
        firmware_update.supported = lambda: True
        firmware_update.hardware_platform.platform_id = lambda: 'esp32-s3'

    def tearDown(self):
        firmware_update.esp32 = self.original_esp32
        firmware_update.supported = self.original_supported
        firmware_update.hardware_platform.platform_id = self.original_platform_id
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def make_bundle(self, payload=None):
        payload = payload or (b'\xe9' + bytes(range(256)) * 20)
        Path('micropython.app-bin').write_bytes(payload)
        build_firmware_bundle(
            'firmware.hamf', 'micropython.app-bin', 'mp-1.28.0', 'esp32-s3'
        )
        return payload, Path('firmware.hamf').read_bytes()

    def test_receive_activate_and_confirm_firmware(self):
        payload, bundle = self.make_bundle()

        state = asyncio.run(firmware_update.receive_bundle(Reader(bundle), len(bundle)))

        self.assertEqual(state['status'], 'ready')
        self.assertEqual(state['target'], 'ota_1')
        self.assertEqual(self.target.data[:len(payload)], payload)
        firmware_update.activate_pending()
        self.assertTrue(self.target.boot_selected)
        self.assertEqual(firmware_update.update_status()['status'], 'trial')

        FakeEsp32.running = self.target
        self.target.next_partition = self.running
        self.assertTrue(firmware_update.confirm_update())
        self.assertTrue(FakeEsp32.marked_valid)
        self.assertEqual(firmware_update.running_version(), 'mp-1.28.0')

    def test_rejects_tampered_firmware_payload(self):
        _, bundle = self.make_bundle()
        tampered = bundle[:-1] + bytes([bundle[-1] ^ 0xff])

        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            asyncio.run(firmware_update.receive_bundle(Reader(tampered), len(tampered)))

    def test_detects_bootloader_rollback(self):
        _, bundle = self.make_bundle()
        asyncio.run(firmware_update.receive_bundle(Reader(bundle), len(bundle)))
        firmware_update.activate_pending()

        state = firmware_update.boot_status()

        self.assertEqual(state['status'], 'rolled_back')
        self.assertEqual(firmware_update.update_status()['status'], 'idle')

