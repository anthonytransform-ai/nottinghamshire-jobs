"""Nottingham Trent University Jobtrain adapter.

The public NTU board renders its vacancy cards with JavaScript. The adapter
tries ordinary HTML first, then uses the shared browser boundary to load the
public cards, including the board's load-more control. Individual detail
pages are fetched directly so closing dates and other fields are not inferred
from card chrome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from ..html_tools import absolute_url, clean_text, element_text_by_id, first_attr, labelled_html_value
from ..models import RunContext, SourceStatus
from .base import BaseAdapter, blocked_result
from .common import (
    extract_deadline,
    labelled_value,
    make_raw,
    parse_date_text,
    parse_reported_total,
    source_record_id,
)


@dataclass
class _JobCard:
    attrs: str
    text_parts: list[str] = field(default_factory=list)
    links: list[tuple[str, str, str]] = field(default_factory=list)
    fields: dict[str, list[str]] = field(default_factory=dict)
    headings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.text_parts))

    def field(self, *names: str) -> str:
        for name in names:
            for key, values in self.fields.items():
                if name.casefold() in key.casefold():
                    value = clean_text(" ".join(values))
                    if value:
                        return value
        return ""


class _JobCardParser(HTMLParser):
    """Collect nested ``job-card`` divs without truncating child divs."""

    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_JobCard] = []
        self._card: _JobCard | None = None
        self._depth = 0
        self._tag_stack: list[str] = []
        self._field_stack: list[tuple[str, str]] = []
        self._link: dict[str, object] | None = None
        self._heading: list[str] | None = None

    @staticmethod
    def _attrs_text(attrs: list[tuple[str, str | None]]) -> str:
        return " ".join(f'{name}="{value or ""}"' for name, value in attrs)

    @staticmethod
    def _field_keys(attrs: list[tuple[str, str | None]]) -> list[str]:
        values = {name.casefold(): (value or "") for name, value in attrs}
        keys: list[str] = []
        testid = values.get("data-testid", "").strip()
        classes = values.get("class", "").split()
        if testid:
            keys.append(f"testid:{testid}")
        keys.extend(f"class:{item}" for item in classes if item)
        return keys

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.casefold()
        values = {name.casefold(): (value or "") for name, value in attrs}
        classes = values.get("class", "").casefold().split()
        if self._card is None and tag_lower in {"div", "article", "li"} and "job-card" in classes:
            self._card = _JobCard(self._attrs_text(attrs))
            self._depth = 1
            self._tag_stack = [tag_lower]
            self._field_stack = []
            self._link = None
            self._heading = None
            return
        if self._card is None:
            return

        if tag_lower not in self._void_tags:
            self._depth += 1
            self._tag_stack.append(tag_lower)
        for key in self._field_keys(attrs):
            self._field_stack.append((key, tag_lower))
            self._card.fields.setdefault(key, [])
        if tag_lower == "a":
            self._link = {"href": values.get("href", ""), "testid": values.get("data-testid", ""), "parts": []}
        if tag_lower in {"h1", "h2", "h3", "h4"}:
            self._heading = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in self._void_tags:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._card is None or not data:
            return
        self._card.text_parts.append(data)
        for key, _tag in self._field_stack:
            self._card.fields.setdefault(key, []).append(data)
        if self._link is not None:
            self._link.setdefault("parts", []).append(data)  # type: ignore[union-attr]
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        tag_lower = tag.casefold()
        if tag_lower == "a" and self._link is not None:
            link = self._link
            parts = link.get("parts", [])
            self._card.links.append((clean_text(" ".join(parts)), str(link.get("href", "")), str(link.get("testid", ""))))  # type: ignore[arg-type]
            self._link = None
        if tag_lower in {"h1", "h2", "h3", "h4"} and self._heading is not None:
            heading = clean_text(" ".join(self._heading))
            if heading:
                self._card.headings.append(heading)
            self._heading = None
        for index in range(len(self._field_stack) - 1, -1, -1):
            if self._field_stack[index][1] == tag_lower:
                del self._field_stack[index]
                break
        if tag_lower in self._tag_stack:
            for index in range(len(self._tag_stack) - 1, -1, -1):
                if self._tag_stack[index] == tag_lower:
                    del self._tag_stack[index:]
                    break
        if tag_lower not in self._void_tags:
            self._depth -= 1
        if self._depth <= 0:
            self.cards.append(self._card)
            self._card = None
            self._depth = 0
            self._tag_stack = []
            self._field_stack = []
            self._link = None
            self._heading = None


def _testid_value(html: str, testid: str) -> str:
    match = re.search(
        rf"<(?P<tag>[A-Za-z][\w:-]*)\b[^>]*\bdata-testid\s*=\s*['\"]{re.escape(testid)}['\"][^>]*>(?P<body>.*?)</(?P=tag)>",
        html or "",
        re.I | re.S,
    )
    return clean_text(match.group("body")) if match else ""


def _card_total(html: str) -> int | None:
    total = parse_reported_total(html, (r"there\s+are\s+([\d,]+)\s+jobs?\s+matching", r"([\d,]+)\s+jobs?\s+matching"))
    if total is not None:
        return total
    value = _testid_value(html, "showTotalMatchCount") or element_text_by_id(html, "showTotalMatchCount")
    match = re.search(r"\d[\d,]*", value)
    return int(match.group(0).replace(",", "")) if match else None


def _job_card_records(html: str, source_id: str, organization: str, source_url: str, default_location: str) -> list:
    parser = _JobCardParser()
    parser.feed(html or "")
    records = []
    seen: set[str] = set()
    for card in parser.cards:
        detail_link = next((absolute_url(source_url, href) for _label, href, testid in card.links if testid.casefold().startswith("a-job-detail") and href), "")
        if not detail_link:
            detail_link = next((absolute_url(source_url, href) for _label, href, _testid in card.links if re.search(r"/job/|jobdetail", href, re.I)), "")
        title = next((label for label, _href, testid in card.links if testid.casefold().startswith("a-job-detail") and label), "")
        if not title:
            title = card.field("testid:span-vacancies-title", "class:job-title", "class:title")
        if not title and card.headings:
            title = card.headings[0]
        record_id = source_record_id(card.attrs, card.text, source_url)
        key = record_id or detail_link or title
        if not key or not title or key in seen:
            continue
        seen.add(key)
        deadline, closing_time = extract_deadline(card.text)
        location = card.field("class:job-card__location", "testid:span-vacancies-loaction-name", "testid:span-vacancies-location")
        location = re.sub(r"\blocation_on\b", "", location, flags=re.I).strip() or default_location
        reference = card.field("class:jobreference", "testid:span-reference")
        reference_match = re.search(r"(?:job\s*)?(?:reference|ref)\s*[:#-]?\s*([A-Za-z0-9/_-]+)", reference or card.text, re.I)
        reference = reference_match.group(1) if reference_match else reference
        records.append(
            make_raw(
                source_id=source_id,
                source_url=source_url,
                record_id=record_id,
                title=title,
                organization=organization,
                location=location,
                deadline=deadline,
                closing_time=closing_time,
                contract=card.field("class:employmenttype", "testid:span-vacancies-employment-type") or labelled_value(card.text, ("Employment type", "Contract")),
                work_pattern=labelled_value(card.text, ("Hours", "Working pattern")),
                salary=card.field("class:salary") or labelled_value(card.text, ("Salary", "Pay")),
                apply_url=detail_link or source_url,
                reference=reference,
                description=card.text,
                evidence={"jobtrain": True, "dynamic_card": True, "detail_required": True},
            )
        )
    return records


def parse_jobtrain_html(html: str, source_id: str, organization: str, source_url: str, default_location: str = "") -> tuple[int | None, list]:
    return _card_total(html), _job_card_records(html, source_id, organization, source_url, default_location)


class NTUJobtrainAdapter(BaseAdapter):
    def fetch(self, context: RunContext):
        config = self.spec.configuration
        url = self.spec.official_entry_url
        response = context.http_client.get(url, use_cache=True)
        method = "direct-http"
        warnings: list[str] = []
        organization = str(config.get("organization", "Nottingham Trent University"))
        default_location = str(config.get("location_default", "")) if config.get("location_default_verified", False) else ""
        if response.ok:
            source_url = response.url or url
            total, records = parse_jobtrain_html(response.text, self.spec.source_id, organization, source_url, default_location)
        else:
            source_url = url
            total, records = None, []

        dynamic = clean_text(response.text).casefold() if response.ok else ""
        needs_browser = not response.ok or not records or (total is not None and total > len(records)) or (total is None and any(marker in dynamic for marker in ("load more", "_jobcard", "javascript")))
        if needs_browser and context.allow_browser:
            rendered = context.browser.render(
                url,
                wait_for=str(config.get("browser_wait_for", ".job-card")),
                wait_ms=int(config.get("browser_wait_ms", 3_000)),
                capture_urls=True,
                load_more_selector=str(config.get("browser_load_more_selector", "")) or None,
            )
            if rendered.ok:
                source_url = rendered.url or url
                browser_total, browser_records = parse_jobtrain_html(rendered.html, self.spec.source_id, organization, source_url, default_location)
                total = browser_total if browser_total is not None else total
                records = browser_records
                method = "playwright-chromium"
                if rendered.captured_urls:
                    warnings.append(f"captured {len(rendered.captured_urls)} browser response URLs while inspecting Jobtrain")
            elif not response.ok:
                return blocked_result(self.spec, rendered.error or response.error or "Jobtrain portal could not be fetched", source_url=url)
            else:
                warnings.append(rendered.error or "Jobtrain browser fallback did not render vacancy cards")

        records = self._unique(records)
        detail_failures = self._enrich_details(records, context)
        if detail_failures:
            warnings.append(f"{detail_failures} NTU Jobtrain detail pages could not be verified")
        if total is not None and len(records) < total:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append(f"captured {len(records)} distinct Jobtrain references against reported total {total}")
        elif detail_failures:
            status = SourceStatus.PARTIALLY_VERIFIED
        elif total is None and not records:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append("Jobtrain portal did not expose a stable reported total or parseable vacancy cards")
        elif method != "direct-http":
            status = SourceStatus.COMPLETE_WITH_FALLBACK
        else:
            status = SourceStatus.COMPLETE
        return self.result(
            method=method,
            raw=records,
            source_total=total,
            status=status,
            warnings=warnings,
            errors=[response.error] if not response.ok and response.error else [],
            source_url=source_url,
            verification_method="direct-primary-advert" if records else "primary-platform-listing",
        )

    @staticmethod
    def _enrich_details(records: list, context: RunContext) -> int:
        failures = 0
        for record in records:
            if not record.apply_url_raw or record.apply_url_raw == record.source_url:
                if record.evidence.get("detail_required"):
                    failures += 1
                    record.evidence["detail_fetch_error"] = "detail URL was not exposed by the search result"
                continue
            response = context.http_client.get(record.apply_url_raw, use_cache=True)
            if not response.ok:
                failures += 1
                record.evidence["detail_fetch_error"] = response.error or f"HTTP {response.status_code}"
                continue
            html = response.text
            text = clean_text(html)
            closing = _testid_value(html, "strong-jt7-vacancies-close-date-external") or labelled_html_value(html, ("Closing Date", "Closing date"))
            deadline = parse_date_text(closing)
            if not deadline:
                deadline, closing_time = extract_deadline(f"Closing Date: {closing or text}")
            else:
                _unused, closing_time = extract_deadline(f"Closing Date: {closing}")
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            location = _testid_value(html, "span-vacancies-loaction-name") or _testid_value(html, "span-vacancies-location")
            if location:
                record.location_raw = location
            contract = _testid_value(html, "span-vacancies-employment-type")
            if contract:
                record.contract_raw = contract
            reference = _testid_value(html, "span-reference")
            if reference:
                record.reference_raw = reference
            salary = _testid_value(html, "span-vacancies-salary") or labelled_html_value(html, ("Salary", "Salary band"))
            if salary:
                record.salary_raw = salary
            record.description_raw = f"{record.description_raw} {text}".strip()
            record.evidence["detail_verified"] = True
        return failures

    @staticmethod
    def _unique(records: list) -> list:
        output = []
        seen: set[str] = set()
        for record in records:
            key = record.reference_raw or record.source_record_id or record.apply_url_raw
            if key in seen:
                continue
            seen.add(key)
            output.append(record)
        return output
