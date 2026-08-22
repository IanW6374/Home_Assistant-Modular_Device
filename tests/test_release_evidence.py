import json
import tempfile
import unittest
from pathlib import Path

from tools.generate_sbom import build_sbom
from tools.generate_provenance import build_statement


class ReleaseEvidenceTests(unittest.TestCase):
    def test_sbom_has_deterministic_file_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.py').write_text('print("ok")\n')
            value = build_sbom(root, '2.0.0-alpha.1')
            self.assertEqual(value['bomFormat'], 'CycloneDX')
            self.assertEqual(value['components'][0]['name'], 'main.py')
            self.assertEqual(len(value['components'][0]['hashes'][0]['content']), 64)
            self.assertEqual(value['components'][-3]['name'], 'MicroPython')

    def test_provenance_binds_artifact_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'release.hamu'
            artifact.write_bytes(b'hamd')
            value = build_statement(
                Path(__file__).resolve().parents[1], [artifact], '2.0.0-alpha.1'
            )
            self.assertEqual(value['subject'][0]['name'], 'release.hamu')
            self.assertEqual(len(value['subject'][0]['digest']['sha256']), 64)


if __name__ == '__main__':
    unittest.main()
