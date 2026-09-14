"""Complete pagination adapter for GOV.UK Teaching Vacancies searches."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..html_tools import clean_text, extract_links, first_attr
from ..models import RunContext, SourceStatus
from .base import BaseAdapter, blocked_result
from .common import extract_deadline, first_link, first_title, labelled_value, make_raw, parse_reported_total, source_record_id


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
            response = context.http_client.get(first_url, use_cache=False)
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
                page = context.http_client.get(next_url, use_cache=False)
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
        self._enrich_details(records, context)
        if not queries or any(not query_complete.get(query, False) for query in queries):
            status = SourceStatus.PARTIALLY_VERIFIED
        else:
            status = SourceStatus.COMPLETE
        if not records and not reported:
            status = SourceStatus.BLOCKED
            warnings.append("Teaching Vacancies returned no parseable result set")
        return self.result(
            method="direct-http",
            raw=records,
            source_total=sum(reported.values()) if reported else None,
            reported_totals=reported,
            status=status,
            warnings=warnings + (["reported query totals overlap; source_total is the sum of query controls"] if len(reported) > 1 else []),
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
                reference = first_attr(attrs, ("data-job-id", "data-reference", "data-vacancy-id")) or record_id
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
                        contract=labelled_value(text, ("Contract", "Contract type")),
                        work_pattern=labelled_value(text, ("Working pattern", "Hours")),
                        salary=labelled_value(text, ("Salary", "Pay")),
                        apply_url=apply_url,
                        reference=reference,
                        description=text,
                        evidence={"query": query},
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
    def _enrich_details(records: list, context: RunContext) -> None:
        for record in records:
            if not record.apply_url_raw or record.apply_url_raw == record.source_url:
                continue
            response = context.http_client.get(record.apply_url_raw, use_cache=False)
            if not response.ok:
                record.evidence["detail_fetch_error"] = response.error or f"HTTP {response.status_code}"
                continue
            text = clean_text(response.text)
            deadline, closing_time = extract_deadline(text)
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            detail_location = labelled_value(text, ("School address", "Address", "Location", "Based at")) or TeachingVacanciesAdapter._infer_location(text)
            if detail_location:
                record.location_raw = detail_location
            detail_employer = labelled_value(text, ("School", "Employer", "Academy", "Trust")) or TeachingVacanciesAdapter._infer_employer(text)
            if detail_employer:
                record.organization_raw = detail_employer
            record.contract_raw = record.contract_raw or labelled_value(text, ("Contract", "Contract type"))
            record.work_pattern_raw = record.work_pattern_raw or labelled_value(text, ("Working pattern", "Hours"))
            record.salary_raw = record.salary_raw or labelled_value(text, ("Salary", "Pay"))
            lowered = text.casefold()
            record.evidence.update(
                {
                    "independent": "independent school" in lowered or "private school" in lowered,
                    "agency": "recruitment agency" in lowered or "agency advert" in lowered,
                    "withdrawn": "vacancy withdrawn" in lowered or "no longer accepting applications" in lowered,
                }
            )
            record.description_raw = f"{record.description_raw} {text}".strip()

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
