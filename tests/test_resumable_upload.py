import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import resumable_upload
from resumable_upload import ResumableUploadStore


class ResumableUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ResumableUploadStore(
            self.temp.name, maximum_bytes=1024, maximum_sessions=2
        )
        self.payload = b'complete signed update payload'
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_resumes_at_exact_offset_and_verifies_complete_payload(self):
        self.store.begin('session-1234', 'universal', len(self.payload), self.digest)
        first = self.payload[:10]
        self.store.append('session-1234', 0, first)

        restored = ResumableUploadStore(self.temp.name, maximum_bytes=1024)
        self.assertEqual(restored.status('session-1234')['received_bytes'], 10)
        restored.append('session-1234', 10, self.payload[10:])
        complete = restored.complete('session-1234')
        self.assertTrue(complete['complete'])
        self.assertEqual(complete['percent'], 100)

    def test_rejects_wrong_offset_digest_and_oversize(self):
        self.store.begin('session-1234', 'application', len(self.payload), '0' * 64)
        with self.assertRaisesRegex(ValueError, 'offset'):
            self.store.append('session-1234', 1, self.payload)
        self.store.append('session-1234', 0, self.payload)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.store.complete('session-1234')
        with self.assertRaisesRegex(ValueError, 'size'):
            self.store.begin('session-5678', 'firmware', 2048, self.digest)

    def test_uncommitted_tail_is_discarded_after_interrupted_chunk(self):
        self.store.begin('session-power-loss', 'application', len(self.payload), self.digest)
        self.store.append('session-power-loss', 0, self.payload[:10])
        part = Path(self.temp.name) / 'session-power-loss.part'
        with part.open('ab') as stream:
            stream.write(b'uncommitted-tail')

        restored = ResumableUploadStore(self.temp.name, maximum_bytes=1024)
        self.assertEqual(restored.status('session-power-loss')['received_bytes'], 10)
        self.assertEqual(part.stat().st_size, 10)
        restored.append('session-power-loss', 10, self.payload[10:])
        self.assertTrue(restored.complete('session-power-loss')['complete'])

    def test_verification_uses_micropython_digest_api_without_hexdigest(self):
        native_sha256 = hashlib.sha256

        class MicroPythonSHA256:
            def __init__(self):
                self._digest = native_sha256()

            def update(self, payload):
                self._digest.update(payload)

            def digest(self):
                return self._digest.digest()

        self.store.begin('session-micropython', 'application', len(self.payload), self.digest)
        self.store.append('session-micropython', 0, self.payload)
        with mock.patch.object(
            resumable_upload.hashlib, 'sha256', MicroPythonSHA256
        ):
            complete = self.store.complete('session-micropython')

        self.assertTrue(complete['complete'])

    def test_selecting_different_artifact_reclaims_incomplete_session(self):
        self.store.begin('session-first', 'firmware', 20, '1' * 64)
        self.store.append('session-first', 0, b'partial')

        second = self.store.begin(
            'session-second', 'application', len(self.payload), self.digest
        )

        self.assertEqual(second['received_bytes'], 0)
        self.assertFalse((Path(self.temp.name) / 'session-first.json').exists())
        self.assertFalse((Path(self.temp.name) / 'session-first.part').exists())

    def test_begin_rejects_before_writing_when_storage_is_too_small(self):
        values = (4096, 4096, 10, 1, 1, 0, 0, 0, 255)
        store = ResumableUploadStore(
            self.temp.name, maximum_bytes=8192, storage_reserve_bytes=1024
        )
        with mock.patch.object(resumable_upload.os, 'statvfs', return_value=values):
            with self.assertRaisesRegex(ValueError, 'insufficient storage'):
                store.begin('session-storage', 'firmware', 4096, self.digest)
        self.assertFalse((Path(self.temp.name) / 'session-storage.part').exists())

    def test_resuming_same_artifact_preserves_committed_bytes(self):
        self.store.begin('session-resume', 'application', len(self.payload), self.digest)
        self.store.append('session-resume', 0, self.payload[:8])

        resumed = self.store.begin(
            'session-resume', 'application', len(self.payload), self.digest
        )

        self.assertEqual(resumed['received_bytes'], 8)

    def test_unfinishable_resume_is_reclaimed_and_restarted(self):
        store = ResumableUploadStore(
            self.temp.name, maximum_bytes=1024, storage_reserve_bytes=0
        )
        store.begin('session-restart', 'application', len(self.payload), self.digest)
        store.append('session-restart', 0, self.payload[:8])
        low_space = (4096, 4096, 10, 0, 0, 0, 0, 0, 255)
        recovered_space = (4096, 4096, 10, 10, 10, 0, 0, 0, 255)

        with mock.patch.object(
            resumable_upload.os, 'statvfs',
            side_effect=(low_space, recovered_space)
        ):
            restarted = store.begin(
                'session-restart', 'application', len(self.payload), self.digest
            )

        self.assertEqual(restarted['received_bytes'], 0)
        self.assertEqual(
            (Path(self.temp.name) / 'session-restart.part').stat().st_size, 0
        )


if __name__ == '__main__':
    unittest.main()
