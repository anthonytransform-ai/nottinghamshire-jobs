"""Anti-bot-aware TAL adapter for council and education boards."""

from __future__ import annotations

import re

from ..html_tools import clean_text, extract_links, first_attr
from ..models import RunContext, SourceStatus
from .base import BaseAdapter, blocked_result
from .common import extract_deadline, first_link, first_title, labelled_value, make_raw, parse_date_text, parse_reported_total, source_record_id


class TALAdapter(BaseAdapter):
    def fetch(self, context: RunContext):
        config = self.spec.configuration
        entry_url = self.spec.official_entry_url
        response = context.http_client.get(entry_url, use_cache=False)
        if not response.ok and not context.allow_browser:
            return blocked_result(self.spec, response.error or f"TAL official entry failed ({response.status_code})", source_url=entry_url)
        entry_html = response.text if response.ok else ""
        board_url = str(config.get("board_url", ""))
        if not board_url:
            candidates = [
                url for _label, url in extract_links(entry_html, entry_url)
                if "tal.net" in url.lower() and ("search" in url.lower() or "vacan" in url.lower() or "appcentre" in url.lower())
            ]
            if candidates:
                board_url = candidates[0]
        if not board_url and "tal.net" in entry_url.lower():
            board_url = entry_url
        if not board_url:
            return blocked_result(self.spec, "official entry did not expose a current TAL board route", source_url=entry_url)

        board_response = context.http_client.get(board_url, use_cache=False)
        method = "direct-http"
        if self._is_challenge(board_response.text, board_response.status_code):
            if context.allow_browser:
                rendered = context.browser.render(board_url, wait_ms=3_000)
                if rendered.ok and not self._is_challenge(rendered.html, rendered.status_code):
                    html = rendered.html
                    current_url = rendered.url or board_url
                    method = "playwright-chromium"
                else:
                    warning = "TAL human-verification page detected; no bypass attempted"
                    return self._partial_or_blocked([], None, board_url, warning)
            else:
                return self._partial_or_blocked([], None, board_url, "TAL human-verification page detected; no bypass attempted")
        elif board_response.ok:
            html = board_response.text
            current_url = board_response.url or board_url
        else:
            return blocked_result(self.spec, board_response.error or f"TAL board failed ({board_response.status_code})", source_url=board_url)

        warnings: list[str] = []
        total, records, filtered = self._parse(html, current_url)
        if not records and context.allow_browser and method == "direct-http":
            rendered = context.browser.render(board_url, wait_ms=2_500, capture_urls=True)
            if rendered.ok and not self._is_challenge(rendered.html, rendered.status_code):
                html = rendered.html
                current_url = rendered.url or board_url
                method = "playwright-chromium"
                total, records, filtered = self._parse(html, current_url)
            elif rendered.error:
                warnings.append(rendered.error)
        if filtered:
            warnings.append("TAL URL appears filtered; it is not sufficient evidence of the complete employer population")
        seen_pages = {current_url}
        next_url = self._next_url(html, current_url)
        while next_url and next_url not in seen_pages and (total is None or len(self._unique(records)) < total):
            seen_pages.add(next_url)
            if method != "direct-http" and context.allow_browser:
                page = context.browser.render(next_url, wait_ms=2_000)
                if not page.ok:
                    warnings.append(f"TAL pagination page failed: {next_url}")
                    break
                page_total, page_records, page_filtered = self._parse(page.html, page.url or next_url)
            else:
                page = context.http_client.get(next_url, use_cache=False)
                if not page.ok:
                    warnings.append(f"TAL pagination page failed: {next_url}")
                    break
                page_total, page_records, page_filtered = self._parse(page.text, page.url or next_url)
            if total is None:
                total = page_total
            records.extend(page_records)
            filtered = filtered or page_filtered
            next_url = self._next_url(page.html if method != "direct-http" and context.allow_browser else page.text, page.url or next_url)
        records = self._unique(records)
        if filtered:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append("reported total came from a filtered TAL view")
        elif total is None:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append("TAL board did not expose a vacancy total")
        elif len(records) < total:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append(f"captured {len(records)} unique TAL IDs against reported total {total}")
        else:
            status = SourceStatus.COMPLETE_WITH_FALLBACK if method != "direct-http" else SourceStatus.COMPLETE
        return self.result(
            method=method,
            raw=records,
            source_total=total,
            status=status,
            warnings=warnings,
            source_url=current_url,
            verification_method="primary-platform-listing" if method == "direct-http" else "official-indexed-fallback",
        )

    def _parse(self, html: str, source_url: str):
        total = parse_reported_total(html, (r"([\d,]+)\s+vacancies?\s+found", r"([\d,]+)\s+vacancies?"))
        filtered = bool(re.search(r"f_Item_Opportunity_", source_url, re.I))
        from .common import candidate_blocks

        row_pattern = re.compile(
            r"<tr\b(?P<attrs>[^>]*\bsearch_res\b[^>]*)>(?P<body>.*?)</tr>",
            re.I | re.S,
        )
        rows = [(match.group("attrs"), match.group("body")) for match in row_pattern.finditer(html or "")]
        if rows:
            records = []
            seen: set[str] = set()
            organization = "Nottinghamshire County Council" if self.spec.configuration.get("board_kind") == "ncc" else ""
            for attrs, body in rows:
                title = first_title(body)
                if not title:
                    continue
                record_id = first_attr(attrs, ("data-oppid", "data-opportunity-id")) or source_record_id(attrs, body, source_url)
                key = record_id or title
                if key in seen:
                    continue
                seen.add(key)
                cells = [clean_text(value) for value in re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.I | re.S)]
                location = cells[1] if len(cells) > 1 else ""
                deadline = parse_date_text(cells[2]) if len(cells) > 2 else ""
                records.append(
                    make_raw(
                        source_id=self.spec.source_id,
                        source_url=source_url,
                        record_id=record_id,
                        title=title,
                        organization=organization,
                        location=location,
                        deadline=deadline,
                        closing_time="",
                        apply_url=first_link(body, source_url) or source_url,
                        reference=record_id,
                        description=clean_text(body),
                        evidence={"tal_board_kind": self.spec.configuration.get("board_kind", ""), "table_row": True},
                    )
                )
            return total, records, filtered

        blocks = candidate_blocks(html)
        records = []
        seen: set[str] = set()
        organization = "Nottinghamshire County Council" if self.spec.configuration.get("board_kind") == "ncc" else ""
        for attrs, body in blocks:
            record_id = source_record_id(attrs, body, source_url)
            title = first_title(body)
            if not title:
                continue
            if record_id and record_id in seen:
                continue
            seen.add(record_id or title)
            text = clean_text(body)
            deadline, closing_time = extract_deadline(text)
            location = first_attr(attrs, ("data-location",)) or labelled_value(text, ("Location", "Based at", "Working location"))
            employer = labelled_value(text, ("Employer", "Organisation", "Organisation name")) or organization
            reference = first_attr(attrs, ("data-reference", "data-opportunity-id")) or record_id
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
                    work_pattern=labelled_value(text, ("Hours", "Working pattern")),
                    salary=labelled_value(text, ("Salary", "Pay")),
                    apply_url=first_link(body, source_url) or source_url,
                    reference=reference,
                    description=text,
                    evidence={"tal_board_kind": self.spec.configuration.get("board_kind", "")},
                )
            )
        return total, records, filtered

    @staticmethod
    def _is_challenge(text: str, status_code: int | None) -> bool:
        marker = clean_text(text).lower()
        return status_code in {401, 403, 429} or "quick check needed" in marker or "human verification" in marker or "captcha" in marker

    @staticmethod
    def _next_url(html: str, base_url: str) -> str:
        for label, url in extract_links(html, base_url):
            if re.search(r"next|more|older", label, re.I):
                return url
        return ""

    @staticmethod
    def _unique(records: list) -> list:
        seen: set[str] = set()
        output = []
        for record in records:
            key = record.source_record_id or record.reference_raw or record.apply_url_raw
            if key in seen:
                continue
            seen.add(key)
            output.append(record)
        return output

    def _partial_or_blocked(self, records, total, url: str, warning: str):
        return self.result(
            method="official-entry-plus-indexed-fallback",
            raw=records,
            source_total=total,
            status=SourceStatus.BLOCKED,
            warnings=[warning],
            errors=["TAL direct board is currently inaccessible"],
            source_url=url,
            verification_method="official-indexed-fallback",
        )
