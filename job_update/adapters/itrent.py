"""Reusable MHR iTrent adapter for the four council views."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..html_tools import clean_text, extract_links, first_attr
from ..models import RunContext, SourceResult, SourceStatus, SourceSpec
from .base import BaseAdapter, blocked_result
from .common import (
    extract_deadline,
    first_link,
    first_title,
    labelled_value,
    make_raw,
    parse_date_text,
    parse_reported_total,
    parse_time_text,
    source_record_id,
)


def _detail_url(source_url: str, record_id: str) -> str:
    """Build the public profile route used by the iTrent search client."""

    parts = urlsplit(source_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.pop("VACANCY_ID", None)
    params["VACANCY_ID"] = record_id
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def parse_itrent_html(html: str, spec: SourceSpec, source_url: str) -> tuple[int | None, list]:
    total = parse_reported_total(
        html,
        (
            r"([\d,]+)\s+jobs?\s+match(?:es)?",
            r"results?\s*[-:]?\s*([\d,]+)\s+matches?\s+found",
            r"([\d,]+)\s+matches?\s+found",
            r"showing\s+\d+\s+to\s+\d+\s+of\s+([\d,]+)",
            r"([\d,]+)\s+(?:jobs?|vacancies?|results?)\s+(?:found|available|matching)",
        ),
    )
    from .common import candidate_blocks

    blocks = candidate_blocks(html)
    identified_blocks = [
        (attrs, body)
        for attrs, body in blocks
        if first_attr(attrs, ("vac-id", "data-vac-id", "data-vacancy-id"))
    ]
    if identified_blocks:
        blocks = identified_blocks
    records = []
    seen: set[str] = set()
    organization = str(spec.configuration.get("organization", spec.display_name))
    default_location = str(spec.configuration.get("location_default", ""))
    for attrs, body in blocks:
        record_id = source_record_id(attrs, body, source_url)
        title = first_title(body)
        if not title:
            title = first_attr(attrs, ("data-title", "aria-label"))
        if not title or (record_id and record_id in seen):
            continue
        seen.add(record_id or title)
        text = clean_text(body)
        deadline, closing_time = extract_deadline(text)
        if not deadline:
            deadline = parse_date_text(first_attr(attrs, ("data-closing-date", "data-close-date")))
        if not closing_time:
            closing_time = parse_time_text(first_attr(attrs, ("data-closing-time",)))
        location = first_attr(attrs, ("data-location", "data-site")) or labelled_value(text, ("Location", "Based at", "Site")) or default_location
        apply_url = first_link(body, source_url) or source_url
        if not apply_url.startswith(("http://", "https://")):
            apply_url = _detail_url(source_url, record_id) if record_id else source_url
        reference = first_attr(attrs, ("data-reference", "data-job-reference")) or record_id
        records.append(
            make_raw(
                source_id=spec.source_id,
                source_url=source_url,
                record_id=record_id or reference,
                title=title,
                organization=organization,
                location=location,
                deadline=deadline,
                closing_time=closing_time,
                contract=labelled_value(text, ("Contract", "Contract type")),
                work_pattern=labelled_value(text, ("Hours", "Working pattern", "Work pattern")),
                salary=labelled_value(text, ("Salary", "Pay")),
                apply_url=apply_url,
                reference=reference,
                description=text,
                evidence={"itrent_wvid": spec.configuration.get("wvid", "")},
            )
        )
    return total, records


class ITrentAdapter(BaseAdapter):
    def fetch(self, context: RunContext) -> SourceResult:
        config = self.spec.configuration
        url = str(config.get("portal_url") or self.spec.official_entry_url)
        response = context.http_client.get(url, use_cache=False)
        method = "direct-http"
        warnings: list[str] = []
        errors: list[str] = []
        dynamic_page = self._needs_browser(response.text, response.status_code)
        if dynamic_page and context.allow_browser:
            browser_response = context.browser.render(
                url,
                wait_for=".Mhr-jobDetail",
                wait_ms=2_500,
                capture_urls=True,
                load_more_selector=str(config.get("browser_load_more_selector", ".Mhr-jobSearchMoreResultsButton")),
            )
            if browser_response.ok:
                html = browser_response.html
                source_url = browser_response.url or url
                method = "playwright-chromium-load-more"
            else:
                return blocked_result(self.spec, browser_response.error or response.error or "iTrent page was blocked", source_url=url)
        elif response.ok:
            html = response.text
            source_url = response.url or url
        else:
            return blocked_result(self.spec, response.error or f"iTrent request failed ({response.status_code})", source_url=url)

        # When the official council entry point is used, discover the current
        # webitrent WVID route before parsing the page.
        if "webitrent" not in source_url.lower():
            discovered = [link for _label, link in extract_links(html, source_url) if "webitrent" in link.lower()]
            if discovered:
                source_url = discovered[0]
                response = context.http_client.get(source_url, use_cache=False)
                if response.ok:
                    html = response.text
                elif context.allow_browser:
                    browser_response = context.browser.render(source_url, wait_ms=2_500)
                    if browser_response.ok:
                        html = browser_response.html
                        method = "playwright-chromium"
                    else:
                        warnings.append("official entry linked to iTrent but the linked board could not be rendered")
                else:
                    warnings.append("official entry linked to iTrent but the linked board could not be fetched")

        total, records = parse_itrent_html(html, self.spec, source_url)
        seen_urls = {source_url}
        next_url = self._next_url(html, source_url)
        while next_url and next_url not in seen_urls and (total is None or len(records) < total):
            seen_urls.add(next_url)
            response = context.http_client.get(next_url, use_cache=False)
            if not response.ok:
                warnings.append(f"pagination page failed: {next_url}")
                break
            page_total, page_records = parse_itrent_html(response.text, self.spec, next_url)
            total = total if total is not None else page_total
            records.extend(page_records)
            next_url = self._next_url(response.text, next_url)
        records = self._unique(records)
        detail_failures = self._enrich_details(records, context)
        if detail_failures:
            warnings.append(f"{detail_failures} iTrent job profile pages could not be verified")
        if total is not None and len(records) < total:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append(f"captured {len(records)} iTrent vacancies against reported total {total}")
        elif detail_failures:
            status = SourceStatus.PARTIALLY_VERIFIED
        elif total is None:
            status = SourceStatus.COMPLETE_WITH_FALLBACK if method != "direct-http" else SourceStatus.PARTIALLY_VERIFIED
            if total is None:
                warnings.append("iTrent page did not expose a reported result count")
        else:
            status = SourceStatus.COMPLETE_WITH_FALLBACK if method != "direct-http" else SourceStatus.COMPLETE
        return self.result(
            method=method,
            raw=records,
            source_total=total,
            status=status,
            warnings=warnings,
            errors=errors,
            source_url=source_url,
            verification_method="primary-platform-listing",
        )

    @staticmethod
    def _needs_browser(text: str, status_code: int | None) -> bool:
        marker = f"{text}\n{clean_text(text)}".lower()
        return status_code in {401, 403, 429} or "access denied" in marker or "enable javascript" in marker or "quick check" in marker or "mhr_webrec_job_search" in marker or "show more results" in marker

    @staticmethod
    def _enrich_details(records: list, context: RunContext) -> int:
        failures = 0
        for record in records:
            if not record.apply_url_raw or record.apply_url_raw == record.source_url:
                continue
            response = context.http_client.get(record.apply_url_raw, use_cache=False)
            html = response.text if response.ok and "job profile" in clean_text(response.text).casefold() else ""
            if not html and context.allow_browser:
                rendered = context.browser.render(record.apply_url_raw, wait_ms=1_000)
                if rendered.ok:
                    html = rendered.html
                    record.evidence["detail_retrieval_method"] = "playwright-chromium"
            if not html:
                if record.closing_date_raw:
                    continue
                failures += 1
                record.evidence["detail_fetch_error"] = response.error or f"HTTP {response.status_code}"
                continue
            text = clean_text(html)
            deadline, closing_time = extract_deadline(text)
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            location_matches = re.findall(r"location_on\s+(.+?)(?=\s+\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b)", text, re.I)
            location = clean_text(location_matches[-1]) if location_matches else ITrentAdapter._labelled_detail(text, ("Location",))
            if location:
                record.location_raw = location
            salary = ITrentAdapter._labelled_detail(text, ("Salary",))
            if salary:
                record.salary_raw = salary
            contract = ITrentAdapter._labelled_detail(text, ("Basis", "Contractual hours"))
            if contract:
                record.contract_raw = contract
            reference_match = re.search(r"Job reference\s+(.+?)(?=\s+Attachments\b|\s+Job description\b|$)", text, re.I)
            reference = clean_text(reference_match.group(1)) if reference_match else ITrentAdapter._labelled_detail(text, ("Job reference", "Job Reference"))
            if reference:
                record.reference_raw = reference
            title_match = re.search(r"job profile for\s+(.+?)(?:\s+chevron_left|\s+Back to job search|$)", text, re.I)
            if title_match:
                record.title_raw = clean_text(title_match.group(1))
            record.description_raw = f"{record.description_raw} {text}".strip()
            record.evidence["detail_verified"] = True
        return failures

    @staticmethod
    def _labelled_detail(text: str, labels: tuple[str, ...]) -> str:
        pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{pattern})\s*[:\-]?\s*(.+?)(?=\s+(?:Salary|Contractual hours|Basis|Region|Package|Local Government|Job category/type|Date posted|Job reference|Closing date|Interview date|Job description)\b|$)", text, re.I)
        return clean_text(match.group(1)) if match else ""

    @staticmethod
    def _next_url(html: str, base_url: str) -> str:
        for label, url in extract_links(html, base_url):
            if re.search(r"next|more|page\s*2", label, re.I):
                return url
        return ""

    @staticmethod
    def _unique(records: list) -> list:
        seen: set[str] = set()
        unique = []
        for record in records:
            key = record.source_record_id or record.reference_raw or record.apply_url_raw
            if key in seen:
                continue
            seen.add(key)
            unique.append(record)
        return unique
