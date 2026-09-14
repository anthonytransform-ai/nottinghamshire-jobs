"""Source audit ledger and anomaly summary writers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import SourceResult, SourceStatus


def audit_rows(results: Iterable[SourceResult], *, mandatory_only: bool = False) -> list[dict]:
    rows = []
    for result in results:
        if mandatory_only and not result.mandatory:
            continue
        rows.append(
            {
                "source": result.source_name,
                "source_id": result.source_id,
                "source_url": result.source_url,
                "source_total": result.source_total,
                "reported_totals": result.reported_totals,
                "captured_total": result.captured_total,
                "eligible_count": result.eligible_hint_count,
                "verification_method": result.verification_method,
                "retrieval_method": result.retrieval_method,
                "status": result.status.value,
                "warnings": result.warnings,
                "errors": result.errors,
                "exclusions": result.exclusions,
                "checked_at": result.checked_at,
            }
        )
    return rows


def write_source_audit(results: list[SourceResult], json_path: Path, markdown_path: Path) -> None:
    rows = audit_rows(results)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Nottinghamshire Jobs source audit",
        "",
        "| Source | Total | Captured | Eligible | Method | Status | Warnings |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        total = "—" if row["source_total"] is None else str(row["source_total"])
        warning = "; ".join(row["warnings"] + row["errors"]).replace("|", "/")
        lines.append(
            f"| {row['source']} | {total} | {row['captured_total']} | {row['eligible_count']} | {row['verification_method'] or row['retrieval_method']} | {row['status']} | {warning} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def anomaly_warnings(results: list[SourceResult], *, candidate_row_count: int | None = None) -> list[str]:
    warnings: list[str] = []
    for result in results:
        if result.status in {SourceStatus.PARTIALLY_VERIFIED, SourceStatus.BLOCKED}:
            warnings.append(f"{result.source_name}: {result.status.value}")
        if result.source_total is not None and result.captured_total < result.source_total:
            warnings.append(
                f"{result.source_name}: captured {result.captured_total} is below reported total {result.source_total}"
            )
    if candidate_row_count == 0:
        warnings.append("candidate contains zero eligible rows; inspect every mandatory source audit before publication")
    return warnings
