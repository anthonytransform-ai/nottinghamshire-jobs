"""Nottingham City Council Oracle HCM public requisition adapter."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from ..html_tools import clean_text, labelled_html_value
from ..models import RunContext, SourceResult, SourceStatus
from .base import BaseAdapter, blocked_result
from .common import extract_deadline, make_raw, parse_date_text


class OracleHCMAdapter(BaseAdapter):
    def fetch(self, context: RunContext) -> SourceResult:
        config = self.spec.configuration
        api_url = str(config.get("api_url", self.spec.official_entry_url))
        page_size = int(config.get("page_size", 100))
        offset = 0
        records = []
        seen: set[str] = set()
        total: int | None = None
        warnings: list[str] = []
        errors: list[str] = []
        while True:
            url = self._page_url(api_url, page_size, offset)
            response = context.http_client.get(url, use_cache=True)
            if not response.ok:
                if not records:
                    return blocked_result(self.spec, response.error or f"Oracle request failed ({response.status_code})", source_url=url)
                errors.append(response.error or f"Oracle page failed at offset {offset}")
                break
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                return blocked_result(self.spec, f"Oracle response was not JSON: {exc}", source_url=url)
            page_total, requisitions = self._extract_requisitions(payload)
            if total is None:
                total = page_total
            if page_total is not None and total != page_total:
                warnings.append(f"Oracle TotalJobsCount changed during run ({total} -> {page_total})")
                total = max(total or 0, page_total)
            for requisition in requisitions:
                record = self._to_raw(requisition, context, url)
                key = record.source_record_id or record.apply_url_raw
                if key and key not in seen:
                    seen.add(key)
                    records.append(record)
            if total is None:
                break
            if total == 0 or len(seen) >= total:
                break
            if not requisitions:
                errors.append(f"Oracle returned no requisitions at offset {offset} before TotalJobsCount={total}")
                break
            offset += page_size

        self._enrich_details(records, context)
        if total is None:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append("Oracle response did not expose TotalJobsCount")
        elif len(seen) < total:
            status = SourceStatus.PARTIALLY_VERIFIED
            warnings.append(f"captured {len(seen)} unique Oracle IDs against TotalJobsCount={total}")
        else:
            status = SourceStatus.COMPLETE
        return self.result(
            method="official-api",
            raw=records,
            source_total=total,
            status=status,
            warnings=warnings,
            errors=errors,
            source_url=api_url,
            verification_method="primary-platform-listing",
        )

    @staticmethod
    def _page_url(url: str, limit: int, offset: int) -> str:
        url = re.sub(r"limit=\d+", f"limit={limit}", url, flags=re.I)
        url = re.sub(r"offset=\d+", f"offset={offset}", url, flags=re.I)
        return url

    @staticmethod
    def _extract_requisitions(payload: dict) -> tuple[int | None, list[dict]]:
        items = payload.get("items") if isinstance(payload, dict) else None
        first = items[0] if isinstance(items, list) and items else {}
        total_value = first.get("TotalJobsCount") if isinstance(first, dict) else None
        try:
            total = int(total_value) if total_value is not None else None
        except (TypeError, ValueError):
            total = None
        requisitions = first.get("requisitionList", []) if isinstance(first, dict) else []
        if isinstance(requisitions, dict):
            requisitions = requisitions.get("items", requisitions.get("results", []))
        if not isinstance(requisitions, list):
            requisitions = []
        return total, [item for item in requisitions if isinstance(item, dict)]

    def _to_raw(self, item: dict, context: RunContext, source_url: str):
        record_id = str(item.get("Id") or item.get("id") or item.get("RequisitionNumber") or "").strip()
        title = str(item.get("Title") or item.get("title") or "").strip()
        location = str(item.get("PrimaryLocation") or item.get("primaryLocation") or "").strip()
        description = str(item.get("ShortDescriptionStr") or item.get("shortDescription") or "").strip()
        deadline, closing_time = extract_deadline(description)
        if not deadline:
            deadline = parse_date_text(str(item.get("PostingEndDate") or ""))
        apply_url = str(self.spec.configuration.get("detail_url_template", "")).format(id=quote(record_id)) if record_id else source_url
        organization = str(self.spec.configuration.get("organization", "Nottingham City Council"))
        contract = str(item.get("ContractType") or item.get("AssignmentCategory") or "")
        work_pattern = str(item.get("WorkPattern") or "")
        salary = str(item.get("Salary") or "")
        if not contract:
            contract = self._first_type(description, ("permanent", "fixed term", "fixed-term", "temporary", "casual", "freelance"))
        if not work_pattern:
            work_pattern = self._first_type(description, ("full-time or part-time", "full-time", "full time", "part-time", "part time", "casual"))
        if not salary:
            salary_match = re.search(r"£[\d,]+(?:\s*(?:-|to)\s*£?[\d,]+)?(?:\s+per\s+(?:annum|hour))?", description, re.I)
            salary = salary_match.group(0) if salary_match else ""
        return make_raw(
            source_id=self.spec.source_id,
            source_url=source_url,
            record_id=record_id,
            title=title,
            organization=organization,
            location=location,
            deadline=deadline,
            closing_time=closing_time,
            contract=contract,
            work_pattern=work_pattern,
            salary=salary,
            apply_url=apply_url,
            reference=str(item.get("RequisitionNumber") or record_id),
            description=description,
            evidence={
                "oracle_id": record_id,
                "total_field": "TotalJobsCount",
                "organizations_facet": item.get("organizationsFacet", ""),
            },
        )

    @staticmethod
    def _first_type(text: str, values: tuple[str, ...]) -> str:
        lowered = text.casefold()
        for value in values:
            if value.casefold() in lowered:
                return value
        return ""

    def _enrich_details(self, records: list, context: RunContext) -> None:
        """Use the current advert only when the listing summary lacks policy fields."""

        for record in records:
            if record.closing_date_raw and record.location_raw:
                continue
            if not record.apply_url_raw or record.apply_url_raw == record.source_url:
                continue
            response = context.http_client.get(record.apply_url_raw, use_cache=True)
            if not response.ok:
                record.evidence["detail_fetch_error"] = response.error or f"HTTP {response.status_code}"
                continue
            text = clean_text(response.text)
            deadline, closing_time = extract_deadline(text)
            if deadline:
                record.closing_date_raw = deadline
            if closing_time:
                record.closing_time_raw = closing_time
            if not record.location_raw:
                record.location_raw = labelled_html_value(response.text, ("Location", "Primary location", "Work location"))
            record.contract_raw = record.contract_raw or self._first_type(text, ("permanent", "fixed term", "fixed-term", "temporary", "casual", "freelance"))
            record.work_pattern_raw = record.work_pattern_raw or self._first_type(text, ("full-time or part-time", "full-time", "full time", "part-time", "part time", "casual"))
            if not record.salary_raw:
                salary_match = re.search(r"£[\d,]+(?:\s*(?:-|to)\s*£?[\d,]+)?(?:\s+per\s+(?:annum|hour))?", text, re.I)
                record.salary_raw = salary_match.group(0) if salary_match else ""
            record.description_raw = f"{record.description_raw} {text}".strip()
