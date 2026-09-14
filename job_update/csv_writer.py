"""Exact website CSV generation."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .models import NormalizedVacancy


CSV_COLUMNS = [
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


def sort_key(record: NormalizedVacancy) -> tuple[str, str, str, str, str]:
    return (
        " ".join(record.organization.casefold().split()),
        record.closing_date,
        " ".join(record.job_title.casefold().split()),
        record.location.casefold(),
        record.job_reference.casefold(),
    )


def csv_bytes(records: list[NormalizedVacancy]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for record in sorted(records, key=sort_key):
        writer.writerow(record.to_csv_row())
    return stream.getvalue().encode("utf-8")


def write_csv(records: list[NormalizedVacancy], path: Path) -> bytes:
    data = csv_bytes(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data
