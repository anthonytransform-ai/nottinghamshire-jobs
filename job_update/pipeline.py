"""Fetch, audit, consolidate and validate a weekly candidate run."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters.base import blocked_result
from .audit import anomaly_warnings, write_source_audit
from .classify import classify_job_area, classify_location
from .csv_writer import write_csv
from .dedupe import deduplicate
from .eligibility import evaluate
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

    def fetch(self) -> list[SourceResult]:
        results: list[SourceResult] = []
        for adapter in self.context.registry.adapters():
            try:
                result = adapter.fetch(self.context)
            except Exception as exc:
                # One broken source must not erase the mandatory audit row.
                result = blocked_result(adapter.spec, f"adapter error: {type(exc).__name__}: {exc}")
            results.append(result)
        self._write_source_results(results)
        self._write_raw_records(results)
        write_source_audit(
            results,
            self.context.run_dir / "source_audit.json",
            self.context.run_dir / "source_audit.md",
        )
        return results

    def load_results(self) -> list[SourceResult]:
        path = self.context.run_dir / "source_results.json"
        if not path.exists():
            raise PipelineError(f"no fetched source results at {path}; run fetch first")
        values = json.loads(path.read_text(encoding="utf-8"))
        return [SourceResult.from_dict(item) for item in values]

    def build(self, results: list[SourceResult], *, output_path: Path | None = None) -> dict[str, Any]:
        normalized = []
        review_items: list[ReviewItem] = []
        exclusions: list[Exclusion] = []
        date_checked = self.context.date_checked.isoformat()
        for result in results:
            spec = self.context.registry.get(result.source_id)
            result.eligible_hint_count = 0
            result.exclusions = []
            for raw in result.raw_vacancies:
                location_area, location_reason, location_candidates = classify_location(
                    raw.location_raw,
                    raw.description_raw,
                    str(raw.evidence.get("location_area_override", "")),
                )
                job_area, job_reason, job_candidates = classify_job_area(
                    raw.title_raw,
                    raw.description_raw,
                    str(raw.evidence.get("job_area_override", "")),
                )
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
                if decision.review or location_area is None or job_area is None:
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
                            organization=raw.organization_raw,
                            relevant_evidence={
                                "location": raw.location_raw,
                                "description": raw.description_raw,
                                "apply_url": raw.apply_url_raw,
                                "closing_date": raw.closing_date_raw,
                                "source_record_id": raw.source_record_id,
                                "location_reason": location_reason,
                                "location_candidates": location_candidates,
                                "job_area_reason": job_reason,
                                "job_area_candidates": job_candidates,
                            },
                            ambiguous_field=ambiguous_field,
                            candidate_values=candidate_values,
                            reason=decision.reason,
                            source_record_id=raw.source_record_id,
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
        anomalies = anomaly_warnings(results, candidate_row_count=len(selected))
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
        results = self.fetch()
        return self.build(results, output_path=output_path)

    def _write_source_results(self, results: list[SourceResult]) -> None:
        (self.context.run_dir / "source_results.json").write_text(
            json.dumps([result.to_dict() for result in results], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _write_raw_records(self, results: list[SourceResult]) -> None:
        records = [raw.to_dict() for result in results for raw in result.raw_vacancies]
        (self.context.run_dir / "raw_records.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

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
            f"- Closing-date window: **{summary['date_checked']} through +56 calendar days inclusive**",
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
                "The implementation deliberately does not auto-merge this candidate.",
            ]
        )
        return "\n".join(lines) + "\n"
