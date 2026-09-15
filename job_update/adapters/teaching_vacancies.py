"""Complete pagination adapter for GOV.UK Teaching Vacancies searches."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..html_tools import clean_text, extract_links, first_attr
from ..models import RunContext, SourceStatus
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


class TeachingVacanciesAdapter(BaseAdapter):
    def fetch(self, context: RunContext):
        queries = [str(value) for value in self.spec.configuration.get("queries", [self.spec.official_entry_url])]
        page_param = str(self.spec.configuration.get("page_param", "page"))
        records = []
        reported: dict[str, int] = {}
        warnings: list[str] = []
        query_complete: dict[str, bool] = {}
        for query in queries:
            first_url = self._page_url(query, page_param, 1)
            response = context.http_client.get(first_url, use_cache=True)
            if not response.ok:
                warnings.append(f"Teaching Vacancies query failed: {query}")
                query_complete[query] = False
                continue
            current_url = response.url or first_url
            query_total = parse_reported_total(response.text, (r"([\d,]+)\s+jobs?", r"([\d,]+)\s+results?", r"of\s+([\d,]+)"))
            if query_total is not None:
                reported[query] = query_total
            query_records = self._parse(response.text, current_url, query)
            pages_seen = {current_url}
            page_number = 2
            next_url = self._next_url(response.text, current_url)
            while (next_url or (query_total is not None and len(self._unique(query_records)) < query_total)) and page_number <= 200:
                next_url = next_url or self._page_url(query, page_param, page_number)
                if next_url in pages_seen:
                    break
                pages_seen.add(next_url)
                page = context.http_client.get(next_url, use_cache=True)
                if not page.ok:
                    warnings.append(f"Teaching Vacancies pagination failed: {next_url}")
                    break
                if query_total is None:
                    query_total = parse_reported_total(page.text, (r"([\d,]+)\s+jobs?", r"([\d,]+)\s+results?", r"of\s+([\d,]+)"))
                    if query_total is not None:
                        reported[query] = query_total
                query_records.extend(self._parse(page.text, page.url or next_url, query))
                next_url = self._next_url(page.text, page.url or next_url)
                page_number += 1
            query_records = self._unique(query_records)
            records.extend(query_records)
            query_complete[query] = query_total is not None and len(query_records) >= query_total or query_total == 0
            if query_total is None:
                warnings.append(f"Teaching Vacancies query did not expose a reported total: {query}")
                query_complete[query] = bool(query_records)
            elif len(query_records) < query_total:
                warnings.append(f"captured {len(query_records)} Teaching Vacancies records against {query_total} for {query}")
        records = self._unique(records)
        detail_failures = self._enrich_details(records, context)
        if detail_failures:
            warnings.append(f"{detail_failures} Teaching Vacancies detail pages could not be verified")
        if not queries or any(not query_complete.get(query, False) for query in queries):
            status = SourceStatus.PARTIALLY_VERIFIED
        else:
            status = SourceStatus.COMPLETE
        if detail_failures:
            status = SourceStatus.PARTIALLY_VERIFIED
        if not records and not reported:
            status = SourceStatus.BLOCKED
            warnings.append("Teaching Vacancies returned no parseable result set")
        return self.result(
            method="direct-http",
            raw=records,
            source_total=(next(iter(reported.values())) if len(reported) == 1 else None),
            reported_totals=reported,
            status=status,
            warnings=warnings + (["reported query totals overlap; query controls are retained separately and source_total is null"] if len(reported) > 1 else []),
            source_url=self.spec.official_entry_url,
            verification_method="direct-primary-advert" if records else "primary-platform-listing",
        )

    def _parse(self, html: str, source_url: str, query: str):
        records = []
        seen: set[str] = set()
        from .common import candidate_blocks

        for attrs, body in candidate_blocks(html):
                title = first_title(body)
                if not title:
                    continue
                record_id = source_record_id(attrs, body, source_url)
                apply_url = first_link(body, source_url) or source_url
                key = record_id or apply_url or title
                if key in seen:
                    continue
                seen.add(key)
                text = clean_text(body)
                if title.casefold() in {"sorted by distance", "search results", "filter results"}:
                    continue
                employer = labelled_value(text, ("School", "Employer", "Academy", "Trust")) or TeachingVacanciesAdapter._infer_employer(text)
                location = first_attr(attrs, ("data-address", "data-location", "data-school-address")) or labelled_value(text, ("Address", "Location", "School address")) or TeachingVacanciesAdapter._infer_location(text)
                deadline, closing_time = extract_deadline(text)
                public_reference = first_attr(attrs, ("data-job-id", "data-reference", "data-vacancy-id", "data-job-reference"))
                records.append(
                    make_raw(
                        source_id=self.spec.source_id,
                        source_url=source_url,
                        record_id=record_id,
                        title=title,
                        organization=employer,
                        location=location,
                        deadline=deadline,
                        closing_time=closing_time,
                        contract=labelled_value(text, ("Contract", "Contract type")),
                        work_pattern=labelled_value(text, ("Working pattern", "Hours")),
                        salary=labelled_value(text, ("Salary", "Pay")),
                        apply_url=apply_url,
                        reference=public_reference,
                        description=text,
                        evidence={"query": query, "detail_required": True},
                    )
                )
        return records

    @staticmethod
    def _infer_location(text: str) -> str:
        for value in (
            "Nottinghamshire",
            "Nottingham",
            "Derbyshire",
            "Derby",
            "Leicestershire",
            "Leicester",
            "Lincolnshire",
            "Lincoln",
            "South Yorkshire",
        ):
            if value.casefold() in text.casefold():
                return value
        return ""

    @staticmethod
    def _infer_employer(text: str) -> str:
        match = re.search(
            r"(?:school|academy|college|trust)\s*[:\-]?\s*([^|;]+?)(?:\s+address|\s+location|\s+closing|$)",
            text,
            re.I,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _job_posting(html: str) -> dict:
        """Read the service's structured JobPosting detail payload.

        Teaching Vacancies detail pages contain a JSON-LD JobPosting object
        alongside navigation, similar-job cards and footer content. The
        structured object is the authoritative detail boundary; parsing the
        whole page as one text blob causes those unrelated sections to leak
        into employer and location fields.
        """

        pattern = re.compile(
            r"<script\b[^>]*type\s*=\s*['\"]application/ld\+json['\"][^>]*>(?P<body>.*?)</script>",
            re.I | re.S,
        )
        for match in pattern.finditer(html or ""):
            try:
                payload = json.loads(match.group("body"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            expanded: list[dict] = []
            for candidate in candidates:
                if isinstance(candidate, dict) and isinstance(candidate.get("@graph"), list):
                    expanded.extend(item for item in candidate["@graph"] if isinstance(item, dict))
                elif isinstance(candidate, dict):
                    expanded.append(candidate)
            for candidate in expanded:
                if candidate.get("@type") == "JobPosting":
                    return candidate
        return {}

    @staticmethod
    def _posting_employer(posting: dict) -> str:
        organisation = posting.get("hiringOrganization")
        if isinstance(organisation, list):
            organisation = organisation[0] if organisation else {}
        return clean_text(str(organisation.get("name", ""))) if isinstance(organisation, dict) else ""

    @staticmethod
    def _posting_location(posting: dict) -> str:
        location = posting.get("jobLocation")
        if isinstance(location, list):
            location = location[0] if location else {}
        if not isinstance(location, dict):
            return ""
        address = location.get("address", location)
        if isinstance(address, list):
            address = address[0] if address else {}
        if not isinstance(address, dict):
            return ""
        parts = [
            str(address.get("streetAddress", "")),
            str(address.get("addressLocality", "")),
            str(address.get("postalCode", "")),
        ]
        return clean_text(", ".join(part for part in parts if part and part != "None"))

    @staticmethod
    def _posting_salary(posting: dict) -> str:
        salary = posting.get("baseSalary")
        if not isinstance(salary, dict):
            return ""
        value = salary.get("value")
        if isinstance(value, dict):
            value = value.get("value", "")
        return clean_text(str(value or ""))

    @staticmethod
    def _enrich_details(records: list, context: RunContext) -> int:
        failures = 0
        for record in records:
            if not record.apply_url_raw or record.apply_url_raw == record.source_url:
                failures += 1
                record.evidence["detail_fetch_error"] = "detail URL was not exposed by the search result"
                continue
            response = context.http_client.get(record.apply_url_raw, use_cache=True)
            html = response.text if response.ok else ""
            if not html and context.allow_browser:
                rendered = context.browser.render(record.apply_url_raw, wait_ms=500, timeout_ms=10_000)
                if rendered.ok and rendered.status_code not in {401, 403, 404, 429}:
                    html = rendered.html
                    record.evidence["detail_retrieval_method"] = "playwright-chromium-fallback"
            if not html:
                record.evidence["detail_fetch_error"] = response.error or f"HTTP {response.status_code}"
                failures += 1
                continue
            text = clean_text(html)
            posting = TeachingVacanciesAdapter._job_posting(html)
            deadline, closing_time = extract_deadline(text)
            structured_deadline = parse_date_text(str(posting.get("validThrough", ""))) if posting else ""
            structured_time = parse_time_text(str(posting.get("validThrough", ""))) if posting else ""
            if structured_deadline:
                deadline = structured_deadline
            if structured_time:
                closing_time = structured_time
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            detail_location = TeachingVacanciesAdapter._posting_location(posting) or labelled_value(text, ("School address", "Address", "Location", "Based at")) or TeachingVacanciesAdapter._infer_location(text)
            if detail_location:
                record.location_raw = detail_location
            detail_employer = TeachingVacanciesAdapter._posting_employer(posting) or labelled_value(text, ("School", "Employer", "Academy", "Trust")) or TeachingVacanciesAdapter._infer_employer(text)
            if detail_employer:
                record.organization_raw = detail_employer
                record.advertised_employer_raw = detail_employer
            host = TeachingVacanciesAdapter._posting_employer(posting) or labelled_value(text, ("School", "Academy", "Trust", "College"))
            if host and not TeachingVacanciesAdapter._is_independent(text):
                record.host_organization_raw = host
                record.host_association_verified = True
                record.host_association_type = "direct"
                record.host_association_evidence = "Teaching Vacancies detail identifies the public/state-funded school or trust"
            record.contract_raw = record.contract_raw or labelled_value(text, ("Contract", "Contract type"))
            record.work_pattern_raw = record.work_pattern_raw or labelled_value(text, ("Working pattern", "Hours"))
            record.salary_raw = record.salary_raw or TeachingVacanciesAdapter._posting_salary(posting) or labelled_value(text, ("Salary", "Pay"))
            lowered = text.casefold()
            record.evidence.update(
                {
                    "independent": TeachingVacanciesAdapter._is_independent(text),
                    "private": "private school" in lowered or "private academy" in lowered,
                    "agency": "recruitment agency" in lowered or "agency advert" in lowered or "agency" in lowered,
                    "generic_agency": bool("agency" in lowered and not record.host_association_verified),
                    "withdrawn": "vacancy withdrawn" in lowered or "no longer accepting applications" in lowered,
                    "detail_verified": True,
                    "external_apprenticeship": "apprenticeship" in lowered and any(term in lowered for term in ("student", "apply to study", "training opportunity")),
                }
            )
            structured_description = clean_text(str(posting.get("description", ""))) if posting else ""
            record.description_raw = f"{record.description_raw} {structured_description or text}".strip()
        return failures

    @staticmethod
    def _is_independent(text: str) -> bool:
        lowered = text.casefold()
        return "independent school" in lowered or "private school" in lowered or "independent academy" in lowered

    @staticmethod
    def _page_url(url: str, page_param: str, page: int) -> str:
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params[page_param] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))

    @staticmethod
    def _next_url(html: str, base_url: str) -> str:
        for label, url in extract_links(html, base_url):
            if re.search(r"next|older|more", label, re.I):
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
