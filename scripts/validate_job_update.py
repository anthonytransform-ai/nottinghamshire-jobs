#!/usr/bin/env python3
"""Validate only the CSV conditions needed for safe website consumption.

The validator deliberately avoids enforcing weekly editorial or data-quality policy.
Those judgements belong to the Job Search Playbook and human/agent review, not to a
mechanical gate that can discard otherwise useful vacancies.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

LEGACY_COLUMNS = [
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
    "apply_url",
    "job_reference",
    "date_checked",
    "source_url",
]
SUMMARY_COLUMNS = [*LEGACY_COLUMNS, "job_summary"]
EXPECTED_COLUMNS = LEGACY_COLUMNS


class ValidationError(Exception):
    """Raised when a candidate feed cannot be consumed safely by the website."""


def fail(message: str) -> None:
    raise ValidationError(message)


def valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_csv_bytes(csv_bytes: bytes) -> tuple[list[dict[str, str]], list[str]]:
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        fail(f"CSV is not valid UTF-8: {exc}")

    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows = list(reader)
    except csv.Error as exc:
        fail(f"CSV is malformed: {exc}")

    if not rows:
        fail("CSV is empty")

    header = rows[0]
    if header == SUMMARY_COLUMNS:
        columns = SUMMARY_COLUMNS
    elif header == LEGACY_COLUMNS:
        columns = LEGACY_COLUMNS
    else:
        fail("CSV header does not match a supported 15- or 16-column contract")

    records: list[dict[str, str]] = []
    for line_number, row in enumerate(rows[1:], start=2):
        # The browser ignores completely blank rows, so the validator does too.
        if not any(value.strip() for value in row):
            continue
        if len(row) != len(columns):
            fail(f"CSV row {line_number} has {len(row)} fields; expected {len(columns)}")
        record = dict(zip(columns, row))
        if columns == LEGACY_COLUMNS:
            record["job_summary"] = ""
        records.append(record)
    return records, columns


def validate_record(record: dict[str, str], index: int) -> None:
    line = index + 2
    apply_url = record["apply_url"].strip()

    # A vacancy without a safe public destination cannot be rendered as an
    # actionable website row. Keep this narrow safety/functional gate only.
    if not apply_url:
        fail(f"row {line}: apply_url is blank")
    if not valid_http_url(apply_url):
        fail(f"row {line}: apply_url must be an HTTP(S) URL")


def validate_csv_bytes(csv_bytes: bytes) -> dict[str, object]:
    records, columns = parse_csv_bytes(csv_bytes)

    for index, record in enumerate(records):
        validate_record(record, index)

    return {
        "ok": True,
        "row_count": len(records),
        "column_count": len(columns),
        "schema": "summary-16" if columns == SUMMARY_COLUMNS else "legacy-15",
        "sha256": hashlib.sha256(csv_bytes).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Complete jobs.csv candidate to validate")
    args = parser.parse_args(argv)

    try:
        csv_bytes = args.csv_path.read_bytes()
        result = validate_csv_bytes(csv_bytes)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValidationError) as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
