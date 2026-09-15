"""Configurable parser for ordinary official vacancy indexes."""

from __future__ import annotations

import re

from ..html_tools import absolute_url, clean_text, extract_balanced_tag_blocks, extract_links, first_attr
from ..models import RunContext, SourceStatus, SourceSpec
from .base import BaseAdapter, blocked_result
from .common import extract_deadline, first_link, first_title, labelled_value, make_raw, parse_date_text, parse_reported_total, parse_time_text, source_record_id


_NON_JOB_LINK_LABELS = {
    "apply for a job",
    "current vacancies",
    "current job vacancies",
    "jobs",
    "job vacancies",
    "view",
}


def _link_container(html: str, start: int, end: int) -> str:
    """Use a table row as the record body when a page lists jobs in a table."""

    row_start = html.rfind("<tr", 0, start)
    row_end = html.find("</tr>", end)
    if row_start >= 0 and row_end >= 0 and html.rfind("</tr>", 0, start) < row_start:
        return html[row_start : row_end + len("</tr>")]
    return html[start:end]


def _usable_field(value: str) -> str:
    """Reject navigation/footer blobs accidentally captured as card fields."""

    cleaned = clean_text(value)
    if len(cleaned) > 180 or "navigation apply/login" in cleaned.casefold() or "contact us working for us" in cleaned.casefold():
        return ""
    return cleaned


def _parse_configured_job_links(html: str, spec: SourceSpec, source_url: str) -> list:
    pattern = str(spec.configuration.get("job_link_pattern", "")).strip()
    if not pattern:
        return []
    records = []
    seen: set[str] = set()
    organization_default = str(spec.configuration.get("organization", spec.display_name))
    location_default = str(spec.configuration.get("location_default", "")) if spec.configuration.get("location_default_verified", False) else ""
    for match in re.finditer(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", html, re.I | re.S):
        attrs = match.group("attrs")
        href = first_attr(attrs, ("href",))
        if not href or href.strip().startswith("#"):
            continue
        apply_url = absolute_url(source_url, href)
        if not apply_url or not re.search(pattern, apply_url, re.I):
            continue
        title = clean_text(match.group("body"))
        if title.casefold() in {"see more details", "more details", "view", "read more", "apply"}:
            title = clean_text(first_attr(attrs, ("aria-label", "data-title")))
            if not title:
                prefix = html[max(0, match.start() - 2_000) : match.start()]
                headings = re.findall(r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>", prefix, re.I | re.S)
                title = clean_text(headings[-1]) if headings else title
        if not title or title.casefold() in _NON_JOB_LINK_LABELS:
            continue
        container = _link_container(html, match.start(), match.end())
        text = clean_text(container)
        record_id = source_record_id(attrs, apply_url, source_url)
        if not record_id:
            record_id = re.sub(r"[^A-Za-z0-9_-]+", "-", apply_url.rstrip("/").rsplit("/", 1)[-1]).strip("-")[:80]
        key = record_id or apply_url
        if key in seen:
            continue
        seen.add(key)
        deadline, closing_time = extract_deadline(text)
        if not deadline:
            deadline = parse_date_text(first_attr(attrs, ("data-closing-date", "data-close-date")))
        if not closing_time:
            closing_time = parse_time_text(first_attr(attrs, ("data-closing-time",)))
        location = _usable_field(first_attr(attrs, ("data-location", "data-site"))) or _usable_field(labelled_value(
            text, ("Location", "Based at", "Site", "Work base")
        )) or location_default
        organization = _usable_field(labelled_value(text, ("Employer", "Organisation", "Organization"))) or organization_default
        if not spec.configuration.get("allow_organization_from_advert", True):
            organization = organization_default
        reference = first_attr(attrs, ("data-reference", "data-job-reference"))
        records.append(
            make_raw(
                source_id=spec.source_id,
                source_url=source_url,
                record_id=record_id,
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
                evidence={
                    "official_list_url": source_url,
                    "link_enumeration": True,
                    "detail_required": bool(spec.configuration.get("detail_required", False)),
                },
            )
        )
    return records


def _card_field(body: str, labels: tuple[str, ...]) -> str:
    """Read an adjacent label/value pair from a configured vacancy card."""

    label_pattern = "|".join(re.escape(label) for label in labels)
    patterns = (
        rf"<p\b[^>]*>\s*(?:{label_pattern})\s*:\s*</p>\s*(?:<div\b[^>]*>)?\s*(?P<value><[^>]+>.*?</[^>]+>|[^<]+)",
        rf"<(?:dt|th|strong|b)\b[^>]*>\s*(?:{label_pattern})\s*:?\\s*</(?:dt|th|strong|b)>\s*(?P<value><[^>]+>.*?</[^>]+>|[^<]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.I | re.S)
        if match:
            value = _usable_field(match.group("value"))
            if value:
                return value
    return ""


def _parse_configured_card_links(html: str, spec: SourceSpec, source_url: str) -> list:
    """Parse cards whose HTML is loaded by a public XHR/data route.

    This is deliberately opt-in per source.  It keeps the generic direct
    adapter conservative while supporting official card grids such as the
    Nottingham College vacancies listing.
    """

    card_class = str(spec.configuration.get("card_class", "")).strip()
    pattern = str(spec.configuration.get("job_link_pattern", "")).strip()
    if not card_class or not pattern:
        return []
    organization_default = str(spec.configuration.get("organization", spec.display_name))
    location_default = str(spec.configuration.get("location_default", "")) if spec.configuration.get("location_default_verified", False) else ""
    records = []
    seen: set[str] = set()
    for attrs, body in extract_balanced_tag_blocks(html, "div", required_tokens=(card_class,)):
        selected: tuple[str, str] | None = None
        selected_attrs = ""
        for match in re.finditer(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", body, re.I | re.S):
            link_attrs = match.group("attrs")
            href = first_attr(link_attrs, ("href",))
            apply_url = absolute_url(source_url, href) if href else ""
            if href and re.search(pattern, apply_url, re.I):
                selected = (clean_text(match.group("body")), apply_url)
                selected_attrs = link_attrs
                break
        if not selected:
            continue
        title, apply_url = selected
        if not title or title.casefold() in _NON_JOB_LINK_LABELS:
            title = clean_text(first_attr(selected_attrs, ("aria-label", "data-title")))
        if not title or title.casefold() in _NON_JOB_LINK_LABELS:
            continue
        record_id = source_record_id(selected_attrs, body, source_url)
        if not record_id:
            record_id = re.sub(r"[^A-Za-z0-9_-]+", "-", apply_url.rstrip("/").rsplit("/", 1)[-1]).strip("-")[:80]
        if record_id in seen:
            continue
        seen.add(record_id)
        text = clean_text(body)
        deadline, closing_time = extract_deadline(text)
        location = _card_field(body, ("Location", "Based at", "Site", "Work base")) or location_default
        organization = organization_default
        if spec.configuration.get("allow_organization_from_advert", True):
            organization = _card_field(body, ("Employer", "Organisation", "Organization")) or organization
        records.append(
            make_raw(
                source_id=spec.source_id,
                source_url=source_url,
                record_id=record_id,
                title=title,
                organization=organization,
                location=location,
                deadline=deadline,
                closing_time=closing_time,
                contract=_card_field(body, ("Contract Type", "Contract", "Contract type")),
                work_pattern=_card_field(body, ("Hours", "Working pattern", "Work pattern")),
                salary=_card_field(body, ("Salary", "Pay")),
                apply_url=apply_url,
                reference=first_attr(selected_attrs, ("data-reference", "data-job-reference")),
                description=text,
                evidence={
                    "official_list_url": source_url,
                    "card_boundary": card_class,
                    "link_enumeration": True,
                    "detail_required": bool(spec.configuration.get("detail_required", False)),
                },
            )
        )
    return records


def parse_direct_html(html: str, spec: SourceSpec, source_url: str) -> list:
    records = _parse_configured_card_links(html, spec, source_url)
    records.extend(_parse_configured_job_links(html, spec, source_url))
    seen: set[str] = set()
    for record in records:
        seen.add(record.source_record_id or record.apply_url_raw or record.title_raw)
    organization_default = str(spec.configuration.get("organization", spec.display_name))
    location_default = str(spec.configuration.get("location_default", "")) if spec.configuration.get("location_default_verified", False) else ""
    from .common import candidate_blocks

    for attrs, body in candidate_blocks(html):
        text = clean_text(body)
        title = first_title(body)
        if not title or title.lower() in {"current vacancies", "current job vacancies"}:
            continue
        record_id = source_record_id(attrs, body, source_url)
        apply_url = first_link(body, source_url) or source_url
        key = record_id or apply_url or title
        if key in seen:
            continue
        seen.add(key)
        deadline, closing_time = extract_deadline(text)
        if not deadline:
            deadline = parse_date_text(first_attr(attrs, ("data-closing-date", "data-close-date")))
        if not closing_time:
            closing_time = parse_time_text(first_attr(attrs, ("data-closing-time",)))
        location = _usable_field(first_attr(attrs, ("data-location", "data-site"))) or _usable_field(labelled_value(text, ("Location", "Based at", "Site", "Work base"))) or location_default
        organization = _usable_field(labelled_value(text, ("Employer", "Organisation", "Organization"))) or organization_default
        if not spec.configuration.get("allow_organization_from_advert", True):
            organization = organization_default
        reference = first_attr(attrs, ("data-reference", "data-job-reference"))
        records.append(
            make_raw(
                source_id=spec.source_id,
                source_url=source_url,
                record_id=record_id,
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
                evidence={"official_list_url": source_url, "detail_required": bool(spec.configuration.get("detail_required", False))},
            )
        )
    return records


class DirectCouncilAdapter(BaseAdapter):
    def fetch(self, context: RunContext):
        config = self.spec.configuration
        url = str(config.get("list_url") or self.spec.official_entry_url)
        response = context.http_client.get(url, use_cache=True)
        method = "direct-http"
        access_blocked = False
        if (not response.ok or self._needs_browser(response.text, response.status_code)) and context.allow_browser:
            rendered = context.browser.render(
                url,
                wait_for=str(config.get("browser_wait_for", "")) or None,
                wait_ms=int(config.get("browser_wait_ms", 1_500)),
                load_more_selector=str(config.get("browser_load_more_selector", "")) or None,
            )
            if rendered.ok:
                html = rendered.html
                source_url = rendered.url or url
                method = "playwright-chromium"
                access_blocked = rendered.status_code in {401, 403, 404, 429}
            elif not response.ok:
                return blocked_result(self.spec, rendered.error or response.error or "official vacancy page could not be fetched", source_url=url)
            else:
                html = response.text
                source_url = response.url or url
        elif response.ok:
            html = response.text
            source_url = response.url or url
        else:
            return blocked_result(self.spec, response.error or f"official vacancy page failed ({response.status_code})", source_url=url)

        records = parse_direct_html(html, self.spec, source_url)
        warnings: list[str] = []
        pagination_failed = False
        browser_attempted = method != "direct-http"
        if not records and context.allow_browser and not browser_attempted:
            rendered = context.browser.render(
                url,
                wait_for=str(config.get("browser_wait_for", "")) or None,
                wait_ms=int(config.get("browser_wait_ms", 1_500)),
                load_more_selector=str(config.get("browser_load_more_selector", "")) or None,
            )
            browser_attempted = True
            if rendered.ok:
                html = rendered.html
                source_url = rendered.url or url
                method = "playwright-chromium"
                access_blocked = rendered.status_code in {401, 403, 404, 429}
                records = parse_direct_html(html, self.spec, source_url)
            elif rendered.error:
                warnings.append(rendered.error)
        seen_pages = {source_url}
        next_url = self._next_url(html, source_url)
        while next_url and next_url not in seen_pages:
            seen_pages.add(next_url)
            page = context.http_client.get(next_url, use_cache=True)
            if not page.ok:
                pagination_failed = True
                warnings.append(f"pagination page failed: {next_url}")
                break
            records.extend(parse_direct_html(page.text, self.spec, page.url or next_url))
            next_url = self._next_url(page.text, page.url or next_url)
        records = self._unique(records)
        detail_failures = self._enrich_details(records, context) if config.get("detail_links") else 0
        if detail_failures:
            warnings.append(f"{detail_failures} direct vacancy detail pages could not be verified")
        marker = clean_text(html).lower()
        no_results_evidence = any(text in marker for text in ("no current vacancies", "no vacancies currently", "there are currently no", "no jobs available"))
        if access_blocked and not records:
            status = SourceStatus.BLOCKED
            warnings.append(f"official vacancy page returned HTTP access status {rendered.status_code if 'rendered' in locals() else response.status_code}")
        elif pagination_failed or detail_failures:
            status = SourceStatus.PARTIALLY_VERIFIED
        elif not records and not no_results_evidence:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append("official page fetched but no complete vacancy list or explicit zero-result statement was found")
        else:
            status = SourceStatus.COMPLETE_WITH_FALLBACK if method != "direct-http" else SourceStatus.COMPLETE
        source_total = parse_reported_total(
            clean_text(html),
            (r"([\d,]+)\s+(?:current\s+)?(?:jobs?|vacancies?)\s+(?:found|available|listed)", r"showing\s+\d+\s+to\s+\d+\s+of\s+([\d,]+)"),
        )
        if no_results_evidence:
            source_total = 0
        return self.result(
            method=method,
            raw=records,
            source_total=source_total,
            status=status,
            warnings=warnings,
            source_url=source_url,
            verification_method="direct-primary-advert" if records else "primary-platform-listing",
        )

    @staticmethod
    def _needs_browser(text: str, status_code: int | None) -> bool:
        marker = clean_text(text).lower()
        return status_code in {401, 403, 429} or "enable javascript" in marker or "please wait, loading" in marker

    @staticmethod
    def _next_url(html: str, base_url: str) -> str:
        for label, url in extract_links(html, base_url):
            if any(marker in url.casefold() for marker in ("cookiebot", "privacy-policy")):
                continue
            if re.search(r"next|more|older", label, re.I):
                return url
        return ""

    def _enrich_details(self, records: list, context: RunContext) -> int:
        failures = 0
        for record in records:
            if record.closing_date_raw and record.location_raw and not record.evidence.get("detail_required"):
                continue
            if not record.apply_url_raw or record.apply_url_raw == record.source_url:
                continue
            response = context.http_client.get(record.apply_url_raw, use_cache=True)
            if not response.ok:
                failures += 1
                record.evidence["detail_fetch_error"] = response.error or f"HTTP {response.status_code}"
                continue
            text = clean_text(response.text)
            if record.title_raw.casefold() in {"see more details", "more details", "view", "read more", "apply"}:
                detail_title = first_title(response.text)
                if detail_title and detail_title.casefold() not in _NON_JOB_LINK_LABELS:
                    record.title_raw = detail_title
            deadline, closing_time = extract_deadline(text)
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            if not record.location_raw or not _usable_field(record.location_raw):
                record.location_raw = labelled_value(text, ("Location", "Based at", "Site", "Work base"))
            if not _usable_field(record.organization_raw):
                record.organization_raw = str(self.spec.configuration.get("organization", self.spec.display_name))
                record.advertised_employer_raw = record.organization_raw
            record.contract_raw = record.contract_raw or labelled_value(text, ("Contract", "Contract type"))
            record.work_pattern_raw = record.work_pattern_raw or labelled_value(text, ("Hours", "Working pattern", "Work pattern"))
            record.salary_raw = record.salary_raw or labelled_value(text, ("Salary", "Pay"))
            record.description_raw = f"{record.description_raw} {text}".strip()
            record.evidence["detail_verified"] = True
            lowered = text.casefold()
            advertised = labelled_value(text, ("Employer", "Organisation", "Organization", "Advertised by"))
            if advertised:
                record.advertised_employer_raw = advertised
                record.organization_raw = advertised
            configured_host = str(
                self.spec.configuration.get("host_organization")
                or self.spec.configuration.get("organization", "")
            ).strip()
            if configured_host:
                record.host_organization_raw = configured_host
                if advertised and self._same_org(advertised, configured_host):
                    record.host_association_verified = True
                    record.host_association_type = "direct"
                    record.host_association_evidence = "official detail employer matches configured organisation"
                elif configured_host.casefold() in text.casefold():
                    record.host_association_verified = True
                    record.host_association_type = "agency" if "agency" in lowered else "subcontractor"
                    record.host_association_evidence = "official detail names configured host/service"
            if "agency" in lowered or "subcontractor" in lowered:
                record.evidence["agency"] = "agency" in lowered
                record.evidence["subcontractor"] = "subcontractor" in lowered
                record.evidence["generic_agency"] = not record.host_association_verified
            record.evidence.update(
                {
                    "internal_only": "internal only" in lowered or "existing staff" in lowered,
                    "overseas": any(term in lowered for term in ("ningbo", "china", "malaysia", "uk other")),
                    "withdrawn": "vacancy withdrawn" in lowered or "no longer accepting applications" in lowered,
                }
            )
        return failures

    @staticmethod
    def _same_org(left: str, right: str) -> bool:
        left_value = re.sub(r"[^a-z0-9]+", " ", left.casefold()).strip()
        right_value = re.sub(r"[^a-z0-9]+", " ", right.casefold()).strip()
        return bool(left_value and right_value and (left_value == right_value or left_value in right_value or right_value in left_value))

    @staticmethod
    def _unique(records: list) -> list:
        output = []
        seen: set[str] = set()
        for record in records:
            key = record.source_record_id or record.reference_raw or record.apply_url_raw
            if key in seen:
                continue
            seen.add(key)
            output.append(record)
        return output
