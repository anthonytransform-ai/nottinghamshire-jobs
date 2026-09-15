"""Shared data contracts for retrieval, audit and publication."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class SourceStatus(str, Enum):
    COMPLETE = "Complete"
    COMPLETE_WITH_FALLBACK = "Complete with fallback"
    PARTIALLY_VERIFIED = "Partially verified"
    BLOCKED = "Blocked"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    display_name: str
    employer_type: str
    mandatory: bool
    official_entry_url: str
    source_type: str = "agent-researched"
    collector: str = ""
    playbook_notes: str = ""
    expected_host_service: str = ""
    completeness_evidence: str = ""
    stable_data_route: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawVacancy:
    """Source-shaped record retained before policy classification."""

    source_id: str
    source_url: str
    source_record_id: str = ""
    organization_raw: str = ""
    title_raw: str = ""
    location_raw: str = ""
    closing_date_raw: str = ""
    closing_time_raw: str = ""
    contract_raw: str = ""
    work_pattern_raw: str = ""
    salary_raw: str = ""
    apply_url_raw: str = ""
    reference_raw: str = ""
    advertised_employer_raw: str = ""
    host_organization_raw: str = ""
    host_association_verified: bool = False
    host_association_type: str = ""
    host_association_evidence: str = ""
    description_raw: str = ""
    retrieved_at: str = ""
    location_area_raw: str = ""
    job_area_raw: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RawVacancy":
        fields = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: value.get(key) for key in fields if key in value})


@dataclass
class SourceResult:
    source_id: str
    source_name: str
    mandatory: bool
    retrieval_method: str
    source_total: int | None
    captured_total: int
    raw_vacancies: list[RawVacancy]
    eligible_hint_count: int = 0
    status: SourceStatus = SourceStatus.BLOCKED
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checked_at: str = ""
    source_url: str = ""
    verification_method: str = ""
    reported_totals: dict[str, int] = field(default_factory=dict)
    exclusions: list[dict[str, str]] = field(default_factory=list)
    completeness_evidence: str = ""

    def to_dict(self, *, include_raw: bool = True) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        if not include_raw:
            result.pop("raw_vacancies", None)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceResult":
        raw = [RawVacancy.from_dict(item) for item in value.get("raw_vacancies", [])]
        status = value.get("status", SourceStatus.BLOCKED)
        if not isinstance(status, SourceStatus):
            status = SourceStatus(status)
        known = {
            "source_id",
            "source_name",
            "mandatory",
            "retrieval_method",
            "source_total",
            "captured_total",
            "eligible_hint_count",
            "warnings",
            "errors",
            "checked_at",
            "source_url",
            "verification_method",
            "reported_totals",
            "exclusions",
            "completeness_evidence",
        }
        kwargs = {key: value.get(key) for key in known if key in value}
        kwargs["raw_vacancies"] = raw
        kwargs["status"] = status
        return cls(**kwargs)


@dataclass
class NormalizedVacancy:
    """The exact website row plus internal provenance used for audit/dedupe."""

    organization: str
    employer_type: str
    job_title: str
    job_area: str
    location: str
    location_area: str
    closing_date: str
    closing_time: str
    contract_type: str
    work_pattern: str
    salary: str
    apply_url: str
    job_reference: str
    date_checked: str
    source_url: str
    source_id: str = ""
    verification_method: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    source_record_id: str = ""
    advertised_employer: str = ""
    host_organization: str = ""
    host_association_verified: bool = False
    host_association_type: str = ""
    host_association_evidence: str = ""

    def to_csv_row(self) -> dict[str, str]:
        return {
            "organization": self.organization,
            "employer_type": self.employer_type,
            "job_title": self.job_title,
            "job_area": self.job_area,
            "location": self.location,
            "location_area": self.location_area,
            "closing_date": self.closing_date,
            "closing_time": self.closing_time,
            "contract_type": self.contract_type,
            "work_pattern": self.work_pattern,
            "salary": self.salary,
            "apply_url": self.apply_url,
            "job_reference": self.job_reference,
            "date_checked": self.date_checked,
            "source_url": self.source_url,
        }


@dataclass
class ReviewItem:
    source: str
    title: str
    organization: str
    relevant_evidence: dict[str, Any]
    ambiguous_field: str
    candidate_values: list[str]
    reason: str
    source_record_id: str = ""
    resolution_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Exclusion:
    source_id: str
    title: str
    organization: str
    reason: str
    source_record_id: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunContext:
    date_checked: date
    run_dir: Any
    registry: Any
    http_client: Any = None
    live: bool = False
    now: datetime | None = None
    classification_rules: Any = None
    overrides: dict[str, Any] = field(default_factory=dict)
