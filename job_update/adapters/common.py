"""Parsing primitives shared by source-specific adapters."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Iterable
from urllib.parse import urljoin

from ..html_tools import absolute_url, clean_text, extract_links, extract_tag_blocks, first_attr
from ..models import RawVacancy


MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
        start=1,
    )
}
MONTHS.update({name[:3].lower(): number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    start=1,
)})
MONTHS["sept"] = 9


def parse_date_text(value: str, *, reference_year: int | None = None) -> str:
    text = clean_text(value).strip()
    if not text:
        return ""
    iso = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
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
    long_date = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(20\d{2})\b",
        text,
        re.I,
    )
    if long_date and long_date.group(2).lower() in MONTHS:
        try:
            return date(int(long_date.group(3)), MONTHS[long_date.group(2).lower()], int(long_date.group(1))).isoformat()
        except ValueError:
            return ""
    month_first = re.search(r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b", text, re.I)
    if month_first and month_first.group(1).lower() in MONTHS:
        try:
            return date(int(month_first.group(3)), MONTHS[month_first.group(1).lower()], int(month_first.group(2))).isoformat()
        except ValueError:
            return ""
    if reference_year:
        day_month = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\b", text, re.I)
        if day_month and day_month.group(2).lower() in MONTHS:
            try:
                return date(reference_year, MONTHS[day_month.group(2).lower()], int(day_month.group(1))).isoformat()
            except ValueError:
                return ""
    return ""


def parse_time_text(value: str) -> str:
    text = clean_text(value).strip().lower().replace(".", "")
    if not text:
        return ""
    match = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", text)
    if not match:
        match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text)
        if not match:
            return ""
        hour = int(match.group(1))
        minute = 0
        meridiem = match.group(2)
    else:
        hour = int(match.group(1))
        minute = int(match.group(2))
        meridiem = match.group(3)
    if meridiem:
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def extract_deadline(text: str) -> tuple[str, str]:
    """Extract a labelled closing/application deadline, never a posting date."""

    clean = clean_text(text)
    labels = r"(?:closing\s+date|application\s+deadline|apply\s+before|applications?\s+close|closing)"
    match = re.search(
        rf"{labels}\s*[:\-]?\s*(.{{0,80}})",
        clean,
        re.I,
    )
    if not match:
        return "", ""
    value = match.group(1)
    deadline = parse_date_text(value)
    time = parse_time_text(value)
    return deadline, time


def parse_reported_total(text: str, patterns: Iterable[str]) -> int | None:
    clean = clean_text(text)
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except (TypeError, ValueError):
                continue
    return None


def source_record_id(attrs: str, body: str, base_url: str = "") -> str:
    value = first_attr(
        attrs,
        (
            "data-vacancy-id",
            "data-vac-id",
            "vac-id",
            "data-job-reference",
            "data-job-id",
            "data-jobid",
            "data-oppid",
            "data-opportunity-id",
            "data-reference",
        ),
    )
    if value:
        return value
    for _label, url in extract_links(body, base_url):
        match = re.search(
            r"/candidate/jobadvert/([^?#/]+)|/current-vacancies/([^?#/]+)|/(?:job|jobs|vacancy|opportunity)[/_-]([^?#/]+)|[?&]pid=([A-Za-z0-9_-]+)",
            url,
            re.I,
        )
        if match:
            return next(group for group in match.groups() if group)
    for pattern in (
        r"/current-vacancies/([^?#/]+)",
        r"/candidate/jobadvert/([^?#/]+)",
        r"/(?:jobs?|jobadvert)/([^?#/]+)",
        r"/vacancy\.aspx\?ref=([^&#]+)",
        r"(?:vacancy|opportunity|job)[-_ ]?(?:id|reference)?\s*[:#]?\s*([A-Z0-9][A-Z0-9/_-]{2,})",
        r"VACANCY_ID=([A-Z0-9_-]+)",
        r"[?&]pid=([A-Za-z0-9_-]+)",
    ):
        match = re.search(pattern, clean_text(body), re.I)
        if match:
            return match.group(1)
    return ""


def card_blocks(html: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for tag in ("article", "li", "div"):
        for attrs, body in extract_tag_blocks(html, tag):
            marker = f"{attrs} {body}".lower()
            if any(token in marker for token in ("vacancy", "job-card", "job-listing", "opportunity", "result-card", "job-item", "search-result")):
                blocks.append((attrs, body))
    # Preserve document order approximately and avoid nested duplicates by the
    # stable source id; adapters may further dedupe by reference.
    return blocks


def candidate_blocks(html: str) -> list[tuple[str, str]]:
    """Find card elements without mistaking a page-level result container for a job."""

    tokens = (
        "vacancy",
        "opportunity",
        "job-card",
        "job-result",
        "job-listing",
        "job-item",
        "jobtrain",
        "mhr-card",
        "mhr-jobdetail",
        "vacancy-list",
        "search-result",
        "result-card",
        "teaching-vacancy",
    )
    blocks: list[tuple[str, str]] = []
    for tag in ("article", "li", "div"):
        for attrs, body in extract_tag_blocks(html, tag):
            marker = attrs.casefold()
            if tag == "div" and not any(token in marker for token in tokens):
                continue
            if any(token in marker for token in tokens):
                blocks.append((attrs, body))
    return blocks


def first_title(body: str, fallback: str = "") -> str:
    for pattern in (
        r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>",
        r"<a\b[^>]*(?:class|aria-label)=[\"'][^\"']*(?:title|job)[^\"']*[\"'][^>]*>(.*?)</a>",
        r"<a\b[^>]*>(.*?)</a>",
    ):
        match = re.search(pattern, body, re.I | re.S)
        if match:
            value = clean_text(match.group(1))
            if value:
                return value
    return fallback


def first_link(body: str, base_url: str) -> str:
    links = extract_links(body, base_url)
    for label, url in links:
        if re.search(r"job|vacan|career|opportun|apply|profile", f"{label} {url}", re.I):
            return url
    return links[0][1] if links else ""


def labelled_value(text: str, labels: Iterable[str]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*[:\-]?\s*([^|\n;]{{1,180}})", text, re.I)
    return clean_text(match.group(1)) if match else ""


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
    description: str = "",
    evidence: dict[str, object] | None = None,
) -> RawVacancy:
    return RawVacancy(
        source_id=source_id,
        source_url=source_url,
        source_record_id=record_id,
        organization_raw=clean_text(organization),
        title_raw=clean_text(title),
        location_raw=clean_text(location),
        closing_date_raw=clean_text(deadline),
        closing_time_raw=clean_text(closing_time),
        contract_raw=clean_text(contract),
        work_pattern_raw=clean_text(work_pattern),
        salary_raw=clean_text(salary),
        apply_url_raw=apply_url,
        reference_raw=clean_text(reference or record_id),
        description_raw=clean_text(description),
        retrieved_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        evidence=evidence or {},
    )


def dedupe_raw(records: Iterable[RawVacancy]) -> list[RawVacancy]:
    seen: set[str] = set()
    output: list[RawVacancy] = []
    for record in records:
        key = record.source_record_id or record.reference_raw or record.apply_url_raw or f"{record.title_raw}|{record.location_raw}|{record.closing_date_raw}"
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output
