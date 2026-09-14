"""University of Nottingham current opportunities adapter."""

from __future__ import annotations

import re

from ..html_tools import absolute_url, clean_text, extract_links, first_attr, labelled_html_value
from ..models import RunContext, SourceStatus
from .base import BaseAdapter, blocked_result
from .common import extract_deadline, first_link, first_title, labelled_value, make_raw, parse_reported_total, source_record_id


class UniversityNottinghamAdapter(BaseAdapter):
    def fetch(self, context: RunContext):
        url = self.spec.official_entry_url
        response = context.http_client.get(url, use_cache=False)
        method = "direct-http"
        if not response.ok and context.allow_browser:
            rendered = context.browser.render(url, wait_ms=2_000)
            if rendered.ok:
                html = rendered.html
                source_url = rendered.url or url
                method = "playwright-chromium"
            else:
                return blocked_result(self.spec, rendered.error or response.error or "University vacancy board could not be fetched", source_url=url)
        elif response.ok:
            html = response.text
            source_url = response.url or url
        else:
            return blocked_result(self.spec, response.error or f"University vacancy board failed ({response.status_code})", source_url=url)

        total = parse_reported_total(
            html,
            (r"full\s+list\s+of\s+current\s+opportunities\s*\(?\s*([\d,]+)", r"([\d,]+)\s+current\s+(?:opportunities|vacancies)", r"([\d,]+)\s+vacancies?"),
        )
        records = self._parse(html, source_url)
        warnings: list[str] = []
        detail_failures = self._enrich_details(records, context) if self.spec.configuration.get("detail_links", True) else 0
        records = self._unique(records)
        if total is None and records:
            total = len(records)
            warnings.append("full-list total was verified by counting unique official vacancy references")
        if detail_failures:
            warnings.append(f"{detail_failures} University vacancy detail pages could not be verified")
        if total is None:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append("University board did not expose the full current opportunity total")
        elif detail_failures:
            status = SourceStatus.PARTIALLY_VERIFIED
        elif len(records) < total:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append(f"captured {len(records)} distinct references against reported total {total}; excluded categories are retained for audit")
        else:
            status = SourceStatus.COMPLETE_WITH_FALLBACK if method != "direct-http" else SourceStatus.COMPLETE
        return self.result(
            method=method,
            raw=records,
            source_total=total,
            status=status,
            warnings=warnings,
            source_url=source_url,
            verification_method="direct-primary-advert" if records else "primary-platform-listing",
        )

    def _parse(self, html: str, source_url: str):
        records = []
        seen: set[str] = set()
        default_org = str(self.spec.configuration.get("organization", "University of Nottingham"))
        from .common import candidate_blocks

        # The UoN board is a category/index page. Enumerate individual
        # vacancy references from its links before opening detail adverts.
        vacancy_links = []
        for match in re.finditer(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", html, re.I | re.S):
            apply_url = absolute_url(source_url, first_attr(match.group("attrs"), ("href",)))
            if not re.search(r"vacancy\.aspx\?ref=", apply_url, re.I):
                continue
            link_start = match.start()
            paragraph_start = html.rfind("<p", 0, link_start)
            paragraph_end = html.find("</p>", match.end())
            if paragraph_start >= 0 and paragraph_end >= 0 and html.rfind("</p>", 0, link_start) < paragraph_start:
                block = html[paragraph_start : paragraph_end + len("</p>")]
            else:
                block = match.group(0)
            heading_start = max(html.rfind("<h2", 0, link_start), html.rfind("<h3", 0, link_start))
            section = clean_text(html[heading_start:link_start]) if heading_start >= 0 else ""
            vacancy_links.append((clean_text(match.group("body")), apply_url, block, section))
        for label, apply_url, block, section in vacancy_links:
            match = re.search(r"[?&]ref=([^&#]+)", apply_url, re.I)
            record_id = match.group(1) if match else source_record_id("", apply_url, source_url)
            title = label or record_id
            key = record_id or apply_url
            if key in seen or not title:
                continue
            seen.add(key)
            block_text = clean_text(block)
            section_text = f"{section} {block_text}".casefold()
            deadline, closing_time = extract_deadline(block_text)
            records.append(
                make_raw(
                    source_id=self.spec.source_id,
                    source_url=source_url,
                    record_id=record_id,
                    title=title,
                    organization=default_org,
                    location="",
                    deadline=deadline,
                    closing_time=closing_time,
                    salary=labelled_html_value(block, ("Salary",)),
                    apply_url=apply_url,
                    reference=record_id,
                    description=block_text,
                    evidence={
                        "detail_required": True,
                        "internal_only": "internal only" in section_text or "internal only" in title.casefold(),
                        "overseas": any(term in section_text for term in ("ningbo", "china", "malaysia")),
                        "studentship": "studentship" in section_text or "phd studentship" in section_text,
                    },
                )
            )
        if records:
            return records

        # Small fixture/simple-list fallback for sources that expose cards.
        default_location = str(self.spec.configuration.get("location_default", ""))
        for attrs, body in candidate_blocks(html):
            title = first_title(body)
            if not title or title.lower() in {"full list of current opportunities", "current opportunities", "all current vacancies"}:
                continue
            record_id = source_record_id(attrs, body, source_url)
            apply_url = first_link(body, source_url) or source_url
            key = record_id or apply_url or title
            if key in seen:
                continue
            seen.add(key)
            text = clean_text(body)
            deadline, closing_time = extract_deadline(text)
            location = first_attr(attrs, ("data-location",)) or labelled_value(text, ("Location", "Based at", "Campus")) or default_location
            reference = first_attr(attrs, ("data-reference", "data-job-reference")) or record_id
            records.append(
                make_raw(
                    source_id=self.spec.source_id,
                    source_url=source_url,
                    record_id=record_id or reference,
                    title=title,
                    organization=default_org,
                    location=location,
                    deadline=deadline,
                    closing_time=closing_time,
                    contract=labelled_value(text, ("Contract", "Contract type")),
                    work_pattern=labelled_value(text, ("Hours", "Working pattern")),
                    salary=labelled_value(text, ("Salary", "Pay")),
                    apply_url=apply_url,
                    reference=reference,
                    description=text,
                    evidence={
                        "internal_only": "internal only" in text.lower() or "existing staff" in text.lower(),
                        "overseas": any(term in text.lower() for term in ("ningbo", "china", "malaysia")),
                        "studentship": "studentship" in text.lower() or "phd" in title.lower(),
                    },
                )
            )
        return records

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

    @staticmethod
    def _enrich_details(records: list, context: RunContext) -> int:
        failures = 0
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
            closing_value = labelled_html_value(html, ("Closing Date",))
            deadline, closing_time = extract_deadline(closing_value or text)
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            if not record.location_raw:
                record.location_raw = labelled_html_value(html, ("Location", "Based at", "Campus"))
            lowered = text.casefold()
            record.evidence["internal_only"] = "internal only" in lowered or "existing staff" in lowered
            record.evidence["overseas"] = any(term in lowered for term in ("ningbo", "china", "malaysia", "location uk other"))
            record.evidence["studentship"] = "studentship" in lowered or "phd" in record.title_raw.casefold()
            if "open until filled" in lowered or "rolling recruitment" in lowered:
                record.evidence["open_ended"] = True
            record.description_raw = f"{record.description_raw} {text}".strip()
        return failures
