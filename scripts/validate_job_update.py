#!/usr/bin/env python3
"""Validate a complete Nottinghamshire jobs CSV candidate.

Standard-library only. The validator reads the exact candidate `jobs.csv` bytes,
checks the public data contract, and reports the update date, row count and
SHA-256. It does not publish, reconstruct, or transform the candidate file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

EXPECTED_COLUMNS = [
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

EMPLOYER_TYPES = {"Council", "NHS", "VCSE", "Education"}
JOB_AREAS = {
    "Administration & Business Support",
    "Care & Support",
    "Children & Young People",
    "Community & Outreach",
    "Customer Service",
    "Education & Training",
    "Finance & Procurement",
    "Health & Clinical",
    "HR & People",
    "Housing & Homelessness",
    "IT & Digital",
    "Legal & Governance",
    "Management & Leadership",
    "Planning, Environment & Regulatory",
    "Property, Facilities & Operations",
    "Transport & Driving",
    "Leisure, Sport & Culture",
    "Other",
}
LOCATION_AREAS = {
    "Nottingham",
    "Broxtowe",
    "Ashfield",
    "Bassetlaw",
    "Gedling",
    "Mansfield",
    "Newark & Sherwood",
    "Rushcliffe",
    "Nottinghamshire-wide",
    "Multiple Nottinghamshire locations",
}
CONTRACT_TYPES = {
    "Permanent",
    "Fixed-term",
    "Temporary",
    "Apprenticeship",
    "Bank/Casual/Sessional",
    "Freelance",
    "Other",
}
WORK_PATTERNS = {
    "Full-time",
    "Part-time",
    "Full-time or Part-time",
    "Variable/Sessional",
    "Not stated",
}

_TIME_RE = re.compile(r"^(\d{2}):(\d{2})$")


class ValidationError(Exception):
    """Raised when a candidate update fails deterministic validation."""


def fail(message: str) -> None:
    raise ValidationError(message)


def parse_iso_date(value: str, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        fail(f"{field} must be YYYY-MM-DD: {value!r}")
    if parsed.isoformat() != value:
        fail(f"{field} must use canonical YYYY-MM-DD format: {value!r}")
    return parsed


def valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def parse_csv_bytes(csv_bytes: bytes) -> list[dict[str, str]]:
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        fail(f"CSV is not valid UTF-8: {exc}")

    reader = csv.reader(io.StringIO(text, newline=""))
    rows = list(reader)
    if not rows:
        fail("CSV is empty")

    if rows[0] != EXPECTED_COLUMNS:
        fail("CSV header does not match the exact 15-column contract")

    records: list[dict[str, str]] = []
    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(EXPECTED_COLUMNS):
            fail(f"CSV row {line_number} has {len(row)} fields; expected {len(EXPECTED_COLUMNS)}")
        records.append(dict(zip(EXPECTED_COLUMNS, row)))
    return records


def resolve_update_date(records: list[dict[str, str]], declared_date: str | None, require_today: bool) -> date:
    today = datetime.now(ZoneInfo("Europe/London")).date()

    if records:
        values = {record["date_checked"] for record in records}
        if "" in values:
            fail("date_checked must not be blank")
        if len(values) != 1:
            fail("all rows must use the same date_checked")
        value = next(iter(values))
        update_date = parse_iso_date(value, "date_checked")
        if declared_date is not None and value != declared_date:
            fail(f"date_checked {value} does not match declared date {declared_date}")
    else:
        if declared_date is not None:
            update_date = parse_iso_date(declared_date, "declared date")
        elif require_today:
            update_date = today
        else:
            fail("a zero-row CSV requires --date-checked unless --require-today is used")

    if require_today and update_date != today:
        fail(
            f"date_checked {update_date.isoformat()} is not today's Europe/London date {today.isoformat()}"
        )
    return update_date


def validate_record(record: dict[str, str], index: int, update_date: date, require_today: bool) -> None:
    line = index + 2
    required_fields = ["organization", "job_title", "location_area", "closing_date", "apply_url", "source_url"]
    for field in required_fields:
        if not record[field].strip():
            fail(f"row {line}: required field {field} is blank")

    if record["employer_type"] not in EMPLOYER_TYPES:
        fail(f"row {line}: invalid employer_type {record['employer_type']!r}")
    if record["job_area"] not in JOB_AREAS:
        fail(f"row {line}: invalid job_area {record['job_area']!r}")
    if record["location_area"] not in LOCATION_AREAS:
        fail(f"row {line}: invalid location_area {record['location_area']!r}")
    if record["contract_type"] not in CONTRACT_TYPES:
        fail(f"row {line}: invalid contract_type {record['contract_type']!r}")
    if record["work_pattern"] not in WORK_PATTERNS:
        fail(f"row {line}: invalid work_pattern {record['work_pattern']!r}")

    if record["date_checked"] != update_date.isoformat():
        fail(f"row {line}: date_checked must equal update date {update_date.isoformat()}")

    closing_date = parse_iso_date(record["closing_date"], f"row {line} closing_date")
    if closing_date < update_date:
        fail(f"row {line}: closing_date must be on or after the update date")

    closing_time = record["closing_time"]
    if closing_time:
        match = _TIME_RE.fullmatch(closing_time)
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            fail(f"row {line}: closing_time must be blank or HH:MM")
        if require_today and closing_date == update_date:
            now = datetime.now(ZoneInfo("Europe/London"))
            deadline_minutes = int(match.group(1)) * 60 + int(match.group(2))
            if now.date() == update_date and now.hour * 60 + now.minute >= deadline_minutes:
                fail(f"row {line}: stated same-day closing time has already passed in Europe/London")

    for field in ("apply_url", "source_url"):
        if not valid_http_url(record[field].strip()):
            fail(f"row {line}: {field} must be an HTTP(S) URL")


def validate_duplicates(records: list[dict[str, str]]) -> None:
    reference_keys: dict[tuple[str, str], int] = {}
    fallback_groups: dict[tuple[str, str, str, str], list[tuple[int, str]]] = {}

    for index, record in enumerate(records):
        line = index + 2
        reference = normalise(record["job_reference"])
        if reference:
            key = (normalise(record["organization"]), reference)
            if key in reference_keys:
                fail(f"rows {reference_keys[key]} and {line}: duplicate employer + job_reference")
            reference_keys[key] = line
            continue

        key = (
            normalise(record["organization"]),
            normalise(record["job_title"]),
            normalise(record["location"]),
            record["closing_date"],
        )
        fallback_groups.setdefault(key, []).append((line, record["apply_url"].strip()))

    for group in fallback_groups.values():
        if len(group) < 2:
            continue
        urls = [url for _, url in group]
        if any(not url for url in urls) or len(set(urls)) != len(urls):
            lines = ", ".join(str(line) for line, _ in group)
            fail(f"rows {lines}: unresolved duplicate employer/title/location/closing_date")


def validate_sort(records: list[dict[str, str]]) -> None:
    def key(record: dict[str, str]) -> tuple[str, str, str]:
        return (
            normalise(record["organization"]),
            record["closing_date"],
            normalise(record["job_title"]),
        )

    sorted_records = sorted(records, key=key)
    if [key(record) for record in records] != [key(record) for record in sorted_records]:
        fail("CSV is not sorted by organization A-Z, closing_date earliest first, then job_title A-Z")


def validate_csv_bytes(
    csv_bytes: bytes,
    *,
    declared_date: str | None = None,
    require_today: bool = False,
) -> dict[str, object]:
    records = parse_csv_bytes(csv_bytes)
    update_date = resolve_update_date(records, declared_date, require_today)

    for index, record in enumerate(records):
        validate_record(record, index, update_date, require_today)
    validate_duplicates(records)
    validate_sort(records)

    return {
        "ok": True,
        "date_checked": update_date.isoformat(),
        "row_count": len(records),
        "sha256": hashlib.sha256(csv_bytes).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Complete jobs.csv candidate to validate")
    parser.add_argument("--date-checked", help="Optional declared YYYY-MM-DD update date")
    parser.add_argument(
        "--require-today",
        action="store_true",
        help="Require the update date to equal today's Europe/London date and reject passed same-day stated deadlines",
    )
    args = parser.parse_args(argv)

    try:
        csv_bytes = args.csv_path.read_bytes()
        result = validate_csv_bytes(
            csv_bytes,
            declared_date=args.date_checked,
            require_today=args.require_today,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValidationError) as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
