"""Protocol and result helper for the retained stable collectors."""

from __future__ import annotations

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
        verification_method: str = "official-api",
        reported_totals: dict[str, int] | None = None,
    ) -> SourceResult:
        records = raw or []
        for record in records:
            prepare_source_metadata(record, self.spec)
        return SourceResult(
            source_id=self.spec.source_id,
            source_name=self.spec.display_name,
            mandatory=self.spec.mandatory,
            retrieval_method=method,
            source_total=source_total,
            captured_total=len(records),
            raw_vacancies=records,
            status=status,
            warnings=warnings or [],
            errors=errors or [],
            checked_at=london_now().isoformat(),
            source_url=source_url or self.spec.official_entry_url,
            verification_method=verification_method,
            reported_totals=reported_totals or {},
            completeness_evidence=self.spec.completeness_evidence,
        )


def blocked_result(spec: SourceSpec, error: str, *, source_url: str = "") -> SourceResult:
    return SourceResult(
        source_id=spec.source_id,
        source_name=spec.display_name,
        mandatory=spec.mandatory,
        retrieval_method="stable-collector",
        source_total=None,
        captured_total=0,
        raw_vacancies=[],
        status=SourceStatus.BLOCKED,
        errors=[error],
        checked_at=london_now().isoformat(),
        source_url=source_url or spec.official_entry_url,
        verification_method="official-api",
        completeness_evidence=spec.completeness_evidence,
    )
