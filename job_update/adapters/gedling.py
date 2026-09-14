"""Gedling Borough Council's public ASP.NET jobs board adapter."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from ..html_tools import clean_text, extract_links, hidden_form_fields
from ..models import RunContext, SourceStatus
from .base import BaseAdapter, blocked_result
from .common import extract_deadline, make_raw, parse_time_text


def _inline_value(html: str, label: str) -> str:
    match = re.search(
        rf"{re.escape(label)}\s*:\s*(?P<value>.*?)(?:<br\s*/?>|</p>|$)",
        html or "",
        re.I | re.S,
    )
    return clean_text(match.group("value")) if match else ""


def parse_gedling_html(html: str, source_url: str, *, source_id: str, organization: str, location: str) -> tuple[list, bool]:
    """Parse the six-card current list without treating the page wrapper as a job."""

    records = []
    seen: set[str] = set()
    card_pattern = re.compile(
        r"<div\b(?P<attrs>[^>]*\bclass\s*=\s*['\"][^'\"]*\bu-pull-left\b[^'\"]*['\"][^>]*)>(?P<body>.*?)</div>",
        re.I | re.S,
    )
    for index, match in enumerate(card_pattern.finditer(html), start=1):
        attrs = match.group("attrs")
        body = match.group("body")
        title_match = re.search(r"<h3\b[^>]*>(.*?)</h3>", body, re.I | re.S)
        title = clean_text(title_match.group(1)) if title_match else ""
        if not title:
            continue
        event_match = re.search(r"__doPostBack\s*\(\s*['\"]([^'\"]+)['\"]", body, re.I)
        event_target = event_match.group(1) if event_match else ""
        record_id = f"GEDLING-{index:03d}"
        if event_target:
            control_match = re.search(r"rptCurrentJobs\$ctl(\d+)\$btnView", event_target, re.I)
            if control_match:
                record_id = f"GEDLING-{int(control_match.group(1)):03d}"
        if record_id in seen:
            continue
        seen.add(record_id)
        text = clean_text(body)
        deadline, closing_time = extract_deadline(text)
        if not closing_time:
            closing_time = parse_time_text(_inline_value(body, "Closing Date"))
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
                salary=_inline_value(body, "Salary"),
                work_pattern=_inline_value(body, "Hours"),
                apply_url=source_url,
                reference=record_id,
                description=text,
                evidence={"gedling_event_target": event_target, "detail_required": bool(event_target)},
            )
        )
    return records, bool(records)


class GedlingAdapter(BaseAdapter):
    def fetch(self, context: RunContext):
        url = str(self.spec.configuration.get("list_url") or self.spec.official_entry_url)
        response = context.http_client.get(url, use_cache=False)
        method = "direct-http"
        if not response.ok and context.allow_browser:
            rendered = context.browser.render(url, wait_ms=1_500)
            if rendered.ok:
                html = rendered.html
                source_url = rendered.url or url
                method = "playwright-chromium"
            else:
                return blocked_result(self.spec, rendered.error or response.error or "Gedling jobs board could not be fetched", source_url=url)
        elif response.ok:
            html = response.text
            source_url = response.url or url
        else:
            return blocked_result(self.spec, response.error or f"Gedling jobs board failed ({response.status_code})", source_url=url)

        organization = str(self.spec.configuration.get("organization", self.spec.display_name))
        location = str(self.spec.configuration.get("location_default", "Gedling"))
        records, has_cards = parse_gedling_html(
            html,
            source_url,
            source_id=self.spec.source_id,
            organization=organization,
            location=location,
        )
        detail_failures = 0
        if method == "direct-http" and records:
            fields = hidden_form_fields(html)
            for record in records:
                event_target = str(record.evidence.get("gedling_event_target", ""))
                if not event_target:
                    continue
                data = dict(fields)
                data["__EVENTTARGET"] = event_target
                data["__EVENTARGUMENT"] = ""
                detail = context.http_client.request(
                    source_url,
                    method="POST",
                    data=urlencode(data).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    use_cache=False,
                )
                if not detail.ok:
                    detail_failures += 1
                    record.evidence["detail_fetch_error"] = detail.error or f"HTTP {detail.status_code}"
                    continue
                self._apply_detail(record, detail.text, source_url)

        warnings: list[str] = []
        if detail_failures:
            warnings.append(f"{detail_failures} Gedling postback detail pages could not be verified")
        no_results = any(
            marker in clean_text(html).casefold()
            for marker in ("no current vacancies", "no vacancies currently", "no jobs available", "there are no jobs")
        )
        if detail_failures or (not records and not no_results):
            status = SourceStatus.PARTIALLY_VERIFIED
            if not records and not has_cards:
                warnings.append("official Gedling page was fetched but no parseable current vacancy cards were found")
        else:
            status = SourceStatus.COMPLETE_WITH_FALLBACK if method != "direct-http" else SourceStatus.COMPLETE
        return self.result(
            method=method,
            raw=records,
            source_total=len(records) if records or no_results else None,
            status=status,
            warnings=warnings,
            source_url=source_url,
            verification_method="direct-primary-advert" if detail_failures == 0 and records else "primary-platform-listing",
        )

    @staticmethod
    def _apply_detail(record, html: str, source_url: str) -> None:
        text = clean_text(html)
        deadline, closing_time = extract_deadline(text)
        if deadline:
            record.closing_date_raw = deadline
        if closing_time:
            record.closing_time_raw = closing_time
        record.salary_raw = record.salary_raw or _inline_value(html, "Salary")
        record.work_pattern_raw = record.work_pattern_raw or _inline_value(html, "Hours")
        record.description_raw = f"{record.description_raw} {text}".strip()
        record.evidence["detail_verified"] = True
        record.evidence["internal_only"] = "internal only" in text.casefold()
        record.evidence["withdrawn"] = "vacancy withdrawn" in text.casefold() or "no longer accepting applications" in text.casefold()
        for label, url in extract_links(html, source_url):
            if re.search(r"apply|application", label, re.I) and not re.search(r"guidance|policy", label, re.I):
                record.apply_url_raw = url
                break
