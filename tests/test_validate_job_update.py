import csv
import io
import unittest
from copy import deepcopy
from datetime import datetime as DateTime
from unittest.mock import patch

from scripts.validate_job_update import (
    LEGACY_COLUMNS,
    SUMMARY_COLUMNS,
    ValidationError,
    validate_csv_bytes,
)


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
    "job_summary": "Support the service by coordinating records, responding to routine enquiries and keeping day-to-day administration accurate and up to date.",
}


def csv_bytes(rows, columns=LEGACY_COLUMNS):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


class CandidateValidationTests(unittest.TestCase):
    def test_legacy_15_column_candidate_remains_valid_during_migration(self):
        data = csv_bytes([deepcopy(BASE_ROW)], LEGACY_COLUMNS)
        result = validate_csv_bytes(data, declared_date="2026-09-07")
        self.assertTrue(result["ok"])
        self.assertEqual("legacy-15", result["schema"])
        self.assertEqual(15, result["column_count"])

    def test_legacy_candidate_fails_when_summary_column_is_explicitly_required(self):
        data = csv_bytes([deepcopy(BASE_ROW)], LEGACY_COLUMNS)
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data, require_summary_column=True)

    def test_valid_16_column_candidate_reports_summary_schema(self):
        data = csv_bytes([deepcopy(BASE_ROW)], SUMMARY_COLUMNS)
        result = validate_csv_bytes(data, declared_date="2026-09-07", require_summary_column=True)
        self.assertTrue(result["ok"])
        self.assertEqual("summary-16", result["schema"])
        self.assertEqual(16, result["column_count"])
        self.assertEqual(1, result["row_count"])
        self.assertEqual(64, len(result["sha256"]))

    def test_blank_summary_is_valid_in_16_column_candidate(self):
        row = deepcopy(BASE_ROW)
        row["job_summary"] = ""
        result = validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS), require_summary_column=True)
        self.assertEqual(1, result["row_count"])

    def test_summary_with_commas_and_quotes_is_valid_csv(self):
        row = deepcopy(BASE_ROW)
        row["job_summary"] = 'Support the team with calls, records and the service\'s "first response" process.'
        result = validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS), require_summary_column=True)
        self.assertEqual("summary-16", result["schema"])

    def test_summary_with_line_break_fails(self):
        row = deepcopy(BASE_ROW)
        row["job_summary"] = "First sentence.\nSecond sentence."
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS), require_summary_column=True)

    def test_summary_with_tab_fails(self):
        row = deepcopy(BASE_ROW)
        row["job_summary"] = "First sentence.\tSecond sentence."
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS), require_summary_column=True)

    def test_summary_with_noncanonical_whitespace_fails(self):
        row = deepcopy(BASE_ROW)
        row["job_summary"] = "First sentence.  Second sentence."
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS), require_summary_column=True)

    def test_malformed_row_field_count_fails(self):
        header = ",".join(SUMMARY_COLUMNS)
        malformed = f"{header}\r\nonly,three,fields\r\n".encode("utf-8")
        with self.assertRaises(ValidationError):
            validate_csv_bytes(malformed, require_summary_column=True)

    def test_declared_date_mismatch_fails(self):
        data = csv_bytes([deepcopy(BASE_ROW)], LEGACY_COLUMNS)
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data, declared_date="2026-09-08")

    def test_mixed_date_checked_fails(self):
        first = deepcopy(BASE_ROW)
        second = deepcopy(BASE_ROW)
        second.update(job_reference="REF-2", job_title="Zulu", date_checked="2026-09-08")
        data = csv_bytes([first, second], LEGACY_COLUMNS)
        with self.assertRaises(ValidationError):
            validate_csv_bytes(data)

    def test_far_future_closing_date_is_allowed(self):
        row = deepcopy(BASE_ROW)
        row["closing_date"] = "2026-11-03"
        result = validate_csv_bytes(csv_bytes([row], LEGACY_COLUMNS))
        self.assertEqual(1, result["row_count"])

    def test_closing_date_before_update_date_fails(self):
        row = deepcopy(BASE_ROW)
        row["closing_date"] = "2026-09-06"
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([row], LEGACY_COLUMNS))

    def test_same_day_closing_time_is_checked(self):
        row = deepcopy(BASE_ROW)
        row["closing_date"] = "2026-09-07"
        row["closing_time"] = "17:00"
        data = csv_bytes([row], LEGACY_COLUMNS)
        with patch("scripts.validate_job_update.datetime") as clock:
            clock.now.return_value = DateTime(2026, 9, 7, 17, 0)
            with self.assertRaises(ValidationError):
                validate_csv_bytes(data, declared_date="2026-09-07", require_today=True)

    def test_wrong_sort_fails(self):
        first = deepcopy(BASE_ROW)
        first.update(job_reference="REF-2", job_title="Zulu", apply_url="https://example.org/jobs/2", source_url="https://example.org/jobs/2")
        second = deepcopy(BASE_ROW)
        second.update(job_reference="REF-1", job_title="Alpha")
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([first, second], LEGACY_COLUMNS))

    def test_duplicate_reference_fails(self):
        first = deepcopy(BASE_ROW)
        second = deepcopy(BASE_ROW)
        second.update(job_title="Different title", apply_url="https://example.org/jobs/2", source_url="https://example.org/jobs/2")
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([first, second], LEGACY_COLUMNS))

    def test_same_fallback_key_allowed_for_distinct_advert_urls(self):
        first = deepcopy(BASE_ROW)
        first.update(job_reference="", apply_url="https://example.org/jobs/a", source_url="https://example.org/jobs/a")
        second = deepcopy(first)
        second.update(apply_url="https://example.org/jobs/b", source_url="https://example.org/jobs/b")
        result = validate_csv_bytes(csv_bytes([first, second], LEGACY_COLUMNS))
        self.assertEqual(2, result["row_count"])

    def test_different_jobs_may_share_one_recruitment_page(self):
        first = deepcopy(BASE_ROW)
        first.update(
            job_reference="",
            job_title="Administrator",
            apply_url="https://example.org/vacancies",
            source_url="https://example.org/vacancies",
        )
        second = deepcopy(first)
        second.update(job_title="Planner")
        result = validate_csv_bytes(csv_bytes([first, second], LEGACY_COLUMNS))
        self.assertEqual(2, result["row_count"])

    def test_zero_rows_allowed_with_declared_date_for_both_contracts(self):
        legacy = validate_csv_bytes(csv_bytes([], LEGACY_COLUMNS), declared_date="2026-09-07")
        summary = validate_csv_bytes(
            csv_bytes([], SUMMARY_COLUMNS),
            declared_date="2026-09-07",
            require_summary_column=True,
        )
        self.assertEqual(0, legacy["row_count"])
        self.assertEqual("legacy-15", legacy["schema"])
        self.assertEqual(0, summary["row_count"])
        self.assertEqual("summary-16", summary["schema"])


if __name__ == "__main__":
    unittest.main()
