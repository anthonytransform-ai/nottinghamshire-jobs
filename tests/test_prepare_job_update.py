import tempfile
import unittest
from pathlib import Path

from scripts.prepare_job_update import prepare
from scripts.validate_job_update import assemble_chunks, load_manifest, validate_candidate
from test_validate_job_update import BASE_ROW, csv_bytes


class PreparationTests(unittest.TestCase):
    def test_preparation_round_trip_preserves_exact_bytes(self):
        data = csv_bytes([BASE_ROW])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "jobs.csv"
            source.write_bytes(data)
            stage = root / "stage"
            manifest = prepare(source, stage, "2026-09-07", "a" * 40, 12000)
            loaded = load_manifest(stage / "job-update-manifest.json")
            rebuilt = assemble_chunks(stage, loaded["chunks"])
            self.assertEqual(data, rebuilt)
            self.assertEqual(manifest["sha256"], loaded["sha256"])
            self.assertEqual(1, len(validate_candidate(rebuilt, loaded)))


if __name__ == "__main__":
    unittest.main()
