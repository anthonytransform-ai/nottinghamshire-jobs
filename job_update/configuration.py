"""Runtime loading for tracked policy rules and run-local decisions."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any, Iterable

from .models import RawVacancy


ALLOWED_RESOLUTION_FIELDS = {
    "location_area",
    "job_area",
    "advertised_employer",
    "host_organization",
    "host_association_verified",
    "host_association_type",
    "host_association_evidence",
    "policy",
}
FORBIDDEN_RESOLUTION_FIELDS = {
    "closing_date",
    "closing_time",
    "live_status",
    "reference",
    "job_reference",
    "source_record_id",
}


def resolution_key(raw: RawVacancy) -> str:
    """Return a stable operator-facing key without inventing a public ID."""

    if raw.source_record_id.strip():
        return f"{raw.source_id}::{raw.source_record_id.strip()}"
    identity = "|".join(
        (
            raw.source_id,
            raw.apply_url_raw.strip(),
            " ".join(raw.title_raw.casefold().split()),
            " ".join(raw.location_raw.casefold().split()),
            raw.closing_date_raw.strip(),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"{raw.source_id}::anonymous-{digest}"


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            value = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_resolutions(path: Path) -> dict[str, dict[str, Any]]:
    """Load only safe, explicit review decisions from a TOML file."""

    data = _read_toml(path)
    entries = data.get("resolutions", data.get("resolution", []))
    if isinstance(entries, dict):
        entries = [dict(value, key=key) if isinstance(value, dict) else {"key": key} for key, value in entries.items()]
    if not isinstance(entries, list):
        return {}
    loaded: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("key", "")).strip():
            continue
        key = str(entry["key"]).strip()
        decision: dict[str, Any] = {}
        for field, value in entry.items():
            if field == "key" or value in (None, ""):
                continue
            if field in FORBIDDEN_RESOLUTION_FIELDS:
                # A hand-edited file must not be able to alter source evidence.
                continue
            if field in ALLOWED_RESOLUTION_FIELDS:
                decision[field] = value
        if decision:
            loaded[key] = decision
    return loaded


def load_tracked_overrides(path: Path) -> list[dict[str, Any]]:
    """Load durable classification overrides when an operator has opted in.

    The repository ships only ``overrides.example.toml``.  A real
    ``config/overrides.toml`` is intentionally ignored by git and is never
    required for a valid run.
    """

    data = _read_toml(path)
    output: list[dict[str, Any]] = []
    for section, field in (("location_area", "location_area"), ("job_area", "job_area")):
        entries = data.get(section, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("value", "")).strip():
                output.append({field: str(entry["value"]).strip(), **entry})
    return output


def _matches(raw: RawVacancy, decision: dict[str, Any]) -> bool:
    if decision.get("source_id") and decision["source_id"] != raw.source_id:
        return False
    if decision.get("source_record_id") and decision["source_record_id"] != raw.source_record_id:
        return False
    if decision.get("title") and decision["title"] != raw.title_raw:
        return False
    return bool(decision.get("source_record_id") or decision.get("title"))


def apply_resolution(raw: RawVacancy, decision: dict[str, Any] | None) -> RawVacancy:
    """Apply a reviewed decision without changing source-derived evidence."""

    if not decision:
        return raw
    for field in decision:
        if field in FORBIDDEN_RESOLUTION_FIELDS:
            continue
        if field not in ALLOWED_RESOLUTION_FIELDS:
            continue
    if decision.get("location_area"):
        raw.evidence["location_area_override"] = str(decision["location_area"])
        raw.evidence["location_area_override_reviewed"] = True
    if decision.get("job_area"):
        raw.evidence["job_area_override"] = str(decision["job_area"])
        raw.evidence["job_area_override_reviewed"] = True
    if decision.get("advertised_employer"):
        raw.advertised_employer_raw = str(decision["advertised_employer"]).strip()
        raw.organization_raw = raw.advertised_employer_raw
        raw.evidence["advertised_employer_reviewed"] = True
    if decision.get("host_organization"):
        raw.host_organization_raw = str(decision["host_organization"]).strip()
    if "host_association_verified" in decision:
        raw.host_association_verified = bool(decision["host_association_verified"])
    if decision.get("host_association_type"):
        raw.host_association_type = str(decision["host_association_type"]).strip()
    if decision.get("host_association_evidence"):
        raw.host_association_evidence = str(decision["host_association_evidence"]).strip()
    if decision.get("policy") in {"include", "exclude"}:
        raw.evidence["review_policy"] = decision["policy"]
    if decision:
        raw.evidence["resolution_key"] = resolution_key(raw)
        raw.evidence["resolution_applied"] = True
    return raw


def apply_tracked_overrides(raw: RawVacancy, overrides: Iterable[dict[str, Any]]) -> RawVacancy:
    for decision in overrides:
        if _matches(raw, decision):
            apply_resolution(raw, decision)
    return raw
