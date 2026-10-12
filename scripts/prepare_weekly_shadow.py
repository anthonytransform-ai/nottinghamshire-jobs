"""Serialize explicitly judged pilot rows into an authorised controlled shadow.

This is a local proof tool, not publication or an eligibility engine. The agent
must finish one source's decisions before moving to the next. Non-pilot rows are
held constant from the explicitly approved same-day trusted baseline.
"""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from scripts.collect_weekly_jobs import PILOTS
from scripts.participant_job_policy import validate_participant_url
from scripts.validate_job_update import SUMMARY_COLUMNS, parse_csv_bytes, validate_csv_bytes
from scripts.weekly_job_update import DEFAULT_WORKING_ROOT, SourceRunStatus, WorkingStateStore, load_registry


def candidate_identity(candidate):
    return candidate.source_platform_id or candidate.source_reference


def finish_source(source_id, candidates, decisions):
    """Require an explicit include/exclude disposition for each captured identity."""
    identities = {candidate_identity(c) for c in candidates if c.source_id == source_id}
    supplied = [d.get("identity") for d in decisions]
    if len(supplied) != len(set(supplied)) or set(supplied) != identities:
        raise ValueError(f"{source_id}: decisions must cover each raw identity exactly once")
    rows = []
    for decision in decisions:
        if not str(decision.get("reason", "")).strip():
            raise ValueError("Each judgement requires its row-level reason")
        if decision.get("outcome") == "exclude":
            continue
        if decision.get("outcome") != "include":
            raise ValueError("Each judgement must explicitly include or exclude")
        row = decision.get("row", {})
        if set(row) != set(SUMMARY_COLUMNS) or not all(isinstance(v, str) for v in row.values()):
            raise ValueError("Included rows must contain the complete 16 string fields")
        validate_participant_url(load_registry().get(source_id), row["apply_url"])
        audit = decision.get("audit", {})
        if not isinstance(audit.get("shared_apply_url"), bool):
            raise ValueError("Agent must explicitly assess the participant-facing destination")
        if audit["shared_apply_url"] and not audit.get("shared_apply_url_reason", "").strip():
            raise ValueError("Shared destination requires its genuine source limitation")
        if not row["job_summary"].strip() and not audit.get("blank_summary_reason", "").strip():
            raise ValueError("Blank summary requires its genuine detail limitation")
        rows.append(row)
    return rows


def identify_baseline_pilot(row, registry):
    """Match the approved baseline portion through known source/employer evidence."""
    for source_id in PILOTS:
        source = registry.get(source_id)
        host = urlparse(source.fixed_route).netloc
        urls = (row["apply_url"], row["source_url"])
        if not any(urlparse(url).netloc == host for url in urls):
            continue
        if source_id != PILOTS[2] or row["organization"] in {source.name, source.name + " NHS Trust"} or any("/Nottingham_University_Hospitals_NHS_Trust/" in url for url in urls):
            return source_id
    if row["organization"] in {registry.get(s).name for s in PILOTS} | {registry.get(PILOTS[2]).name + " NHS Trust"}:
        raise ValueError("Baseline pilot employer has an unrecognised source route; inspect before removal")
    return None


def serialize_rows(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=SUMMARY_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(sorted(rows, key=lambda r: (r["organization"].casefold(), r["job_title"].casefold(), r["location"].casefold(), r["job_reference"], r["apply_url"])))
    return stream.getvalue().encode("utf-8")


def build_shadow(root, baseline_bytes, checked_date):
    registry = load_registry()
    baseline, columns = parse_csv_bytes(baseline_bytes)
    if columns != SUMMARY_COLUMNS or any(row["date_checked"] != checked_date for row in baseline):
        raise ValueError("Controlled shadow requires the approved same-day 16-column baseline")
    store = WorkingStateStore(root)
    runs = {r.source_id: r for r in store.load_source_runs()}
    candidates = store.load_raw_candidates()
    removed = {source_id: [] for source_id in PILOTS}
    retained = []
    for row in baseline:
        source_id = identify_baseline_pilot(row, registry)
        (removed[source_id] if source_id else retained).append(row)
    pilot_rows = []
    source_reports = []
    decisions_all = []
    for source_id in [s.source_id for s in registry.sources if s.source_id in PILOTS]:
        run = runs.get(source_id)
        if run is None or run.status in {SourceRunStatus.RUNNING, SourceRunStatus.NOT_STARTED}:
            raise ValueError(f"{source_id}: collection outcome must be explicitly recorded")
        decisions = json.loads((Path(root) / f"{source_id}-decisions.json").read_text(encoding="utf-8"))
        fresh = finish_source(source_id, candidates, decisions)
        if any(row["date_checked"] != checked_date for row in fresh):
            raise ValueError("Fresh pilot rows must use the common checked date")
        source_reports.append(dict(source_id=source_id, collection=run.to_mapping(), baseline_rows=len(removed[source_id]), fresh_rows=len(fresh), excluded=sum(d["outcome"] == "exclude" for d in decisions)))
        decisions_all.extend(decisions)
        pilot_rows.extend(fresh)
    # Dedupe is an explicit agent judgement, not an automatic title/URL heuristic.
    rows = retained + pilot_rows
    csv_bytes = serialize_rows(rows)
    validation = validate_csv_bytes(csv_bytes)
    fixed_routes = {s.fixed_route for s in registry.sources}
    inherited_exceptions = [dict(organization=r["organization"], job_title=r["job_title"], apply_url=r["apply_url"], job_reference=r["job_reference"], shared_apply_url=r["apply_url"] in fixed_routes, blank_summary=not r["job_summary"].strip(), reason="Inherited unchanged from Anthony-approved same-day trusted non-pilot baseline. Public CSV does not retain the original limitation reason; no fresh non-pilot re-verification is claimed.") for r in retained if r["apply_url"] in fixed_routes or not r["job_summary"].strip()]
    pilot_shared = sum(d["outcome"] == "include" and d["audit"]["shared_apply_url"] for d in decisions_all)
    baseline_shared = sum(r["apply_url"] in fixed_routes for r in retained)
    manifest = dict(mode="controlled_integration_shadow", checked_date=checked_date, registry_id=registry.registry_id, registry_source_order=[s.source_id for s in registry.sources], baseline_sha256=sha256(baseline_bytes).hexdigest(), baseline_rows=len(baseline), retained_nonpilot_rows=len(retained), nonpilot_freshly_collected=False, pilot_fresh_rows=len(pilot_rows), sources=source_reports, validation=validation, audit=dict(total_rows=len(rows), job_specific_apply_urls=len(rows)-baseline_shared-pilot_shared, shared_apply_urls=baseline_shared+pilot_shared, nonblank_summaries=sum(bool(r["job_summary"].strip()) for r in rows), blank_summaries=sum(not r["job_summary"].strip() for r in rows), fresh_pilot_shared_apply_urls=pilot_shared, fresh_pilot_blank_summaries=sum(not r["job_summary"].strip() for r in pilot_rows), inherited_exceptions=inherited_exceptions, exception_scope="Pilot exceptions freshly audited; non-pilot exceptions inherited under the controlled comparison boundary"), public_jobs_csv_changed=False, production_adoption=False)
    store.save_final_candidates(rows)
    return csv_bytes, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--checked-date", required=True)
    parser.add_argument("--baseline", type=Path, default=Path(__file__).resolve().parents[1] / "jobs.csv")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.run) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.checked_date):
        parser.error("Use a simple named run directory and ISO checked date")
    root = DEFAULT_WORKING_ROOT / args.run
    content, manifest = build_shadow(root, args.baseline.read_bytes(), args.checked_date)
    (root / "shadow-jobs.csv").write_bytes(content)
    (root / "shadow-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("mode", "baseline_rows", "retained_nonpilot_rows", "pilot_fresh_rows", "validation")}, indent=2))


if __name__ == "__main__":
    main()
