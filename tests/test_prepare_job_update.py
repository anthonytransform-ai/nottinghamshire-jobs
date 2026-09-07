import subprocess
import sys
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


class PreparationCliTests(unittest.TestCase):
    def test_direct_script_invocation_works(self):
        data = csv_bytes([BASE_ROW])
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "jobs.csv"
            source.write_bytes(data)
            output = root / "stage"
            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "prepare_job_update.py"),
                    str(source),
                    "--output-dir",
                    str(output),
                    "--date-checked",
                    "2026-09-07",
                    "--base-main-sha",
                    "a" * 40,
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
            self.assertTrue((output / "job-update-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
