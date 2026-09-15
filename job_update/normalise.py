"""Policy-preserving conversion from raw source fields to website fields."""

from __future__ import annotations

import re

from .models import NormalizedVacancy, RawVacancy, SourceSpec


def canonical_organization(raw: RawVacancy, spec: SourceSpec) -> str:
    configured = str(spec.configuration.get("organization", "")).strip()
    advertised = (raw.advertised_employer_raw or raw.organization_raw).strip()
    host = (raw.host_organization_raw or configured).strip()
    if advertised and (not host or raw.host_association_verified or _same_organization(advertised, host)):
        return advertised
    return host or advertised or spec.display_name.split(" — ", 1)[0].strip()


def _same_organization(left: str, right: str) -> bool:
    left_value = " ".join(left.casefold().replace("&", "and").split())
    right_value = " ".join(right.casefold().replace("&", "and").split())
    return bool(left_value and right_value and (left_value == right_value or left_value in right_value or right_value in left_value))


def normalize_contract(value: str) -> str:
    text = value.casefold()
    if "apprent" in text:
        return "Apprenticeship"
    if "permanent" in text or "ongoing" in text:
        return "Permanent"
    if re.search(r"\bfixed[\s-]+term\b|\bfixed[\s-]+until\b", text):
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
        job_reference=raw.reference_raw.strip(),
        date_checked=date_checked,
        source_url=raw.source_url.strip(),
        source_id=raw.source_id,
        verification_method=verification_method,
        evidence=raw.evidence,
        source_record_id=raw.source_record_id,
        advertised_employer=(raw.advertised_employer_raw or raw.organization_raw).strip(),
        host_organization=raw.host_organization_raw.strip(),
        host_association_verified=raw.host_association_verified,
        host_association_type=raw.host_association_type,
        host_association_evidence=raw.host_association_evidence,
    )
