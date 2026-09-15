"""Small stable-collector helpers.

These helpers are intentionally not a general recruitment-site parser.  The
weekly agent supplies structured evidence for mutable sources; this module
only supports the retained Oracle API collector and its public advert fields.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from ..html_tools import clean_text
from ..models import RawVacancy, SourceSpec


MONTHS = {
    name.casefold(): number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
MONTHS.update({name[:3].casefold(): number for name, number in list(MONTHS.items()) if len(name) > 3})
MONTHS["sept"] = 9


def parse_date_text(value: str, *, reference_year: int | None = None) -> str:
    text = clean_text(value)
    iso = re.search(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        except ValueError:
            return ""
    dmy = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text)
    if dmy:
        try:
            return date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1))).isoformat()
        except ValueError:
            return ""
    long_date = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b", text, re.I)
    if long_date and long_date.group(2).casefold() in MONTHS:
        try:
            return date(int(long_date.group(3)), MONTHS[long_date.group(2).casefold()], int(long_date.group(1))).isoformat()
        except ValueError:
            return ""
    if reference_year:
        day_month = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\b", text, re.I)
        if day_month and day_month.group(2).casefold() in MONTHS:
            try:
                return date(reference_year, MONTHS[day_month.group(2).casefold()], int(day_month.group(1))).isoformat()
            except ValueError:
                return ""
    return ""


def parse_time_text(value: str) -> str:
    text = clean_text(value).casefold().replace(".", "")
    match = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", text)
    if not match:
        return ""
    hour, minute = int(match.group(1)), int(match.group(2))
    if match.group(3) == "pm" and hour < 12:
        hour += 12
    if match.group(3) == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}" if hour <= 23 and minute <= 59 else ""


def extract_deadline(text: str) -> tuple[str, str]:
    match = re.search(
        r"(?:closing\s+date|application\s+deadline|apply\s+before|applications?\s+close|closing)\s*[:\-]?\s*(.{0,80})",
        clean_text(text),
        re.I,
    )
    if not match:
        return "", ""
    value = match.group(1)
    return parse_date_text(value), parse_time_text(value)


def make_raw(
    *,
    source_id: str,
    source_url: str,
    record_id: str,
    title: str,
    organization: str,
    location: str,
    deadline: str,
    closing_time: str,
    contract: str = "",
    work_pattern: str = "",
    salary: str = "",
    apply_url: str = "",
    reference: str = "",
    advertised_employer: str = "",
    host_organization: str = "",
    host_association_verified: bool = False,
    host_association_type: str = "",
    host_association_evidence: str = "",
    description: str = "",
    evidence: dict[str, object] | None = None,
) -> RawVacancy:
    advertised = clean_text(advertised_employer or organization)
    host = clean_text(host_organization)
    return RawVacancy(
        source_id=source_id,
        source_url=source_url,
        source_record_id=record_id,
        organization_raw=advertised,
        title_raw=clean_text(title),
        location_raw=clean_text(location),
        closing_date_raw=clean_text(deadline),
        closing_time_raw=clean_text(closing_time),
        contract_raw=clean_text(contract),
        work_pattern_raw=clean_text(work_pattern),
        salary_raw=clean_text(salary),
        apply_url_raw=apply_url,
        reference_raw=clean_text(reference),
        advertised_employer_raw=advertised,
        host_organization_raw=host,
        host_association_verified=host_association_verified,
        host_association_type=clean_text(host_association_type),
        host_association_evidence=clean_text(host_association_evidence),
        description_raw=clean_text(description),
        retrieved_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        evidence=dict(evidence or {}),
    )


def prepare_source_metadata(raw: RawVacancy, spec: SourceSpec) -> RawVacancy:
    """Apply only stable configured Oracle host metadata."""

    raw.advertised_employer_raw = clean_text(raw.advertised_employer_raw or raw.organization_raw)
    raw.organization_raw = raw.organization_raw or raw.advertised_employer_raw
    if not raw.host_organization_raw:
        raw.host_organization_raw = str(spec.expected_host_service or spec.configuration.get("organization", "")).strip()
    if raw.host_organization_raw and not raw.host_association_verified:
        advertised = " ".join(raw.advertised_employer_raw.casefold().replace("&", "and").split())
        host = " ".join(raw.host_organization_raw.casefold().replace("&", "and").split())
        if advertised and (advertised == host or advertised in host or host in advertised):
            raw.host_association_verified = True
            raw.host_association_type = raw.host_association_type or "direct"
            raw.host_association_evidence = raw.host_association_evidence or "stable collector employer matches configured host"
    raw.evidence.setdefault("advertised_employer", raw.advertised_employer_raw)
    raw.evidence.setdefault("host_organization", raw.host_organization_raw)
    raw.evidence.setdefault("host_association_verified", raw.host_association_verified)
    return raw
