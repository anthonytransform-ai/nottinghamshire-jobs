"""Structured review queue persistence and safe resolution workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .configuration import ALLOWED_RESOLUTION_FIELDS, FORBIDDEN_RESOLUTION_FIELDS, resolution_key
from .models import ReviewItem


def write_review_queue(items: list[ReviewItem], path: Path) -> None:
    path.write_text(
        json.dumps([item.to_dict() for item in items], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_resolution_template(items: list[ReviewItem], path: Path) -> None:
    """Write an explicit, run-local TOML template for operator decisions."""

    lines = [
        "# Run-local reviewed decisions. Fill only the permitted fields below.",
        "# Never add closing_date, closing_time, live_status, reference or source_record_id.",
        "# A decision is applied on the next `py -m job_update build --date YYYY-MM-DD`.",
        "",
    ]
    for item in items:
        key = item.resolution_key or f"{item.source}::{item.source_record_id}"
        lines.extend(
            [
                "[[resolutions]]",
                f"key = {json.dumps(key, ensure_ascii=False)}",
                f"# source = {json.dumps(item.source, ensure_ascii=False)}",
                f"# title = {json.dumps(item.title, ensure_ascii=False)}",
                f"# reason = {json.dumps(item.reason, ensure_ascii=False)}",
                "# location_area = \"...\"",
                "# job_area = \"...\"",
                "# advertised_employer = \"...\"",
                "# host_organization = \"...\"",
                "# host_association_verified = true",
                "# host_association_type = \"direct|agency|subcontractor|subsidiary|shared-service\"",
                "# host_association_evidence = \"source evidence\"",
                "# policy = \"include|exclude\"",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_resolution(
    path: Path,
    *,
    key: str,
    field: str,
    value: Any,
) -> None:
    """Upsert one safe field while preserving existing run-local decisions."""

    if field in FORBIDDEN_RESOLUTION_FIELDS:
        raise ValueError(f"resolution field is not permitted: {field}")
    if field not in ALLOWED_RESOLUTION_FIELDS:
        raise ValueError(f"unknown resolution field: {field}")
    if not str(key).strip():
        raise ValueError("resolution key is required")
    existing: list[dict[str, Any]] = []
    if path.exists():
        import tomllib

        with path.open("rb") as stream:
            data = tomllib.load(stream)
        raw_entries = data.get("resolutions", [])
        if isinstance(raw_entries, list):
            existing = [dict(entry) for entry in raw_entries if isinstance(entry, dict)]
    entry = next((item for item in existing if item.get("key") == key), None)
    if entry is None:
        entry = {"key": key}
        existing.append(entry)
    entry[field] = value
    lines = [
        "# Run-local reviewed decisions. These fields never alter source dates, status or public references.",
        "",
    ]
    for item in existing:
        lines.append("[[resolutions]]")
        for item_key, item_value in item.items():
            if item_key in FORBIDDEN_RESOLUTION_FIELDS or item_key not in {"key", *ALLOWED_RESOLUTION_FIELDS}:
                continue
            if isinstance(item_value, bool):
                rendered = "true" if item_value else "false"
            elif isinstance(item_value, (int, float)):
                rendered = str(item_value)
            else:
                rendered = json.dumps(str(item_value), ensure_ascii=False)
            lines.append(f"{item_key} = {rendered}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def resolution_key_for_item(item: ReviewItem) -> str:
    return item.resolution_key or f"{item.source}::{item.source_record_id}"
