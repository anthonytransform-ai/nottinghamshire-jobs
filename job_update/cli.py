"""Command-line boundary for agent evidence, stable collection and build."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .http_client import HttpClient
from .ingestion import IngestionError, validate_source_results
from .models import RunContext
from .pipeline import JobUpdatePipeline, PipelineError
from .registry import DEFAULT_REGISTRY_PATH, SourceRegistry
from .review import write_resolution, write_resolution_template
from .timezone import london_now


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = PROJECT_ROOT / ".job-update-runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nottinghamshire Jobs agent-first weekly evidence engine")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH, help="TOML source registry")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sources", help="list every agent-facing source")

    ingest = sub.add_parser("ingest", help="validate and copy a Codex source_results.json into a dated run")
    ingest.add_argument("--date", dest="date_checked", required=True)
    ingest.add_argument("--input", type=Path, required=True)

    for name in ("build", "run"):
        command = sub.add_parser(name, help="build deterministically from dated structured source evidence; never retrieves sources")
        command.add_argument("--date", dest="date_checked", required=True)
        command.add_argument("--output", type=Path, help="optional candidate CSV path")

    collect = sub.add_parser("collect", help="explicitly run retained stable collectors only")
    collect.add_argument("--date", dest="date_checked", required=True)
    collect.add_argument("--source-id", action="append", dest="source_ids", help="stable source ID; repeatable")

    sub.add_parser("doctor", help="report local registry and ingestion readiness without network access")

    audit = sub.add_parser("audit", help="print a saved source audit")
    audit.add_argument("--date", dest="date_checked", required=True)

    review = sub.add_parser("review", help="inspect or resolve the run-local review queue")
    review.add_argument("--date", dest="date_checked", required=True)
    review.add_argument("--write-template", action="store_true")
    review.add_argument("--key")
    review.add_argument("--field", choices=(
        "location_area",
        "job_area",
        "advertised_employer",
        "host_organization",
        "host_association_verified",
        "host_association_type",
        "host_association_evidence",
        "policy",
    ))
    review.add_argument("--value")

    validate = sub.add_parser("validate", help="run the existing whole-file CSV validator")
    validate.add_argument("csv_path", type=Path)
    validate.add_argument("--date-checked")
    validate.add_argument("--require-today", action="store_true")
    return parser


def _date(value: str | None) -> date:
    return date.fromisoformat(value) if value else london_now().date()


def _context(registry: SourceRegistry, update_date: date, run_dir: Path, *, live: bool = False) -> RunContext:
    return RunContext(
        date_checked=update_date,
        run_dir=run_dir,
        registry=registry,
        http_client=HttpClient() if live else None,
        live=live,
        now=london_now(),
    )


def _print_sources(registry: SourceRegistry) -> None:
    print(f"Configured sources: {len(registry.sources)} ({len(registry.mandatory)} mandatory)")
    for source in registry.sources:
        marker = "mandatory" if source.mandatory else "optional"
        collector = source.collector or "agent"
        print(f"{source.source_id}\t{marker}\t{source.employer_type}\t{source.source_type}\t{collector}\t{source.display_name}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = SourceRegistry.load(args.registry)
        if args.command == "sources":
            _print_sources(registry)
            return 0
        if args.command == "doctor":
            print(json.dumps(JobUpdatePipeline(_context(registry, london_now().date(), RUNS_ROOT / "doctor", live=False)).diagnostics(), sort_keys=True))
            return 0
        if args.command == "validate":
            from scripts.validate_job_update import validate_csv_bytes

            result = validate_csv_bytes(
                args.csv_path.read_bytes(),
                declared_date=args.date_checked,
                require_today=args.require_today,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == "audit":
            path = RUNS_ROOT / args.date_checked / "source_audit.json"
            if not path.exists():
                raise PipelineError(f"source audit not found: {path}")
            print(path.read_text(encoding="utf-8"))
            return 0
        if args.command == "review":
            run_dir = RUNS_ROOT / args.date_checked
            queue_path = run_dir / "review_queue.json"
            if not queue_path.exists():
                raise PipelineError(f"review queue not found: {queue_path}")
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            if args.write_template:
                from .models import ReviewItem

                write_resolution_template([ReviewItem(**item) for item in queue], run_dir / "review_resolutions.toml")
            if any(value is not None for value in (args.key, args.field, args.value)):
                if not (args.key and args.field and args.value is not None):
                    raise PipelineError("--key, --field and --value must be supplied together")
                value = args.value
                if args.field == "host_association_verified":
                    if value.casefold() not in {"true", "false"}:
                        raise PipelineError("host_association_verified must be true or false")
                    value = value.casefold() == "true"
                write_resolution(run_dir / "review_resolutions.toml", key=args.key, field=args.field, value=value)
            print(json.dumps({"date_checked": args.date_checked, "review_count": len(queue), "queue": str(queue_path)}, sort_keys=True))
            return 0
        if args.command == "ingest":
            requested_date = _date(args.date_checked)
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            summary = validate_source_results(payload, registry, expected_date=requested_date)
            run_dir = RUNS_ROOT / requested_date.isoformat()
            run_dir.mkdir(parents=True, exist_ok=True)
            destination = run_dir / "source_results.json"
            destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps({**summary, "output": str(destination)}, sort_keys=True))
            return 0
        requested_date = _date(args.date_checked)
        run_dir = RUNS_ROOT / requested_date.isoformat()
        if args.command in {"build", "run"}:
            pipeline = JobUpdatePipeline(_context(registry, requested_date, run_dir, live=False))
            print(json.dumps(pipeline.build(pipeline.load_results(), output_path=args.output), sort_keys=True))
            return 0
        if args.command == "collect":
            pipeline = JobUpdatePipeline(_context(registry, requested_date, run_dir, live=True))
            results = pipeline.collect(set(args.source_ids) if args.source_ids else None)
            destination = run_dir / "stable_collector_results.json"
            from .ingestion import write_structured_source_results

            write_structured_source_results(results, destination, date_checked=requested_date)
            print(json.dumps({
                "date_checked": requested_date.isoformat(),
                "source_count": len(results),
                "source_ids": [result.source_id for result in results],
                "output": str(destination),
            }, sort_keys=True))
            return 0
    except (OSError, ValueError, IngestionError, PipelineError) as exc:
        print(f"job_update failed: {exc}")
        return 1
    return 1
