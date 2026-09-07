import base64
import csv
import hashlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.validate_job_update import EXPECTED_COLUMNS, ValidationError, load_manifest, validate_candidate


BASE_ROW = {
    "organization": "Example Council",
    "employer_type": "Council",
    "job_title": "Administrator",
    "job_area": "Administration & Business Support",
    "location": "Nottingham",
    "location_area": "Nottingham",
    "closing_date": "2026-09-10",
    "closing_time": "17:00",
    "contract_type": "Permanent",
    "work_pattern": "Full-time",
    "salary": "£25,000",
    "apply_url": "https://example.org/jobs/1",
    "job_reference": "REF-1",
    "date_checked": "2026-09-07",
    "source_url": "https://example.org/jobs/1",
}


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EXPECTED_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


def manifest_for(data, rows):
    return {
        "date_checked": "2026-09-07",
        "row_count": len(rows),
        "sha256": hashlib.sha256(data).hexdigest(),
        "base_main_sha": "a" * 40,
        "chunks": [".job-update/chunk-001.b64"],
    }


class CandidateValidationTests(unittest.TestCase):
    def test_valid_candidate(self):
        rows = [deepcopy(BASE_ROW)]
        data = csv_bytes(rows)
        records = validate_candidate(data, manifest_for(data, rows))
        self.assertEqual(1, len(records))

    def test_bad_checksum_fails(self):
        rows = [deepcopy(BASE_ROW)]
        data = csv_bytes(rows)
        manifest = manifest_for(data, rows)
        manifest["sha256"] = "0" * 64
        with self.assertRaises(ValidationError):
            validate_candidate(data, manifest)

    def test_out_of_window_fails(self):
        row = deepcopy(BASE_ROW)
        row["closing_date"] = "2026-11-03"
        data = csv_bytes([row])
        with self.assertRaises(ValidationError):
            validate_candidate(data, manifest_for(data, [row]))

    def test_wrong_sort_fails(self):
        first = deepcopy(BASE_ROW)
        first.update(job_reference="REF-2", job_title="Zulu", apply_url="https://example.org/jobs/2", source_url="https://example.org/jobs/2")
        second = deepcopy(BASE_ROW)
        second.update(job_reference="REF-1", job_title="Alpha")
        rows = [first, second]
        data = csv_bytes(rows)
        with self.assertRaises(ValidationError):
            validate_candidate(data, manifest_for(data, rows))

    def test_duplicate_reference_fails(self):
        first = deepcopy(BASE_ROW)
        second = deepcopy(BASE_ROW)
        second.update(job_title="Different title", apply_url="https://example.org/jobs/2", source_url="https://example.org/jobs/2")
        rows = [first, second]
        data = csv_bytes(rows)
        with self.assertRaises(ValidationError):
            validate_candidate(data, manifest_for(data, rows))

    def test_same_fallback_key_allowed_for_distinct_advert_urls(self):
        first = deepcopy(BASE_ROW)
        first.update(job_reference="", apply_url="https://example.org/jobs/a", source_url="https://example.org/jobs/a")
        second = deepcopy(first)
        second.update(apply_url="https://example.org/jobs/b", source_url="https://example.org/jobs/b")
        rows = [first, second]
        data = csv_bytes(rows)
        records = validate_candidate(data, manifest_for(data, rows))
        self.assertEqual(2, len(records))


class ManifestTests(unittest.TestCase):
    def test_manifest_and_chunk_path_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = csv_bytes([deepcopy(BASE_ROW)])
            manifest = manifest_for(payload, [BASE_ROW])
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            parsed = load_manifest(root / "manifest.json")
            self.assertEqual(manifest["sha256"], parsed["sha256"])

    def test_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = csv_bytes([deepcopy(BASE_ROW)])
            manifest = manifest_for(payload, [BASE_ROW])
            manifest["chunks"] = ["../secret.b64"]
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValidationError):
                load_manifest(root / "manifest.json")


if __name__ == "__main__":
    unittest.main()
