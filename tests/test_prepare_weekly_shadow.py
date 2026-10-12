from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from scripts.collect_weekly_jobs import PILOTS
from scripts.prepare_weekly_shadow import build_shadow, finish_source, identify_baseline_pilot, serialize_rows
from scripts.validate_job_update import SUMMARY_COLUMNS, parse_csv_bytes
from scripts.weekly_job_update import RawCandidate, SourceRun, SourceRunStatus, WorkingStateStore, load_registry


def row(title="Example Role"):
    result = {key: "" for key in SUMMARY_COLUMNS}
    result.update(organization="Example Employer", job_title=title, apply_url="https://example.org/jobs/1", date_checked="2026-10-12", job_summary="Source-grounded role duties.")
    return result


def candidate(source_id=PILOTS[0]):
    return RawCandidate(source_id=source_id, source_family="education", source_reference="REF1", list_url="https://example.org/jobs", detail_url="https://example.org/jobs/1", collected_at="2026-10-12T10:00:00Z", collection_method="fixture")


def decision():
    return dict(identity="REF1", outcome="include", row=row(), reason="Reviewed live current source evidence", audit=dict(shared_apply_url=False))


class ShadowPreparationTests(unittest.TestCase):
    def test_no_candidate_can_be_left_unfinished_or_judged_twice(self):
        c = candidate()
        for decisions in ([], [decision(), decision()], [dict(identity="wrong", outcome="exclude", reason="Excluded")]):
            with self.assertRaises(ValueError):
                finish_source(PILOTS[0], [c], decisions)
        self.assertEqual([row()], finish_source(PILOTS[0], [c], [decision()]))

    def test_blank_summary_and_shared_route_need_explicit_agent_reasons(self):
        d = decision()
        d["row"]["job_summary"] = ""
        with self.assertRaises(ValueError):
            finish_source(PILOTS[0], [candidate()], [d])
        d["audit"]["blank_summary_reason"] = "Detail returned a genuine access limitation"
        self.assertEqual(1, len(finish_source(PILOTS[0], [candidate()], [d])))
        d["audit"]["shared_apply_url"] = True
        with self.assertRaises(ValueError):
            finish_source(PILOTS[0], [candidate()], [d])

    def test_baseline_nhs_source_matching_does_not_remove_other_trusts(self):
        registry = load_registry()
        r = row()
        r.update(organization="Sherwood Forest Hospitals NHS Foundation Trust", apply_url="https://www.healthjobsuk.com/job/UK/Nottinghamshire/Example/Other_Trust/Example-v2")
        self.assertIsNone(identify_baseline_pilot(r, registry))
        r["organization"] = "Nottingham University Hospitals NHS Trust"
        self.assertEqual(PILOTS[2], identify_baseline_pilot(r, registry))

    def test_round_trip_exact_csv_quotes_without_editorial_reclassification(self):
        r = row('Role, with "quotes"')
        r["job_summary"] = 'Source text, with "quoted" content.'
        records, columns = parse_csv_bytes(serialize_rows([r]))
        self.assertEqual(SUMMARY_COLUMNS, columns)
        self.assertEqual([r], records)

    def test_shadow_holds_nonpilot_fields_constant_and_validates_exact_bytes(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            store = WorkingStateStore(root)
            runs = []
            for source_id in PILOTS:
                run = SourceRun(source_id)
                run.begin("2026-10-12T10:00:00Z")
                run.complete(SourceRunStatus.OK, candidate_count=1, finished_at="2026-10-12T10:01:00Z", normal_collection_completed=True)
                runs.append(run)
                store.append_raw_candidate(candidate(source_id))
                (root / f"{source_id}-decisions.json").write_text(json.dumps([decision()]), encoding="utf-8")
            store.save_source_runs(runs)
            trusted = row("Trusted non-pilot role")
            baseline_pilot = row("Old pilot role")
            baseline_pilot.update(organization="University of Nottingham", apply_url="https://jobs.nottingham.ac.uk/vacancy.aspx?ref=old")
            baseline_bytes = serialize_rows([trusted, baseline_pilot])
            content, manifest = build_shadow(root, baseline_bytes, "2026-10-12")
            records, _ = parse_csv_bytes(content)
            self.assertIn(trusted, records)
            self.assertNotIn(baseline_pilot, records)
            self.assertEqual(4, manifest["validation"]["row_count"])
            self.assertEqual(1, manifest["retained_nonpilot_rows"])
            self.assertFalse(manifest["nonpilot_freshly_collected"])
            import hashlib
            self.assertEqual(hashlib.sha256(content).hexdigest(), manifest["validation"]["sha256"])
            self.assertEqual(baseline_bytes, serialize_rows([trusted, baseline_pilot]))


if __name__ == "__main__":
    unittest.main()
