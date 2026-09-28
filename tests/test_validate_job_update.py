import csv
import io
import unittest
from copy import deepcopy

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
    "job_summary": "Support the service by coordinating records and responding to routine enquiries.",
}


def csv_bytes(rows, columns=LEGACY_COLUMNS):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


class CandidateValidationTests(unittest.TestCase):
    def test_legacy_15_column_candidate_is_supported(self):
        result = validate_csv_bytes(csv_bytes([deepcopy(BASE_ROW)], LEGACY_COLUMNS))
        self.assertTrue(result["ok"])
        self.assertEqual("legacy-15", result["schema"])
        self.assertEqual(15, result["column_count"])

    def test_16_column_candidate_is_supported(self):
        result = validate_csv_bytes(csv_bytes([deepcopy(BASE_ROW)], SUMMARY_COLUMNS))
        self.assertTrue(result["ok"])
        self.assertEqual("summary-16", result["schema"])
        self.assertEqual(16, result["column_count"])
        self.assertEqual(1, result["row_count"])
        self.assertEqual(64, len(result["sha256"]))

    def test_blank_optional_values_are_allowed(self):
        row = deepcopy(BASE_ROW)
        for field in (
            "organization",
            "employer_type",
            "job_title",
            "job_area",
            "location",
            "location_area",
            "closing_date",
            "closing_time",
            "contract_type",
            "work_pattern",
            "salary",
            "job_reference",
            "date_checked",
            "source_url",
            "job_summary",
        ):
            row[field] = ""
        result = validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS))
        self.assertEqual(1, result["row_count"])

    def test_arbitrary_nonstructural_values_are_allowed(self):
        row = deepcopy(BASE_ROW)
        row.update(
            employer_type="Community employer",
            job_area="Specialist role",
            location_area="Near Nottingham",
            contract_type="Open-ended",
            work_pattern="Flexible",
            closing_date="Open until filled",
            closing_time="Whenever stated by employer",
            date_checked="",
        )
        result = validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS))
        self.assertEqual(1, result["row_count"])

    def test_past_closing_date_is_not_a_validator_rejection(self):
        row = deepcopy(BASE_ROW)
        row["closing_date"] = "2020-01-01"
        result = validate_csv_bytes(csv_bytes([row], LEGACY_COLUMNS))
        self.assertEqual(1, result["row_count"])

    def test_mixed_or_blank_date_checked_is_not_a_validator_rejection(self):
        first = deepcopy(BASE_ROW)
        second = deepcopy(BASE_ROW)
        second.update(
            job_reference="REF-2",
            job_title="Second role",
            apply_url="https://example.org/jobs/2",
            date_checked="",
        )
        result = validate_csv_bytes(csv_bytes([first, second], LEGACY_COLUMNS))
        self.assertEqual(2, result["row_count"])

    def test_duplicate_reference_is_not_a_validator_rejection(self):
        first = deepcopy(BASE_ROW)
        second = deepcopy(BASE_ROW)
        second.update(job_title="Different title", apply_url="https://example.org/jobs/2")
        result = validate_csv_bytes(csv_bytes([first, second], LEGACY_COLUMNS))
        self.assertEqual(2, result["row_count"])

    def test_unsorted_rows_are_not_a_validator_rejection(self):
        first = deepcopy(BASE_ROW)
        first.update(job_reference="REF-2", job_title="Zulu", apply_url="https://example.org/jobs/2")
        second = deepcopy(BASE_ROW)
        second.update(job_reference="REF-1", job_title="Alpha")
        result = validate_csv_bytes(csv_bytes([first, second], LEGACY_COLUMNS))
        self.assertEqual(2, result["row_count"])

    def test_summary_whitespace_and_line_breaks_are_not_validator_rejections(self):
        row = deepcopy(BASE_ROW)
        row["job_summary"] = "First sentence.  Second sentence.\nThird sentence.\tExtra detail."
        result = validate_csv_bytes(csv_bytes([row], SUMMARY_COLUMNS))
        self.assertEqual(1, result["row_count"])

    def test_blank_rows_are_ignored_like_the_browser_parser(self):
        data = csv_bytes([deepcopy(BASE_ROW)], SUMMARY_COLUMNS) + b"\r\n\r\n"
        result = validate_csv_bytes(data)
        self.assertEqual(1, result["row_count"])

    def test_zero_data_rows_are_allowed(self):
        legacy = validate_csv_bytes(csv_bytes([], LEGACY_COLUMNS))
        summary = validate_csv_bytes(csv_bytes([], SUMMARY_COLUMNS))
        self.assertEqual(0, legacy["row_count"])
        self.assertEqual(0, summary["row_count"])

    def test_malformed_row_field_count_fails(self):
        header = ",".join(SUMMARY_COLUMNS)
        malformed = f"{header}\r\nonly,three,fields\r\n".encode("utf-8")
        with self.assertRaises(ValidationError):
            validate_csv_bytes(malformed)

    def test_unsupported_schema_fails(self):
        wrong_columns = [*LEGACY_COLUMNS[:-1], "unexpected_column"]
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([deepcopy(BASE_ROW)], wrong_columns))

    def test_unterminated_quoted_field_fails(self):
        malformed = (",".join(LEGACY_COLUMNS) + "\r\n\"unterminated").encode("utf-8")
        with self.assertRaises(ValidationError):
            validate_csv_bytes(malformed)

    def test_blank_apply_url_fails(self):
        row = deepcopy(BASE_ROW)
        row["apply_url"] = ""
        with self.assertRaises(ValidationError):
            validate_csv_bytes(csv_bytes([row], LEGACY_COLUMNS))

    def test_unsafe_apply_url_scheme_fails(self):
        for value in ("javascript:alert(1)", "data:text/html,hello", "file:///tmp/job"):
            with self.subTest(value=value):
                row = deepcopy(BASE_ROW)
                row["apply_url"] = value
                with self.assertRaises(ValidationError):
                    validate_csv_bytes(csv_bytes([row], LEGACY_COLUMNS))

    def test_http_and_https_apply_urls_are_allowed(self):
        for value in ("http://example.org/jobs/1", "https://example.org/jobs/1"):
            with self.subTest(value=value):
                row = deepcopy(BASE_ROW)
                row["apply_url"] = value
                result = validate_csv_bytes(csv_bytes([row], LEGACY_COLUMNS))
                self.assertEqual(1, result["row_count"])


if __name__ == "__main__":
    unittest.main()
