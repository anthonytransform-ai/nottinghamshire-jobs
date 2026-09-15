"""Reusable MHR iTrent adapter for the four council views."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ..html_tools import clean_text, extract_balanced_tag_blocks, extract_links, first_attr
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


def _card_value(body: str, labels: tuple[str, ...]) -> str:
    """Read a value from an iTrent labelled result/profile entry."""

    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"<span\b[^>]*class=[\"'][^\"']*Mhr-jobDetailEntry--label[^\"']*[\"'][^>]*>\s*(?:{label_pattern})\s*</span>"
        rf".*?<span\b[^>]*class=[\"'][^\"']*Mhr-jobDetailEntry--text[^\"']*[\"'][^>]*>(?P<value>.*?)</span>",
        body or "",
        re.I | re.S,
    )
    return clean_text(match.group("value")) if match else ""


def _profile_block(html: str, record_id: str) -> str:
    """Return the selected vacancy's actual in-page iTrent profile."""

    from ..html_tools import extract_balanced_tag_blocks

    for attrs, body in extract_balanced_tag_blocks(html, "div"):
        if first_attr(attrs, ("vac-id",)) != record_id:
            continue
        if re.search(r"\bclass\s*=\s*[\"'][^\"']*\bMhr-jobProfile\b[^\"']*[\"']", attrs, re.I):
            return body
    return ""


def _profile_request(attrs: str, source_url: str) -> str:
    request = first_attr(attrs, ("bu-send",))
    return urljoin(source_url, request) if request else ""


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

    blocks = extract_balanced_tag_blocks(html, "div", required_tokens=("vac-id=", "mhr-card"))
    if not blocks:
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
    configured_host = str(spec.configuration.get("host_organization", "")).strip()
    configured_host_verified = bool(spec.configuration.get("host_association_verified", False))
    configured_host_type = str(spec.configuration.get("host_association_type", "direct" if configured_host_verified else ""))
    configured_host_evidence = str(spec.configuration.get("host_association_evidence", "official iTrent employer portal is the configured host"))
    default_location = str(spec.configuration.get("location_default", "")) if spec.configuration.get("location_default_verified", False) else ""
    for attrs, body in blocks:
        record_id = source_record_id(attrs, body, source_url)
        title = first_title(body)
        if not title:
            title = first_attr(attrs, ("data-title", "aria-label"))
        if not title:
            visible = clean_text(body)
            title_match = re.search(r"(?:search\s+results\s+)?(?P<title>[^|]{2,140}?)\s+job\s+profile\b", visible, re.I)
            if title_match:
                title = clean_text(title_match.group("title"))
                if "search results" in title.casefold():
                    title = title.rsplit("search results", 1)[-1].strip()
        title = re.sub(r"\s+job\s+profile\s*$", "", title, flags=re.I).strip()
        if not title or (record_id and record_id in seen):
            continue
        seen.add(record_id or title)
        text = clean_text(body)
        deadline, closing_time = extract_deadline(text)
        if not deadline:
            deadline = parse_date_text(first_attr(attrs, ("data-closing-date", "data-close-date")))
        if not closing_time:
            closing_time = parse_time_text(first_attr(attrs, ("data-closing-time",)))
        location = first_attr(attrs, ("data-location", "data-site")) or _card_value(body, ("Location", "Based at", "Site")) or labelled_value(text, ("Location", "Based at", "Site")) or default_location
        apply_url = first_link(body, source_url) or source_url
        reference = first_attr(attrs, ("data-reference", "data-job-reference", "vac-id", "data-vac-id", "data-vacancy-id"))
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
                contract=_card_value(body, ("Contract", "Contract type", "Basis")) or labelled_value(text, ("Contract", "Contract type")),
                work_pattern=_card_value(body, ("Hours", "Working pattern", "Work pattern")) or labelled_value(text, ("Hours", "Working pattern", "Work pattern")),
                salary=_card_value(body, ("Salary", "Pay")) or labelled_value(text, ("Salary", "Pay")),
                apply_url=apply_url,
                reference=reference,
                host_organization=configured_host,
                host_association_verified=configured_host_verified,
                host_association_type=configured_host_type,
                host_association_evidence=configured_host_evidence if configured_host_verified else "",
                description=text,
                evidence={
                    "itrent_wvid": spec.configuration.get("wvid", ""),
                    "itrent_public_reference": bool(reference),
                    "detail_required": bool(spec.configuration.get("detail_required", False)),
                    "detail_url": _profile_request(attrs, source_url),
                    "host_association_verified": configured_host_verified,
                },
            )
        )
    return total, records


class ITrentAdapter(BaseAdapter):
    def fetch(self, context: RunContext) -> SourceResult:
        config = self.spec.configuration
        url = str(config.get("portal_url") or self.spec.official_entry_url)
        response = context.http_client.get(url, use_cache=True)
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
                response = context.http_client.get(source_url, use_cache=True)
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
            response = context.http_client.get(next_url, use_cache=True)
            if not response.ok:
                warnings.append(f"pagination page failed: {next_url}")
                break
            page_total, page_records = parse_itrent_html(response.text, self.spec, next_url)
            total = total if total is not None else page_total
            records.extend(page_records)
            next_url = self._next_url(response.text, next_url)
        records = self._unique(records)
        detail_failures = self._enrich_details(records, context, listing_html=html)
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

    def _enrich_details(self, records: list, context: RunContext, *, listing_html: str = "") -> int:
        failures = 0
        for record in records:
            detail_required = bool(record.evidence.get("detail_required"))
            if not detail_required and record.closing_date_raw and record.location_raw:
                # The list row is sufficient for ordinary council views. Do
                # not issue a false detail request merely because iTrent's
                # shared page contains a generic ``Job profile`` string.
                continue
            profile = _profile_block(listing_html, record.source_record_id) if listing_html and record.source_record_id else ""
            if profile:
                self._apply_profile(record, profile, context, method="playwright-listing-profile")
                continue

            response = None
            detail_url = str(record.evidence.get("detail_url", ""))
            if detail_url:
                response = context.http_client.get(detail_url, use_cache=True)
                if response.ok:
                    profile = _profile_block(response.text, record.source_record_id)
            if not profile and context.allow_browser and record.source_record_id and record.source_url:
                selector = f'[vac-id="{record.source_record_id}"]'
                rendered = context.browser.render(
                    record.source_url,
                    wait_for=".Mhr-jobDetail",
                    wait_ms=500,
                    load_more_selector=".Mhr-jobSearchMoreResultsButton",
                    click_selector=selector,
                    click_wait_for=".Mhr-jobProfile",
                    timeout_ms=15_000,
                )
                if rendered.ok:
                    profile = _profile_block(rendered.html, record.source_record_id)
                    if profile:
                        self._apply_profile(record, profile, context, method="playwright-clicked-profile")
                        continue
            if profile:
                self._apply_profile(record, profile, context, method="direct-profile-route")
                continue
            if not detail_required:
                continue
            failures += 1
            record.evidence["detail_fetch_error"] = (response.error if response is not None else "") or "iTrent vacancy profile was not exposed"
        return failures

    def _apply_profile(self, record, profile: str, context: RunContext, *, method: str) -> None:
        text = clean_text(profile)
        location_match = re.search(
            r"class=[\"'][^\"']*Mhr-jobProfile--locationText[^\"']*[\"'][^>]*>(?P<location>.*?)</span>",
            profile,
            re.I | re.S,
        )
        location = clean_text(location_match.group("location")) if location_match else _card_value(profile, ("Location", "Site", "Based at"))
        if location:
            record.location_raw = location
        closing_match = re.search(
            r"class=[\"'][^\"']*Mhr-jobProfile--closingDate[^\"']*[\"'][^>]*>(?P<date>.*?)</span>",
            profile,
            re.I | re.S,
        )
        deadline, closing_time = extract_deadline(text)
        if closing_match:
            deadline = parse_date_text(clean_text(closing_match.group("date"))) or deadline
        if deadline:
            record.closing_date_raw = deadline
        if closing_time:
            record.closing_time_raw = closing_time
        title = first_title(profile)
        if title and title.casefold() not in {"((name))", "job profile"}:
            record.title_raw = re.sub(r"\s+job\s+profile\s*$", "", title, flags=re.I).strip()
        salary = _card_value(profile, ("Salary", "Pay"))
        if salary:
            record.salary_raw = salary
        contract = _card_value(profile, ("Basis", "Contractual hours", "Contract", "Contract type"))
        if contract:
            record.contract_raw = contract
        work_pattern = _card_value(profile, ("Working pattern", "Hours", "Work pattern"))
        if work_pattern:
            record.work_pattern_raw = work_pattern
        reference = _card_value(profile, ("Job reference", "Reference"))
        if reference:
            record.reference_raw = reference
        apply_url = first_link(profile, record.source_url)
        if apply_url:
            record.apply_url_raw = apply_url
        record.description_raw = f"{record.description_raw} {text}".strip()
        lowered = text.casefold()
        configured_host = str(
            record.host_organization_raw
            or self.spec.configuration.get("host_organization")
            or self.spec.configuration.get("organization", "")
        ).strip()
        advertised = _card_value(profile, ("Employer", "Organisation", "Organization"))
        if advertised:
            record.advertised_employer_raw = advertised
            record.organization_raw = advertised
        if configured_host:
            record.host_organization_raw = configured_host
            if advertised and self._same_org(advertised, configured_host):
                record.host_association_verified = True
                record.host_association_type = "direct"
                record.host_association_evidence = "iTrent profile employer matches configured organisation"
            elif bool(record.evidence.get("host_association_verified")) or configured_host.casefold() in lowered:
                record.host_association_verified = True
                record.host_association_type = str(record.host_association_type or ("agency" if "agency" in lowered else "subcontractor"))
                record.host_association_evidence = record.host_association_evidence or "iTrent profile names configured host/service"
        record.evidence.update(
            {
                "detail_verified": True,
                "detail_retrieval_method": method,
                "independent": "independent school" in lowered or "private college" in lowered,
                "private": "private school" in lowered or "private college" in lowered,
                "agency": bool(re.search(r"\b(?:agency|recruitment agency|locum agency)\b", lowered)),
                "subcontractor": "subcontractor" in lowered,
                "generic_agency": bool("agency" in lowered and not record.host_association_verified),
                "external_apprenticeship": "apprenticeship" in lowered and any(
                    marker in lowered
                    for marker in ("student opportunity", "for students", "apply for an apprenticeship", "study programme", "not employed by")
                ),
            }
        )

    @staticmethod
    def _same_org(left: str, right: str) -> bool:
        def normalise(value: str) -> str:
            value = value.casefold().replace("&", " and ")
            return re.sub(r"[^a-z0-9]+", " ", value).strip()

        left_value = normalise(left)
        right_value = normalise(right)
        return bool(left_value and right_value and (left_value == right_value or left_value in right_value or right_value in left_value))

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
