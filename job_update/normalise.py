"""Policy-preserving conversion from raw source fields to website fields."""

from __future__ import annotations

from .models import NormalizedVacancy, RawVacancy, SourceSpec


def canonical_organization(raw: RawVacancy, spec: SourceSpec) -> str:
    configured = str(spec.configuration.get("organization", "")).strip()
    discovered = raw.organization_raw.strip()
    if configured and not spec.configuration.get("allow_organization_from_advert", False):
        return configured
    return discovered or configured or spec.display_name.split(" — ", 1)[0].strip()


def normalize_contract(value: str) -> str:
    text = value.casefold()
    if "apprent" in text:
        return "Apprenticeship"
    if "permanent" in text or "ongoing" in text:
        return "Permanent"
    if "fixed" in text or "term" in text:
        return "Fixed-term"
    if "temporary" in text or "temp " in text:
        return "Temporary"
    if any(term in text for term in ("bank", "casual", "sessional")):
        return "Bank/Casual/Sessional"
    if "freelance" in text or "contractor" in text:
        return "Freelance"
    return "Other"


def normalize_work_pattern(value: str) -> str:
    text = " ".join(value.casefold().split())
    if "full-time or part-time" in text or "full time or part time" in text or "full/part" in text:
        return "Full-time or Part-time"
    if "variable" in text or "sessional" in text or "as required" in text:
        return "Variable/Sessional"
    if "full-time" in text or "full time" in text:
        return "Full-time"
    if "part-time" in text or "part time" in text:
        return "Part-time"
    return "Not stated"


def normalized_vacancy(
    raw: RawVacancy,
    spec: SourceSpec,
    *,
    date_checked: str,
    location_area: str,
    job_area: str,
    closing_date: str,
    verification_method: str,
) -> NormalizedVacancy:
    organization = canonical_organization(raw, spec)
    return NormalizedVacancy(
        organization=organization,
        employer_type=spec.employer_type,
        job_title=" ".join(raw.title_raw.split()),
        job_area=job_area,
        location=" ".join((raw.location_raw or spec.configuration.get("location_default", "")).split()),
        location_area=location_area,
        closing_date=closing_date,
        closing_time=raw.closing_time_raw,
        contract_type=normalize_contract(raw.contract_raw),
        work_pattern=normalize_work_pattern(raw.work_pattern_raw),
        salary=" ".join(raw.salary_raw.split()),
        apply_url=raw.apply_url_raw.strip(),
        job_reference=(raw.reference_raw or raw.source_record_id).strip(),
        date_checked=date_checked,
        source_url=raw.source_url.strip(),
        source_id=raw.source_id,
        verification_method=verification_method,
        evidence=raw.evidence,
    )
