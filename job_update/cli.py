"""Command-line operator interface for weekly runs."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .browser import BrowserClient
from .http_client import HttpClient
from .models import RunContext
from .pipeline import JobUpdatePipeline, PipelineError
from .registry import DEFAULT_REGISTRY_PATH, SourceRegistry
from .review import write_resolution, write_resolution_template
from .timezone import london_now


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = PROJECT_ROOT / ".job-update-runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nottinghamshire Jobs weekly vacancy update engine")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH, help="TOML source registry")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list every configured source")

    for name, help_text in (
        ("fetch", "fetch all sources and write raw/audit artefacts"),
        ("run", "fetch, build, validate and write a PR-ready shadow candidate"),
        ("doctor", "run local source diagnostics; use --live for real public retrieval"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--date", dest="date_checked", default=None, help="Europe/London update date (YYYY-MM-DD)")
        command.add_argument("--no-browser", action="store_true", help="disable Playwright fallback")
        command.add_argument("--browser-executable", default=None, help="optional Chromium/Edge executable path for Playwright")
        if name == "run":
            command.add_argument("--output", type=Path, help="optional candidate CSV path; default is run artefact directory")
        if name == "doctor":
            command.add_argument("--live", action="store_true", help="perform public HTTP retrieval")

    build = sub.add_parser("build", help="build from an existing fetched run without refetching")
    build.add_argument("--date", dest="date_checked", required=True, help="run date whose artefacts should be built")
    build.add_argument("--output", type=Path, help="optional candidate CSV path")

    audit = sub.add_parser("audit", help="print a saved source audit")
    audit.add_argument("--date", dest="date_checked", required=True, help="run date")

    review = sub.add_parser("review", help="inspect or resolve the run-local review queue")
    review.add_argument("--date", dest="date_checked", required=True, help="run date")
    review.add_argument("--write-template", action="store_true", help="write review_resolutions.toml template")
    review.add_argument("--key", help="stable resolution key from review_queue.json")
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
    review.add_argument("--value", help="reviewed value for --field")

    validate = sub.add_parser("validate", help="run the existing whole-file CSV validator")
    validate.add_argument("csv_path", type=Path)
    validate.add_argument("--date-checked")
    validate.add_argument("--require-today", action="store_true")
    return parser


def _date(value: str | None) -> date:
    return date.fromisoformat(value) if value else london_now().date()


def _context(
    registry: SourceRegistry,
    update_date: date,
    *,
    no_browser: bool,
    live: bool,
    run_dir: Path,
    browser_executable: str | None = None,
) -> RunContext:
    return RunContext(
        date_checked=update_date,
        run_dir=run_dir,
        http_client=HttpClient(),
        browser=BrowserClient(executable_path=browser_executable),
        registry=registry,
        live=live,
        allow_browser=not no_browser,
        now=london_now(),
    )


def _print_sources(registry: SourceRegistry) -> None:
    print(f"Configured sources: {len(registry.sources)} ({len(registry.mandatory)} mandatory)")
    for source in registry.sources:
        marker = "mandatory" if source.mandatory else "optional"
        print(f"{source.source_id}\t{marker}\t{source.employer_type}\t{source.adapter}\t{source.display_name}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = SourceRegistry.load(args.registry)
        if args.command == "sources":
            _print_sources(registry)
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

                items = [ReviewItem(**item) for item in queue]
                write_resolution_template(items, run_dir / "review_resolutions.toml")
            if any(value is not None for value in (args.key, args.field, args.value)):
                if not (args.key and args.field and args.value is not None):
                    raise PipelineError("--key, --field and --value must be supplied together")
                value = args.value
                if args.field == "host_association_verified":
                    if value.casefold() not in {"true", "false"}:
                        raise PipelineError("host_association_verified must be true or false")
                    value = value.casefold() == "true"
                write_resolution(run_dir / "review_resolutions.toml", key=args.key, field=args.field, value=value)
            print(json.dumps({
                "date_checked": args.date_checked,
                "review_count": len(queue),
                "queue": str(queue_path),
                "resolutions": str(run_dir / "review_resolutions.toml"),
            }, sort_keys=True))
            return 0

        update_date = _date(getattr(args, "date_checked", None))
        run_dir = RUNS_ROOT / update_date.isoformat()
        if args.command == "build":
            context = _context(registry, update_date, no_browser=True, live=False, run_dir=run_dir)
            summary = JobUpdatePipeline(context).build(
                JobUpdatePipeline(context).load_results(),
                output_path=args.output,
            )
            print(json.dumps(summary, sort_keys=True))
            return 0
        live = args.command != "doctor" or bool(getattr(args, "live", False))
        context = _context(
            registry,
            update_date,
            no_browser=getattr(args, "no_browser", False),
            live=live,
            run_dir=run_dir,
            browser_executable=getattr(args, "browser_executable", None),
        )
        pipeline = JobUpdatePipeline(context)
        if args.command == "fetch" or args.command == "doctor":
            if args.command == "doctor" and not args.live:
                print(json.dumps(pipeline.diagnostics(), sort_keys=True))
                pipeline._close_resources()
                return 0
            results = pipeline.fetch()
            summary = {
                "date_checked": update_date.isoformat(),
                "source_count": len(results),
                "mandatory_source_count": sum(1 for result in results if result.mandatory),
                "statuses": {result.source_id: result.status.value for result in results},
                "run_dir": str(run_dir),
            }
            print(json.dumps(summary, sort_keys=True))
            return 0
        summary = pipeline.run(output_path=args.output)
        print(json.dumps(summary, sort_keys=True))
        return 0
    except (OSError, ValueError, PipelineError) as exc:
        print(f"job_update failed: {exc}")
        return 1
