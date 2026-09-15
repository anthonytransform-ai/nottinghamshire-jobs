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
        verified_associations = sum(1 for raw in result.raw_vacancies if raw.host_association_verified)
        distinct_advertisers = sorted({raw.advertised_employer_raw for raw in result.raw_vacancies if raw.advertised_employer_raw})
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
                "completeness_evidence": result.completeness_evidence,
                "retrieval_method": result.retrieval_method,
                "status": result.status.value,
                "warnings": result.warnings,
                "errors": result.errors,
                "exclusions": result.exclusions,
                "host_association_verified_count": verified_associations,
                "advertised_employer_count": len(distinct_advertisers),
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


def anomaly_warnings(
    results: list[SourceResult],
    *,
    candidate_row_count: int | None = None,
    history_path: Path | None = None,
) -> list[str]:
    warnings: list[str] = []
    previous: dict = {}
    if history_path and history_path.exists():
        try:
            previous = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
    previous_sources = previous.get("sources", {}) if isinstance(previous, dict) else {}
    for result in results:
        if result.status in {SourceStatus.PARTIALLY_VERIFIED, SourceStatus.BLOCKED}:
            warnings.append(f"{result.source_name}: {result.status.value}")
        if result.source_total is not None and result.captured_total < result.source_total:
            warnings.append(
                f"{result.source_name}: captured {result.captured_total} is below reported total {result.source_total}"
            )
        old = previous_sources.get(result.source_id, {}) if isinstance(previous_sources, dict) else {}
        old_count = old.get("captured_total") if isinstance(old, dict) else None
        if isinstance(old_count, int) and old_count >= 10 and result.captured_total <= max(2, old_count // 4):
            warnings.append(f"{result.source_name}: captured count fell from {old_count} to {result.captured_total}")
        old_status = old.get("status") if isinstance(old, dict) else None
        if old_status == SourceStatus.COMPLETE.value and result.status == SourceStatus.BLOCKED:
            warnings.append(f"{result.source_name}: previously Complete, now Blocked")
        old_host = old.get("hostname") if isinstance(old, dict) else None
        current_host = result.source_url.split("/", 3)[2] if "/" in result.source_url else ""
        if old_host and current_host and old_host != current_host:
            warnings.append(f"{result.source_name}: source hostname changed from {old_host} to {current_host}")
    if candidate_row_count == 0:
        warnings.append("candidate contains zero eligible rows; inspect every mandatory source audit before publication")
    old_rows = previous.get("candidate_row_count") if isinstance(previous, dict) else None
    if isinstance(old_rows, int) and old_rows >= 10 and candidate_row_count is not None and candidate_row_count <= max(2, old_rows // 4):
        warnings.append(f"overall eligible count fell from {old_rows} to {candidate_row_count}")
    return warnings


def write_history_snapshot(results: list[SourceResult], *, candidate_row_count: int, path: Path) -> None:
    """Persist warning-only evidence for the next run; never drives eligibility."""

    path.parent.mkdir(parents=True, exist_ok=True)
    sources = {}
    for result in results:
        host = result.source_url.split("/", 3)[2] if "/" in result.source_url else ""
        sources[result.source_id] = {
            "captured_total": result.captured_total,
            "source_total": result.source_total,
            "status": result.status.value,
            "hostname": host,
        }
    path.write_text(json.dumps({"candidate_row_count": candidate_row_count, "sources": sources}, indent=2) + "\n", encoding="utf-8")
