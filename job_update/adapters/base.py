"""Adapter protocol and common result helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import RawVacancy, RunContext, SourceResult, SourceSpec, SourceStatus
from ..timezone import london_now
from .common import prepare_source_metadata


class SourceAdapter(Protocol):
    source_id: str
    spec: SourceSpec

    def fetch(self, context: RunContext) -> SourceResult:
        ...


class BaseAdapter:
    def __init__(self, spec: SourceSpec) -> None:
        self.spec = spec
        self.source_id = spec.source_id

    def result(
        self,
        *,
        method: str,
        raw: list[RawVacancy] | None = None,
        source_total: int | None = None,
        status: SourceStatus = SourceStatus.COMPLETE,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        source_url: str | None = None,
        verification_method: str = "primary-platform-listing",
        reported_totals: dict[str, int] | None = None,
        exclusions: list[dict[str, str]] | None = None,
    ) -> SourceResult:
        records = raw or []
        for record in records:
            prepare_source_metadata(record, self.spec)
            if (
                not record.location_raw
                and self.spec.configuration.get("location_default")
                and self.spec.configuration.get("location_default_verified", False)
            ):
                record.location_raw = str(self.spec.configuration["location_default"])
                record.evidence["location_default_applied"] = True
        unique_keys = {
            record.source_record_id
            or record.reference_raw
            or record.apply_url_raw
            or f"{record.title_raw}|{record.location_raw}|{record.closing_date_raw}"
            for record in records
        }
        return SourceResult(
            source_id=self.spec.source_id,
            source_name=self.spec.display_name,
            mandatory=self.spec.mandatory,
            retrieval_method=method,
            source_total=source_total,
            captured_total=len(unique_keys),
            raw_vacancies=records,
            status=status,
            warnings=warnings or [],
            errors=errors or [],
            checked_at=london_now().isoformat(),
            source_url=source_url or self.spec.official_entry_url,
            verification_method=verification_method,
            reported_totals=reported_totals or {},
            exclusions=exclusions or [],
        )


def blocked_result(spec: SourceSpec, error: str, *, source_url: str = "") -> SourceResult:
    return SourceResult(
        source_id=spec.source_id,
        source_name=spec.display_name,
        mandatory=spec.mandatory,
        retrieval_method="none",
        source_total=None,
        captured_total=0,
        raw_vacancies=[],
        status=SourceStatus.BLOCKED,
        errors=[error],
        checked_at=london_now().isoformat(),
        source_url=source_url or spec.official_entry_url,
    )
