"""Employer-specific NHS recruitment search adapter."""

from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit

from ..html_tools import clean_text, element_text_by_id, extract_links, first_attr, labelled_html_value
from ..models import RunContext, SourceStatus
from .base import BaseAdapter, blocked_result
from .common import extract_deadline, first_link, first_title, labelled_value, make_raw, parse_reported_total, source_record_id


class NHSAdapter(BaseAdapter):
    def fetch(self, context: RunContext):
        config = self.spec.configuration
        entry_url = self.spec.official_entry_url
        entry = context.http_client.get(entry_url, use_cache=False)
        warnings: list[str] = []
        if not entry.ok:
            warnings.append("official trust entry page was unavailable; underlying NHS search was attempted")

        search_url = str(config.get("search_url", ""))
        if not search_url:
            return blocked_result(self.spec, "NHS source has no configured recruitment search route", source_url=entry_url)
        query = str(config.get("query", ""))
        search_params = config.get("search_params", {})
        if not isinstance(search_params, dict):
            search_params = {}
        first_url = self._page_url(search_url, query, 1, search_params)
        response = context.http_client.get(first_url, use_cache=False)
        method = "direct-http"
        if (not response.ok or self._needs_browser(response.text, response.status_code)) and context.allow_browser:
            rendered = context.browser.render(first_url, wait_ms=2_000)
            if rendered.ok:
                html = rendered.html
                current_url = rendered.url or first_url
                method = "playwright-chromium"
            else:
                return blocked_result(self.spec, rendered.error or response.error or "NHS recruitment search could not be fetched", source_url=first_url)
        elif response.ok:
            html = response.text
            current_url = response.url or first_url
        else:
            return blocked_result(self.spec, response.error or f"NHS recruitment search failed ({response.status_code})", source_url=first_url)

        total = self._reported_total(html)
        records = self._parse(html, current_url, config)
        seen_pages = {current_url}
        page_number = 2
        next_url = self._next_url(html, current_url)
        while (next_url or (total is not None and len(self._unique(records)) < total)) and page_number <= 100:
            next_url = next_url or self._page_url(search_url, query, page_number, search_params)
            if next_url in seen_pages:
                break
            seen_pages.add(next_url)
            page = context.http_client.get(next_url, use_cache=False)
            if not page.ok:
                warnings.append(f"NHS pagination page failed: {next_url}")
                break
            page_total = self._reported_total(page.text)
            total = total if total is not None else page_total
            records.extend(self._parse(page.text, page.url or next_url, config))
            page_next = self._next_url(page.text, page.url or next_url)
            next_url = page_next
            page_number += 1
            if not page_next and (total is None or len(self._unique(records)) >= total):
                break
        records = self._unique(records)
        detail_failures = self._enrich_details(records, context, config)
        if detail_failures:
            warnings.append(f"{detail_failures} NHS advert detail pages could not be verified")
        marker = clean_text(html).lower()
        no_results = "no results" in marker or "no jobs found" in marker or "0 jobs" in marker
        if detail_failures:
            status = SourceStatus.PARTIALLY_VERIFIED
        elif total is not None and len(records) < total:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append(f"captured {len(records)} unique NHS adverts against reported total {total}")
        elif total is None and not records and not no_results:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append("NHS recruitment page did not expose a result count or parseable rows")
        else:
            status = SourceStatus.COMPLETE_WITH_FALLBACK if method != "direct-http" else SourceStatus.COMPLETE
        return self.result(
            method=method,
            raw=records,
            source_total=total,
            status=status,
            warnings=warnings,
            source_url=current_url,
            verification_method="direct-primary-advert" if records else "primary-platform-listing",
        )

    @staticmethod
    def _page_url(base_url: str, query: str, page: int, search_params: dict | None = None) -> str:
        parts = urlsplit(base_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        if query and not search_params:
            params["keyword"] = query
        for key, value in (search_params or {}).items():
            if value is not None and str(value) != "":
                params[str(key)] = str(value)
        if page > 1:
            params["page"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))

    @staticmethod
    def _reported_total(html: str) -> int | None:
        return parse_reported_total(
            html,
            (r"([\d,]+)\s+(?:jobs?|results?|vacancies?)\s+(?:found|matching|available)", r"showing\s+\d+\s+to\s+\d+\s+of\s+([\d,]+)", r"([\d,]+)\s+results?"),
        )

    def _parse(self, html: str, source_url: str, config: dict):
        records = []
        default_org = str(config.get("employer", self.spec.display_name))
        expected_employer = default_org.casefold()
        seen: set[str] = set()
        blocks = self._result_blocks(html)
        if not blocks:
            from .common import candidate_blocks

            blocks = candidate_blocks(html)
        for attrs, body in blocks:
            title = first_title(body)
            if not title:
                continue
            record_id = source_record_id(attrs, body, source_url)
            key = record_id or first_link(body, source_url) or title
            if key in seen:
                continue
            seen.add(key)
            text = clean_text(body)
            if re.search(r"jobs?\s+found\s+for|search\s+filters?", title, re.I):
                continue
            employer = self._card_employer(body) or labelled_value(text, ("Employer", "Organisation", "Trust")) or default_org
            location = first_attr(attrs, ("data-location",)) or self._card_location(body) or labelled_value(text, ("Location", "Base", "Site")) or self._infer_location(text)
            deadline, closing_time = extract_deadline(text)
            reference = first_attr(attrs, ("data-job-reference", "data-reference")) or record_id
            records.append(
                make_raw(
                    source_id=self.spec.source_id,
                    source_url=source_url,
                    record_id=record_id or reference,
                    title=title,
                    organization=employer,
                    location=location,
                    deadline=deadline,
                    closing_time=closing_time,
                    contract=labelled_value(text, ("Contract", "Employment type")),
                    work_pattern=labelled_value(text, ("Hours", "Working pattern")),
                    salary=labelled_value(text, ("Salary", "Pay")),
                    apply_url=first_link(body, source_url) or source_url,
                    reference=reference,
                    description=text,
                    evidence={
                        "configured_employer": default_org,
                        "employer_mismatch": bool(expected_employer and expected_employer not in text.casefold()),
                    },
                )
            )
        return records

    @staticmethod
    def _result_blocks(html: str) -> list[tuple[str, str]]:
        """Return only NHS search-result list items, not their field divs."""

        pattern = re.compile(
            r"<li\b(?P<attrs>[^>]*\bdata-test\s*=\s*['\"]search-result['\"][^>]*)>"
            r"(?P<body>.*?)</li>",
            re.I | re.S,
        )
        return [(match.group("attrs"), match.group("body")) for match in pattern.finditer(html or "")]

    @staticmethod
    def _card_employer(body: str) -> str:
        match = re.search(
            r"data-test\s*=\s*['\"]search-result-location['\"][^>]*>.*?<h3\b[^>]*>(?P<employer>.*?)<div\b[^>]*class\s*=\s*['\"][^'\"]*location-font-size[^'\"]*['\"]",
            body,
            re.I | re.S,
        )
        return clean_text(match.group("employer")) if match else ""

    @staticmethod
    def _card_location(body: str) -> str:
        match = re.search(
            r"class\s*=\s*['\"][^'\"]*location-font-size[^'\"]*['\"][^>]*>(?P<location>.*?)</div>",
            body,
            re.I | re.S,
        )
        return clean_text(match.group("location")) if match else ""

    @staticmethod
    def _infer_location(text: str) -> str:
        lowered = text.casefold()
        for place in (
                "Nottinghamshire",
                "Nottingham",
            "Mansfield",
            "Sutton-in-Ashfield",
            "Newark",
            "Worksop",
            "Retford",
            "Southwell",
            "West Bridgford",
        ):
            if place.casefold() in lowered:
                return place
        return ""

    @staticmethod
    def _employer_matches(expected: str, actual: str) -> bool:
        expected_text = " ".join(expected.casefold().split())
        actual_text = " ".join(actual.casefold().split())
        return bool(expected_text and actual_text and (expected_text in actual_text or actual_text in expected_text))

    def _enrich_details(self, records: list, context: RunContext, config: dict) -> int:
        failures = 0
        expected = str(config.get("employer", self.spec.display_name))
        for record in records:
            if not record.apply_url_raw or record.apply_url_raw == record.source_url:
                continue
            response = context.http_client.get(record.apply_url_raw, use_cache=False)
            if not response.ok:
                failures += 1
                record.evidence["detail_fetch_error"] = response.error or f"HTTP {response.status_code}"
                continue
            html = response.text
            text = clean_text(html)
            closing = element_text_by_id(html, "closing_date")
            deadline, closing_time = extract_deadline(closing or text)
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            employer = element_text_by_id(html, "employer_name")
            if employer:
                record.organization_raw = employer
                record.evidence["employer_verified"] = self._employer_matches(expected, employer)
            location_parts = [
                element_text_by_id(html, element_id)
                for element_id in (
                    "employer_address_line_1",
                    "employer_address_line_2",
                    "employer_town",
                    "employer_county",
                    "employer_postcode",
                    "employer_country",
                )
            ]
            location = " ".join(part for part in location_parts if part).strip()
            if not location:
                location = labelled_html_value(html, ("Job locations", "Location"))
            if location:
                record.location_raw = location
            record.salary_raw = record.salary_raw or element_text_by_id(html, "range_salary")
            record.contract_raw = record.contract_raw or element_text_by_id(html, "contract_type")
            record.work_pattern_raw = record.work_pattern_raw or labelled_html_value(html, ("Working pattern",))
            reference = element_text_by_id(html, "trac-job-reference")
            if reference:
                record.reference_raw = reference
            lowered = text.casefold()
            record.evidence["withdrawn"] = "vacancy withdrawn" in lowered or "no longer accepting applications" in lowered
            record.description_raw = f"{record.description_raw} {text}".strip()
        return failures

    @staticmethod
    def _needs_browser(text: str, status_code: int | None) -> bool:
        marker = clean_text(text).lower()
        return status_code in {401, 403, 429} or "please wait, loading" in marker or "enable javascript" in marker

    @staticmethod
    def _next_url(html: str, base_url: str) -> str:
        for label, url in extract_links(html, base_url):
            if re.search(r"\bnext\b", label, re.I) and "/candidate/search/results" in url:
                return url
        return ""

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
