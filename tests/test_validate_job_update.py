import csv
import io
import unittest
from copy import deepcopy

from scripts.validate_job_update import EXPECTED_COLUMNS, ValidationError, validate_csv_bytes


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
    return stream.getvalue().encode("utf-8")


class CandidateValidationTests(unittest.TestCase):
    def test_valid_candidate_reports_exact_metadata(self):
        rows = [deepcopy(BASE_ROW)]
        data = csv_bytes(rows)
        result = validate_csv_bytes(data, declared_date="2026-09-07")
        self.assertTrue(result["ok"])
        self.assertEqual("2026-09-07", result["date_checked"])
        self.assertEqual(1, result["row_count"])
        self.assertEqual(64, len(result["sha256"]))

    def test_declared_date_mismatch_fails(self):
        data = csv_bytes([deepcopy(BASE_ROW)])
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data, declared_date="2026-09-08")

    def test_mixed_date_checked_fails(self):
        first = deepcopy(BASE_ROW)
        second = deepcopy(BASE_ROW)
        second.update(job_reference="REF-2", job_title="Zulu", date_checked="2026-09-08")
        data = csv_bytes([first, second])
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data)

    def test_far_future_fixed_deadline_is_allowed(self):
        row = deepcopy(BASE_ROW)
        row["closing_date"] = "2027-01-31"
        data = csv_bytes([row])
        self.assertTrue(validate_csv_bytes(data)["ok"])

    def test_wrong_sort_fails(self):
        first = deepcopy(BASE_ROW)
        first.update(job_reference="REF-2", job_title="Zulu", apply_url="https://example.org/jobs/2", source_url="https://example.org/jobs/2")
        second = deepcopy(BASE_ROW)
        second.update(job_reference="REF-1", job_title="Alpha")
        data = csv_bytes([first, second])
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data)

    def test_duplicate_reference_fails(self):
        first = deepcopy(BASE_ROW)
        second = deepcopy(BASE_ROW)
        second.update(job_title="Different title", apply_url="https://example.org/jobs/2", source_url="https://example.org/jobs/2")
        data = csv_bytes([first, second])
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data)

    def test_same_fallback_key_fails_even_for_distinct_advert_urls(self):
        first = deepcopy(BASE_ROW)
        first.update(job_reference="", apply_url="https://example.org/jobs/a", source_url="https://example.org/jobs/a")
        second = deepcopy(first)
        second.update(apply_url="https://example.org/jobs/b", source_url="https://example.org/jobs/b")
        data = csv_bytes([first, second])
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data)

    def test_zero_rows_allowed_with_declared_date(self):
        data = csv_bytes([])
        result = validate_csv_bytes(data, declared_date="2026-09-07")
        self.assertEqual(0, result["row_count"])
        self.assertEqual("2026-09-07", result["date_checked"])


if __name__ == "__main__":
    unittest.main()
