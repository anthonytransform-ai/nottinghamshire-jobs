"""Fetch, audit, consolidate and validate a weekly candidate run."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters.base import blocked_result
from .audit import anomaly_warnings, write_source_audit, write_history_snapshot
from .classify import JOB_AREAS, LOCATION_AREAS, classify_job_area, classify_location, load_classification_rules
from .csv_writer import write_csv
from .configuration import apply_resolution, apply_tracked_overrides, load_resolutions, load_tracked_overrides, resolution_key
from .dedupe import deduplicate
from .eligibility import evaluate
from .ingestion import load_source_results, write_structured_source_results
from .models import Exclusion, ReviewItem, RunContext, SourceResult, SourceStatus
from .normalise import normalized_vacancy
from .review import write_review_queue


class PipelineError(RuntimeError):
    pass


class JobUpdatePipeline:
    def __init__(self, context: RunContext) -> None:
        self.context = context
        self.context.run_dir = Path(self.context.run_dir)
        self.context.run_dir.mkdir(parents=True, exist_ok=True)
        if self.context.classification_rules is None:
            self.context.classification_rules = load_classification_rules()
        if not self.context.overrides:
            self.context.overrides = load_tracked_overrides(self.context.run_dir.parent.parent / "config" / "overrides.toml")

    def collect(self, source_ids: set[str] | None = None) -> list[SourceResult]:
        """Run only explicitly retained stable collectors.

        Normal weekly operation does not call this method: Codex researches
        agent-owned sources and supplies source_results.json.  Keeping the
        stable collector path explicit prevents a missing collector from
        being mistaken for a zero-result source.
        """

        if not self.context.live:
            raise PipelineError("stable collection is disabled for a non-live context")
        results: list[SourceResult] = []
        try:
            collectors = self.context.registry.collectors()
            if source_ids is not None:
                collectors = [collector for collector in collectors if collector.spec.source_id in source_ids]
            if not collectors:
                raise PipelineError("no requested stable collectors are configured")
            for adapter in collectors:
                try:
                    result = adapter.fetch(self.context)
                except Exception as exc:
                    # A retained collector failure is explicit; it cannot
                    # masquerade as an agent-researched zero-result source.
                    result = blocked_result(adapter.spec, f"adapter error: {type(exc).__name__}: {exc}")
                results.append(result)
        finally:
            self._close_resources()
        return results

    fetch = collect

    def load_results(self) -> list[SourceResult]:
        path = self.context.run_dir / "source_results.json"
        if not path.exists():
            raise PipelineError(f"no fetched source results at {path}; run fetch first")
        return load_source_results(path, self.context.registry, expected_date=self.context.date_checked)

    def build(self, results: list[SourceResult], *, output_path: Path | None = None) -> dict[str, Any]:
        normalized = []
        review_items: list[ReviewItem] = []
        exclusions: list[Exclusion] = []
        date_checked = self.context.date_checked.isoformat()
        resolutions = load_resolutions(self.context.run_dir / "review_resolutions.toml")
        for result in results:
            spec = self.context.registry.get(result.source_id)
            result.eligible_hint_count = 0
            result.exclusions = []
            for raw in result.raw_vacancies:
                decision_key = resolution_key(raw)
                apply_tracked_overrides(raw, self.context.overrides if isinstance(self.context.overrides, list) else [])
                apply_resolution(raw, resolutions.get(decision_key))
                location_area, location_reason, location_candidates = self._location_decision(raw)
                job_area, job_reason, job_candidates = self._job_area_decision(raw)
                decision = evaluate(
                    raw,
                    update_date=self.context.date_checked,
                    employer_type=spec.employer_type,
                    location_area=location_area,
                    job_area=job_area,
                    now=self.context.now,
                )
                if decision.included:
                    record = normalized_vacancy(
                        raw,
                        spec,
                        date_checked=date_checked,
                        location_area=location_area or "",
                        job_area=job_area or "",
                        closing_date=decision.closing_date,
                        verification_method=result.verification_method or "primary-platform-listing",
                    )
                    record.closing_time = decision.closing_time
                    normalized.append(record)
                    result.eligible_hint_count += 1
                    continue
                # Eligibility owns the distinction between a hard policy
                # exclusion and a genuinely ambiguous record. A hard
                # exclusion must not become a review item merely because its
                # location or role classifier has no answer (for example an
                # out-of-scope NHS advert returned by a broad search).
                if decision.review:
                    ambiguous_field, candidate_values = self._review_field(
                        decision.reason,
                        location_area=location_area,
                        location_candidates=location_candidates,
                        job_area=job_area,
                        job_candidates=job_candidates,
                    )
                    review_items.append(
                        ReviewItem(
                            source=result.source_name,
                            title=raw.title_raw,
                            organization=raw.advertised_employer_raw or raw.organization_raw or raw.host_organization_raw,
                            relevant_evidence={
                                "resolution_key": decision_key,
                                "location": raw.location_raw,
                                "description": raw.description_raw,
                                "apply_url": raw.apply_url_raw,
                                "closing_date": raw.closing_date_raw,
                                "source_record_id": raw.source_record_id,
                                "location_reason": location_reason,
                                "location_candidates": location_candidates,
                                "job_area_reason": job_reason,
                                "job_area_candidates": job_candidates,
                                "advertised_employer": raw.advertised_employer_raw,
                                "host_organization": raw.host_organization_raw,
                                "host_association_verified": raw.host_association_verified,
                                "host_association_type": raw.host_association_type,
                                "host_association_evidence": raw.host_association_evidence,
                            },
                            ambiguous_field=ambiguous_field,
                            candidate_values=candidate_values,
                            reason=decision.reason,
                            source_record_id=raw.source_record_id,
                            resolution_key=decision_key,
                        )
                    )
                else:
                    exclusion = Exclusion(
                        source_id=raw.source_id,
                        title=raw.title_raw,
                        organization=raw.organization_raw,
                        reason=decision.reason,
                        source_record_id=raw.source_record_id,
                        evidence=raw.evidence,
                    )
                    exclusions.append(exclusion)
                    result.exclusions.append(exclusion.to_dict())

        selected, duplicate_rows = deduplicate(normalized)
        for duplicate in duplicate_rows:
            exclusions.append(
                Exclusion(
                    source_id=duplicate["source_id"],
                    title=duplicate["title"],
                    organization=duplicate["organization"],
                    reason=duplicate["reason"],
                    evidence=duplicate,
                )
            )
        output = output_path or self.context.run_dir / "jobs.csv"
        data = write_csv(selected, output)
        validation = self._validate(data, date_checked)
        (self.context.run_dir / "validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
        (self.context.run_dir / "normalized_records.json").write_text(
            json.dumps([asdict(record) for record in selected], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (self.context.run_dir / "resolved_raw_records.json").write_text(
            json.dumps([raw.to_dict() for result in results for raw in result.raw_vacancies], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (self.context.run_dir / "exclusions.json").write_text(
            json.dumps([item.to_dict() for item in exclusions], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        write_review_queue(review_items, self.context.run_dir / "review_queue.json")
        write_source_audit(
            results,
            self.context.run_dir / "source_audit.json",
            self.context.run_dir / "source_audit.md",
        )
        anomalies = anomaly_warnings(
            results,
            candidate_row_count=len(selected),
            history_path=self.context.run_dir.parent / "history.json",
        )
        write_history_snapshot(
            results,
            candidate_row_count=len(selected),
            path=self.context.run_dir.parent / "history.json",
        )
        summary = {
            "date_checked": date_checked,
            "row_count": len(selected),
            "review_count": len(review_items),
            "exclusion_count": len(exclusions),
            "source_count": len(results),
            "mandatory_source_count": sum(1 for result in results if result.mandatory),
            "sha256": validation["sha256"],
            "validation": validation,
            "anomalies": anomalies,
            "output": str(output),
        }
        (self.context.run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (self.context.run_dir / "pr_body.md").write_text(self._pr_body(summary, results, review_items), encoding="utf-8")
        return summary

    @staticmethod
    def _review_field(
        reason: str,
        *,
        location_area: str | None,
        location_candidates: list[str],
        job_area: str | None,
        job_candidates: list[str],
    ) -> tuple[str, list[str]]:
        lowered = reason.casefold()
        if "detail" in lowered or "verification" in lowered:
            return "detail_verification", []
        if "host" in lowered or "association" in lowered or "agency" in lowered:
            return "host_association", []
        if "location" in lowered or "base" in lowered or "nottinghamshire" in lowered:
            return "location_area", location_candidates
        if "job-area" in lowered or "job area" in lowered or "classification" in lowered:
            return "job_area", job_candidates
        if "closing" in lowered or "deadline" in lowered or "date" in lowered or "time" in lowered:
            return "closing_date", []
        if "application url" in lowered or "source url" in lowered or "url" in lowered:
            return "apply_url", []
        if "employer" in lowered:
            return "employer", []
        if location_area is None:
            return "location_area", location_candidates
        if job_area is None:
            return "job_area", job_candidates
        return "policy", []

    def run(self, *, output_path: Path | None = None) -> dict[str, Any]:
        results = self.load_results()
        return self.build(results, output_path=output_path)

    def diagnostics(self) -> dict[str, Any]:
        """Return local readiness information without contacting sources."""

        collectors = self.context.registry.collectors()
        return {
            "live": False,
            "network_requests": 0,
            "source_count": len(self.context.registry.sources),
            "mandatory_source_count": len(self.context.registry.mandatory),
            "agent_researched_source_count": len(self.context.registry.agent_researched),
            "stable_collector_count": len(collectors),
            "ingestion_schema_version": 1,
        }

    def _close_resources(self) -> None:
        for resource in (self.context.browser, self.context.http_client):
            close = getattr(resource, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    # Cleanup must not erase the source audit produced by the run.
                    pass

    def _write_source_results(self, results: list[SourceResult]) -> None:
        write_structured_source_results(
            results,
            self.context.run_dir / "source_results.json",
            date_checked=self.context.date_checked,
        )

    def _location_decision(self, raw):
        supplied = str(raw.location_area_raw or raw.evidence.get("location_area", "")).strip()
        override = str(raw.evidence.get("location_area_override", "")).strip()
        if override:
            supplied = override
        if supplied:
            if supplied not in LOCATION_AREAS:
                return None, "agent supplied an invalid location-area value", []
            return supplied, "agent-supplied controlled location-area decision", [supplied]
        return classify_location(raw.location_raw, raw.description_raw, rules=self.context.classification_rules)

    def _job_area_decision(self, raw):
        supplied = str(raw.job_area_raw or raw.evidence.get("job_area", "")).strip()
        override = str(raw.evidence.get("job_area_override", "")).strip()
        if override:
            supplied = override
        if supplied:
            if supplied not in JOB_AREAS:
                return None, "agent supplied an invalid job-area value", []
            return supplied, "agent-supplied controlled job-area decision", [supplied]
        return classify_job_area(raw.title_raw, raw.description_raw, rules=self.context.classification_rules)

    @staticmethod
    def _validate(data: bytes, date_checked: str) -> dict[str, Any]:
        try:
            from scripts.validate_job_update import validate_csv_bytes

            return validate_csv_bytes(data, declared_date=date_checked)
        except Exception as exc:
            raise PipelineError(f"generated candidate failed the existing CSV validator: {exc}") from exc

    @staticmethod
    def _pr_body(summary: dict[str, Any], results: list[SourceResult], review_items: list[ReviewItem]) -> str:
        limited = [result for result in results if result.status in {SourceStatus.PARTIALLY_VERIFIED, SourceStatus.BLOCKED}]
        lines = [
            f"# Nottinghamshire Job Update candidate — {summary['date_checked']}",
            "",
            f"- Eligible vacancies: **{summary['row_count']}**",
            f"- Closing-date policy: **verified fixed deadline on or after {summary['date_checked']}; no maximum future horizon**",
            f"- Candidate CSV: `{summary['output']}`",
            f"- SHA-256: `{summary['sha256']}`",
            "- Publication: manual one-file `jobs.csv` PR; no automatic merge or direct write to `main`.",
            "",
            "## Mandatory source limitations",
            "",
        ]
        if limited:
            lines.extend(
                f"- **{result.source_name}** — {result.status.value}: {('; '.join(result.warnings + result.errors)) or 'see source audit'}"
                for result in limited
            )
        else:
            lines.append("- None.")
        lines.extend(
            [
                "",
                f"- Structured review queue items: **{len(review_items)}**",
                "- Vacancies may close early or be withdrawn after this check.",
                "",
            "Source evidence was supplied by Codex and deterministically rebuilt; the implementation deliberately does not auto-merge this candidate.",
            ]
        )
        return "\n".join(lines) + "\n"
