"""Strict Nottinghamshire and inclusive 56-day eligibility rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
    if bool(flags.get("employer_mismatch")):
        return EligibilityDecision(False, False, "shared recruitment result does not verify the configured employer")
    if bool(flags.get("open_ended")):
        return EligibilityDecision(False, False, "open-ended vacancy has no fixed deadline")
    if employer_type == "Education" and bool(flags.get("studentship")) and "paid employment" not in evidence_text:
        return EligibilityDecision(False, False, "non-employment studentship/study opportunity")
    if re.search(r"\b(unpaid\s+volunteer|volunteer(?:ing)?|unpaid\s+work\s+experience|work experience placement)\b", evidence_text):
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
    end_date = update_date + timedelta(days=56)
    if parsed_date < update_date:
        return EligibilityDecision(False, False, "closing date has passed", closing_date)
    if parsed_date > end_date:
        return EligibilityDecision(False, False, "closing date is beyond the inclusive 56-day window", closing_date)
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
