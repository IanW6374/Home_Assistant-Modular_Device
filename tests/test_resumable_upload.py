import hashlib
import tempfile
import unittest
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
