#!/usr/bin/env python3
"""Assemble and validate a staged Nottinghamshire jobs CSV update.

Standard-library only. The manifest describes Base64 chunks containing the exact
CSV bytes that should be published. Validation is deliberately fail-closed.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import sys
from datetime import date, datetime, timedelta
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

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_TIME_RE = re.compile(r"^(\d{2}):(\d{2})$")
_CHUNK_RE = re.compile(r"^\.job-update/chunk-\d{3,}\.b64$")


class ValidationError(Exception):
    """Raised when a candidate update fails deterministic validation."""


def fail(message: str) -> None:
    raise ValidationError(message)


def parse_iso_date(value: str, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        fail(f"{field} must be YYYY-MM-DD: {value!r}")
    if parsed.isoformat() != value:
        fail(f"{field} must use canonical YYYY-MM-DD format: {value!r}")
    return parsed


def valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read manifest: {exc}")

    required = {"date_checked", "row_count", "sha256", "base_main_sha", "chunks"}
    missing = required - manifest.keys()
    if missing:
        fail(f"manifest missing required keys: {', '.join(sorted(missing))}")

    if not isinstance(manifest["date_checked"], str):
        fail("manifest date_checked must be a string")
    parse_iso_date(manifest["date_checked"], "manifest date_checked")

    if not isinstance(manifest["row_count"], int) or isinstance(manifest["row_count"], bool) or manifest["row_count"] < 0:
        fail("manifest row_count must be a non-negative integer")

    if not isinstance(manifest["sha256"], str) or not _SHA256_RE.fullmatch(manifest["sha256"]):
        fail("manifest sha256 must be a lowercase 64-character SHA-256")

    if not isinstance(manifest["base_main_sha"], str) or not _SHA1_RE.fullmatch(manifest["base_main_sha"]):
        fail("manifest base_main_sha must be a lowercase 40-character commit SHA")

    chunks = manifest["chunks"]
    if not isinstance(chunks, list) or not chunks or not all(isinstance(item, str) for item in chunks):
        fail("manifest chunks must be a non-empty list of paths")
    if len(chunks) != len(set(chunks)):
        fail("manifest chunks contains duplicate paths")
    for chunk in chunks:
        if not _CHUNK_RE.fullmatch(chunk):
            fail(f"invalid chunk path: {chunk!r}")

    return manifest


def assemble_chunks(root: Path, chunks: list[str]) -> bytes:
    encoded_parts: list[str] = []
    for relative in chunks:
        path = root / relative
        try:
            text = path.read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError) as exc:
            fail(f"cannot read chunk {relative!r}: {exc}")
        # Whitespace is formatting only; chunk content itself must remain Base64.
        encoded_parts.append("".join(text.split()))

    encoded = "".join(encoded_parts)
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        fail(f"staged chunks are not valid Base64: {exc}")


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
        fail(f"row {line}: date_checked must equal manifest date {update_date.isoformat()}")

    closing_date = parse_iso_date(record["closing_date"], f"row {line} closing_date")
    if closing_date < update_date or closing_date > update_date + timedelta(days=56):
        fail(f"row {line}: closing_date is outside the inclusive 56-day window")

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

    for key, group in fallback_groups.items():
        if len(group) < 2:
            continue
        urls = [url for _, url in group]
        # Identical title/location/deadline rows are allowed only when distinct
        # official advert URLs prove they are separate adverts.
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


def validate_candidate(csv_bytes: bytes, manifest: dict, require_today: bool = False) -> list[dict[str, str]]:
    digest = hashlib.sha256(csv_bytes).hexdigest()
    if digest != manifest["sha256"]:
        fail(f"SHA-256 mismatch: manifest={manifest['sha256']} actual={digest}")

    update_date = parse_iso_date(manifest["date_checked"], "manifest date_checked")
    if require_today:
        today = datetime.now(ZoneInfo("Europe/London")).date()
        if update_date != today:
            fail(f"manifest date_checked {update_date.isoformat()} is not today's Europe/London date {today.isoformat()}")

    records = parse_csv_bytes(csv_bytes)
    if len(records) != manifest["row_count"]:
        fail(f"row_count mismatch: manifest={manifest['row_count']} actual={len(records)}")

    for index, record in enumerate(records):
        validate_record(record, index, update_date, require_today)
    validate_duplicates(records)
    validate_sort(records)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."), help="Root containing manifest chunk paths")
    parser.add_argument("--output", type=Path, help="Write exact validated CSV bytes here")
    parser.add_argument("--actual-main-sha", help="Fail unless this equals manifest base_main_sha")
    parser.add_argument("--require-today", action="store_true", help="Require manifest date to equal current Europe/London date")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        if args.actual_main_sha is not None:
            if not _SHA1_RE.fullmatch(args.actual_main_sha):
                fail("--actual-main-sha must be a lowercase 40-character commit SHA")
            if manifest["base_main_sha"] != args.actual_main_sha:
                fail(
                    "main changed after publication preparation: "
                    f"manifest={manifest['base_main_sha']} current={args.actual_main_sha}"
                )

        csv_bytes = assemble_chunks(args.root, manifest["chunks"])
        records = validate_candidate(csv_bytes, manifest, require_today=args.require_today)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(csv_bytes)
        print(
            json.dumps(
                {
                    "ok": True,
                    "date_checked": manifest["date_checked"],
                    "row_count": len(records),
                    "sha256": manifest["sha256"],
                },
                sort_keys=True,
            )
        )
        return 0
    except ValidationError as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
