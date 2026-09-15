"""Strict Nottinghamshire and fixed-deadline eligibility rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlparse

from .adapters.common import parse_date_text, parse_time_text
from .models import RawVacancy
from .timezone import london_now


@dataclass
class EligibilityDecision:
    included: bool
    review: bool
    reason: str = ""
    closing_date: str = ""
    closing_time: str = ""


def evaluate(
    raw: RawVacancy,
    *,
    update_date: date,
    employer_type: str,
    location_area: str | None,
    job_area: str | None,
    now: datetime | None = None,
) -> EligibilityDecision:
    evidence_text = " ".join((raw.description_raw, raw.title_raw, raw.organization_raw)).casefold()
    flags = raw.evidence
    if employer_type not in {"Council", "NHS", "VCSE", "Education"}:
        return EligibilityDecision(False, False, "employer type is outside the publication contract")
    if any(bool(flags.get(key)) for key in ("internal_only", "withdrawn", "overseas")):
        return EligibilityDecision(False, False, "internal, withdrawn or overseas vacancy")
    if bool(flags.get("review_policy")) and str(flags["review_policy"]).casefold() == "exclude":
        return EligibilityDecision(False, False, "explicit reviewed policy exclusion")
    if bool(flags.get("out_of_scope_employer")) or bool(flags.get("not_nhs_employer")):
        return EligibilityDecision(False, False, "advertised employer is outside the configured source scope")
    if bool(flags.get("detail_required")) and not bool(flags.get("detail_verified")):
        return EligibilityDecision(False, True, "source requires detail-level verification before publication")
    if employer_type == "Education" and (
        bool(flags.get("independent"))
        or bool(flags.get("private"))
        or bool(flags.get("commercial_training_provider"))
    ):
        return EligibilityDecision(False, False, "independent, private or commercial education provider")
    if employer_type == "Education" and bool(flags.get("external_apprenticeship")):
        return EligibilityDecision(False, False, "external apprenticeship/student opportunity, not college employment")
    if employer_type in {"Council", "NHS", "Education"}:
        advertised = " ".join((raw.advertised_employer_raw or raw.organization_raw).casefold().split())
        contractor_marker = bool(flags.get("agency") or flags.get("subcontractor") or flags.get("generic_agency"))
        host_source = raw.host_organization_raw or ("" if contractor_marker else raw.organization_raw)
        host = " ".join(host_source.casefold().split())
        direct = bool(advertised and host and (advertised == host or advertised in host or host in advertised))
        association_verified = bool(raw.host_association_verified or flags.get("host_association_verified") or direct)
        if not association_verified:
            if bool(flags.get("agency")) or bool(flags.get("subcontractor")) or bool(flags.get("generic_agency")):
                return EligibilityDecision(False, False, "agency/subcontractor host is not identified or verified")
            return EligibilityDecision(False, True, "host/service association is unresolved")
    if bool(flags.get("open_ended")):
        return EligibilityDecision(False, False, "open-ended vacancy has no fixed deadline")
    if employer_type == "Education" and bool(flags.get("studentship")) and "paid employment" not in evidence_text:
        return EligibilityDecision(False, False, "non-employment studentship/study opportunity")
    if bool(flags.get("unpaid_volunteering")) or re.search(
        r"\b(unpaid\s+(?:volunteer(?:ing)?|role|work\s+experience)|volunteer(?:ing)?\s+opportunity|work\s+experience\s+placement)\b",
        evidence_text,
    ):
        return EligibilityDecision(False, False, "unpaid volunteering/work experience")
    if re.search(r"\b(talent pool|talentpool|speculative|open application|register your interest|open until filled|rolling recruitment)\b", evidence_text):
        return EligibilityDecision(False, False, "talent-pool, speculative or open-ended recruitment")
    if employer_type == "VCSE" and re.search(r"\b(recruitment agency|agency worker|private limited|commercial care)\b", evidence_text):
        return EligibilityDecision(False, False, "VCSE source record is a commercial/agency role")
    if not raw.title_raw.strip():
        return EligibilityDecision(False, True, "job title is missing")
    if not location_area:
        return EligibilityDecision(False, True, "actual Nottinghamshire work base is unresolved")
    if not raw.closing_date_raw.strip():
        return EligibilityDecision(False, True, "fixed closing date is missing; no date inferred")
    closing_date = parse_date_text(raw.closing_date_raw, reference_year=update_date.year)
    if not closing_date:
        return EligibilityDecision(False, True, "closing date could not be parsed without guessing")
    try:
        parsed_date = date.fromisoformat(closing_date)
    except ValueError:
        return EligibilityDecision(False, True, "closing date is not canonical")
    if parsed_date < update_date:
        return EligibilityDecision(False, False, "closing date has passed", closing_date)
    closing_time = parse_time_text(raw.closing_time_raw)
    if raw.closing_time_raw.strip() and not closing_time:
        return EligibilityDecision(False, True, "closing time could not be parsed", closing_date)
    current = now or london_now()
    if parsed_date == current.date() == update_date and closing_time:
        hour, minute = (int(part) for part in closing_time.split(":"))
        if current.hour * 60 + current.minute >= hour * 60 + minute:
            return EligibilityDecision(False, False, "same-day closing time has passed in Europe/London", closing_date, closing_time)
    if not raw.apply_url_raw or urlparse(raw.apply_url_raw).scheme not in {"http", "https"}:
        return EligibilityDecision(False, True, "current application URL is missing or not HTTP(S)", closing_date, closing_time)
    if not raw.source_url or urlparse(raw.source_url).scheme not in {"http", "https"}:
        return EligibilityDecision(False, True, "source URL is missing or not HTTP(S)", closing_date, closing_time)
    if not job_area:
        return EligibilityDecision(False, True, "job-area classification remains ambiguous", closing_date, closing_time)
    return EligibilityDecision(True, False, "eligible", closing_date, closing_time)
