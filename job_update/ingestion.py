"""Validated boundary between Codex source research and deterministic build.

The accepted document is a JSON object with schema_version, date_checked and a
sources array. Each source entry carries source_id, status, retrieval_method,
verification_method, completeness_evidence, source_total, captured_total,
source_url, checked_at, warnings, errors, reported_totals and records. Every
mandatory registry source must be present, including a verified zero-result
source. A record preserves
source identity separately from the public reference and must include the
factual, host-association, deadline, URL and controlled semantic fields used
by the deterministic build.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .classify import JOB_AREAS, LOCATION_AREAS
from .models import RawVacancy, SourceResult, SourceSpec, SourceStatus
from .timezone import london_now


INGESTION_SCHEMA_VERSION = 1
HOST_ASSOCIATION_TYPES = {
    "",
    "direct",
    "agency",
    "subcontractor",
    "subsidiary",
    "shared-service",
}


class IngestionError(ValueError):
    """Raised when a Codex-produced source evidence document is unsafe."""


def _require_string(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise IngestionError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise IngestionError(f"{field} must not be empty")
    return value.strip()


def _require_url(value: Any, field: str, *, allow_empty: bool = False) -> str:
    url = _require_string(value, field, allow_empty=allow_empty)
    if url and urlparse(url).scheme not in {"http", "https"}:
        raise IngestionError(f"{field} must be an HTTP(S) URL")
    return url


def _require_non_negative_int(value: Any, field: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IngestionError(f"{field} must be a non-negative integer or null")
    return value


def _validate_record(record: Any, *, source_id: str, index: int, source_url: str) -> None:
    if not isinstance(record, dict):
        raise IngestionError(f"{source_id}.records[{index}] must be an object")
    required = (
        "source_record_id",
        "title",
        "advertised_employer",
        "host_organization",
        "host_association_verified",
        "host_association_type",
        "host_association_evidence",
        "location",
        "closing_date",
        "closing_time",
        "contract",
        "work_pattern",
        "salary",
        "apply_url",
        "job_reference",
        "source_url",
        "location_area",
        "job_area",
        "evidence",
    )
    missing = [field for field in required if field not in record]
    if missing:
        raise IngestionError(f"{source_id}.records[{index}] missing fields: {', '.join(missing)}")
    for field in required:
        if field == "evidence":
            continue
        if field == "host_association_verified":
            if not isinstance(record[field], bool):
                raise IngestionError(f"{source_id}.records[{index}].host_association_verified must be boolean")
            continue
        if field in {"apply_url", "source_url"}:
            _require_url(record[field], f"{source_id}.records[{index}].{field}", allow_empty=field == "apply_url")
            continue
        _require_string(record[field], f"{source_id}.records[{index}].{field}")
    if record["host_association_type"] not in HOST_ASSOCIATION_TYPES:
        raise IngestionError(
            f"{source_id}.records[{index}].host_association_type must be one of "
            + ", ".join(sorted(value or "empty" for value in HOST_ASSOCIATION_TYPES))
        )
    if record["host_association_verified"] and (
        not record["host_organization"].strip()
        or not record["host_association_type"]
        or not record["host_association_evidence"].strip()
    ):
        raise IngestionError(
            f"{source_id}.records[{index}] verified host association requires "
            "host_organization, host_association_type and host_association_evidence"
        )
    if record["location_area"] not in {"", *LOCATION_AREAS}:
        raise IngestionError(f"{source_id}.records[{index}].location_area is not a controlled value")
    if record["job_area"] not in {"", *JOB_AREAS}:
        raise IngestionError(f"{source_id}.records[{index}].job_area is not a controlled value")
    if not isinstance(record["evidence"], dict) or not record["evidence"]:
        raise IngestionError(f"{source_id}.records[{index}].evidence must be a non-empty object")
    if record["source_url"] != source_url:
        # A detail advert may use its own source URL, but it must still be a
        # public URL. The source-level URL remains the completeness route.
        _require_url(record["source_url"], f"{source_id}.records[{index}].source_url")


def validate_source_results(
    payload: Any,
    registry: Any,
    *,
    expected_date: date | None = None,
) -> dict[str, Any]:
    """Validate the complete agent evidence document before it reaches build."""

    if not isinstance(payload, dict):
        raise IngestionError("source_results.json must contain an object")
    if payload.get("schema_version") != INGESTION_SCHEMA_VERSION:
        raise IngestionError(f"source_results schema_version must be {INGESTION_SCHEMA_VERSION}")
    date_checked = _require_string(payload.get("date_checked"), "date_checked", allow_empty=False)
    try:
        parsed_date = date.fromisoformat(date_checked)
    except ValueError as exc:
        raise IngestionError("date_checked must be YYYY-MM-DD") from exc
    if expected_date is not None and parsed_date != expected_date:
        raise IngestionError(f"source_results date_checked {date_checked} does not match requested {expected_date.isoformat()}")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise IngestionError("sources must be an array")
    seen: set[str] = set()
    for index, item in enumerate(sources):
        if not isinstance(item, dict):
            raise IngestionError(f"sources[{index}] must be an object")
        source_id = _require_string(item.get("source_id"), f"sources[{index}].source_id", allow_empty=False)
        if source_id in seen:
            raise IngestionError(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        try:
            spec = registry.get(source_id)
        except KeyError as exc:
            raise IngestionError(str(exc)) from exc
        status_value = _require_string(item.get("status"), f"{source_id}.status", allow_empty=False)
        try:
            status = SourceStatus(status_value)
        except ValueError as exc:
            raise IngestionError(f"{source_id}.status is not a supported SourceStatus") from exc
        source_url = _require_url(
            item.get("source_url") or spec.official_entry_url,
            f"{source_id}.source_url",
        )
        _require_string(item.get("retrieval_method"), f"{source_id}.retrieval_method", allow_empty=False)
        _require_string(item.get("verification_method"), f"{source_id}.verification_method", allow_empty=False)
        _require_string(item.get("completeness_evidence"), f"{source_id}.completeness_evidence", allow_empty=False)
        _require_string(item.get("checked_at"), f"{source_id}.checked_at", allow_empty=False)
        if not isinstance(item.get("warnings", []), list) or not all(isinstance(value, str) for value in item.get("warnings", [])):
            raise IngestionError(f"{source_id}.warnings must be an array of strings")
        if not isinstance(item.get("errors", []), list) or not all(isinstance(value, str) for value in item.get("errors", [])):
            raise IngestionError(f"{source_id}.errors must be an array of strings")
        reported_totals = item.get("reported_totals", {})
        if not isinstance(reported_totals, dict) or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in reported_totals.items()
        ):
            raise IngestionError(f"{source_id}.reported_totals must be an object of non-negative integers")
        source_total = _require_non_negative_int(item.get("source_total"), f"{source_id}.source_total", allow_none=True)
        records = item.get("records")
        if not isinstance(records, list):
            raise IngestionError(f"{source_id}.records must be an array")
        captured_total = _require_non_negative_int(item.get("captured_total"), f"{source_id}.captured_total")
        if captured_total != len(records):
            raise IngestionError(f"{source_id}.captured_total must equal len(records)")
        if status == SourceStatus.COMPLETE and source_total is not None and captured_total != source_total:
            raise IngestionError(f"{source_id} marked Complete but captured_total does not equal source_total")
        if source_total is not None and captured_total > source_total:
            raise IngestionError(f"{source_id}.captured_total exceeds source_total")
        for record_index, record in enumerate(records):
            _validate_record(record, source_id=source_id, index=record_index, source_url=source_url)
    missing = sorted(source.source_id for source in registry.mandatory if source.source_id not in seen)
    if missing:
        raise IngestionError("mandatory sources missing from source_results.json: " + ", ".join(missing))
    return {
        "schema_version": INGESTION_SCHEMA_VERSION,
        "date_checked": date_checked,
        "source_count": len(sources),
        "mandatory_source_count": len(registry.mandatory),
        "source_ids": sorted(seen),
    }


def _raw_vacancy(record: dict[str, Any], source_id: str, source_url: str) -> RawVacancy:
    evidence = dict(record["evidence"])
    evidence.setdefault("agent_supplied_semantics", bool(record["location_area"] or record["job_area"]))
    evidence.setdefault("source_url", source_url)
    return RawVacancy(
        source_id=source_id,
        source_url=_require_url(record["source_url"], f"{source_id}.records.source_url"),
        source_record_id=record["source_record_id"],
        organization_raw=record["advertised_employer"],
        title_raw=record["title"],
        location_raw=record["location"],
        closing_date_raw=record["closing_date"],
        closing_time_raw=record["closing_time"],
        contract_raw=record["contract"],
        work_pattern_raw=record["work_pattern"],
        salary_raw=record["salary"],
        apply_url_raw=record["apply_url"],
        reference_raw=record["job_reference"],
        advertised_employer_raw=record["advertised_employer"],
        host_organization_raw=record["host_organization"],
        host_association_verified=record["host_association_verified"],
        host_association_type=record["host_association_type"],
        host_association_evidence=record["host_association_evidence"],
        description_raw=record.get("description", ""),
        retrieved_at=str(evidence.get("checked_at") or evidence.get("retrieved_at") or ""),
        location_area_raw=record["location_area"],
        job_area_raw=record["job_area"],
        evidence=evidence,
    )


def load_source_results(path: Path, registry: Any, *, expected_date: date | None = None) -> list[SourceResult]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionError(f"cannot read structured source evidence: {path}: {exc}") from exc
    validate_source_results(payload, registry, expected_date=expected_date)
    results: list[SourceResult] = []
    for item in payload["sources"]:
        spec: SourceSpec = registry.get(item["source_id"])
        source_url = item.get("source_url") or spec.official_entry_url
        results.append(
            SourceResult(
                source_id=spec.source_id,
                source_name=spec.display_name,
                mandatory=spec.mandatory,
                retrieval_method=item["retrieval_method"],
                source_total=item["source_total"],
                captured_total=item["captured_total"],
                raw_vacancies=[_raw_vacancy(record, spec.source_id, source_url) for record in item["records"]],
                status=SourceStatus(item["status"]),
                warnings=list(item.get("warnings", [])),
                errors=list(item.get("errors", [])),
                checked_at=item["checked_at"],
                source_url=source_url,
                verification_method=item["verification_method"],
                reported_totals=dict(item.get("reported_totals", {})),
                completeness_evidence=item["completeness_evidence"],
            )
        )
    return results


def _ingestion_record(raw: RawVacancy) -> dict[str, Any]:
    return {
        "source_record_id": raw.source_record_id,
        "title": raw.title_raw,
        "advertised_employer": raw.advertised_employer_raw or raw.organization_raw,
        "host_organization": raw.host_organization_raw,
        "host_association_verified": raw.host_association_verified,
        "host_association_type": raw.host_association_type,
        "host_association_evidence": raw.host_association_evidence,
        "location": raw.location_raw,
        "closing_date": raw.closing_date_raw,
        "closing_time": raw.closing_time_raw,
        "contract": raw.contract_raw,
        "work_pattern": raw.work_pattern_raw,
        "salary": raw.salary_raw,
        "apply_url": raw.apply_url_raw,
        "job_reference": raw.reference_raw,
        "source_url": raw.source_url,
        "location_area": raw.location_area_raw or str(raw.evidence.get("location_area", "")),
        "job_area": raw.job_area_raw or str(raw.evidence.get("job_area", "")),
        "description": raw.description_raw,
        "evidence": raw.evidence or {"source_url": raw.source_url},
    }


def structured_payload(results: Iterable[SourceResult], *, date_checked: date) -> dict[str, Any]:
    return {
        "schema_version": INGESTION_SCHEMA_VERSION,
        "date_checked": date_checked.isoformat(),
        "sources": [
            {
                "source_id": result.source_id,
                "status": result.status.value,
                "retrieval_method": result.retrieval_method,
                "verification_method": result.verification_method,
                "completeness_evidence": result.completeness_evidence,
                "source_total": result.source_total,
                "captured_total": len(result.raw_vacancies),
                "source_url": result.source_url,
                "checked_at": result.checked_at,
                "warnings": result.warnings,
                "errors": result.errors,
                "reported_totals": result.reported_totals,
                "records": [_ingestion_record(raw) for raw in result.raw_vacancies],
            }
            for result in results
        ],
    }


def write_structured_source_results(results: Iterable[SourceResult], path: Path, *, date_checked: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = structured_payload(results, date_checked=date_checked)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
