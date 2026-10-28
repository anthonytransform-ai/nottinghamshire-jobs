from contextlib import redirect_stdout
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.participant_job_policy import (
    eligibility_review_flags, main, participant_destination, quality_review_findings,
    salary_review_flags, summary_review_flags, text_review_flags, validate_participant_url,
)
from scripts.prepare_weekly_shadow import finish_source
from scripts.validate_job_update import LEGACY_COLUMNS, SUMMARY_COLUMNS, validate_csv_bytes
from scripts.weekly_job_update import RawCandidate, load_registry


class ParticipantPolicyTests(unittest.TestCase):
    def test_explicit_internal_only_is_reviewed_without_excluding_internal_rotation(self):
        for title in ("Market Assistant (internal vacancy only)",
                      "Waste Loader (Internal Vacancy Only)",
                      "Systems and Customer Relations Manager (Internal Vacancy Only)"):
            self.assertEqual(["explicit_internal_only_requires_eligibility_review"], eligibility_review_flags(title))
        self.assertEqual([], eligibility_review_flags("Speech & Language Therapist internal rotation"))
        self.assertEqual([], eligibility_review_flags("Internal Auditor"))

    def test_all_six_itrent_sources_use_their_own_board_for_session_bound_detail(self):
        for source in load_registry().sources:
            if source.method != "itrent":
                continue
            with self.subTest(source=source.source_id):
                detail = source.fixed_route + "&VACANCY_ID=observed&USESSION=transient"
                self.assertEqual(source.fixed_route, participant_destination(source, detail))
                with self.assertRaisesRegex(ValueError, "USESSION"):
                    validate_participant_url(source, detail)
                validate_participant_url(source, source.fixed_route)

    def test_usession_is_rejected_even_if_empty_or_case_varies(self):
        source = load_registry().get("west-nottinghamshire-college")
        for query in ("&usession=", "&USeSsIoN=abc"):
            with self.assertRaises(ValueError):
                validate_participant_url(source, source.fixed_route + query)

    def test_stable_direct_route_requires_positive_fresh_session_evidence(self):
        source = load_registry().get("bassetlaw-district-council")
        observed = source.fixed_route + "&VACANCY_ID=observed"
        self.assertEqual(source.fixed_route, participant_destination(source, observed))
        self.assertEqual(observed, participant_destination(source, observed, fresh_session_usable=True))

    def test_known_summary_defects_are_flags_not_validator_rules(self):
        self.assertIn("employer_branding", summary_review_flags("Build a Rewarding Career. Doing things differently."))
        self.assertIn("requirements_first", summary_review_flags("Qualified Teacher Status (QTS). Degree in History."))
        self.assertIn("metadata_first", summary_review_flags("Contract: Permanent. Working Hours: 37."))
        # A short factual summary is reviewable, not rejected by word count.
        self.assertEqual(["short_requires_semantic_review"], summary_review_flags("Teach History at Key stage 4 in a full-time permanent role."))

    def test_row_finishing_enforces_itrent_link_policy_before_candidate_serialization(self):
        source = load_registry().get("bassetlaw-district-council")
        candidate = RawCandidate(source_id=source.source_id, source_family=source.family,
            source_platform_id="observed", list_url=source.fixed_route,
            collected_at="2026-10-12T20:00:00Z", collection_method="fixture")
        row = {key: "" for key in SUMMARY_COLUMNS}
        row["apply_url"] = source.fixed_route + "&VACANCY_ID=observed&USESSION=transient"
        decision = dict(identity="observed", outcome="include", row=row,
            reason="Retained current list evidence", audit=dict(shared_apply_url=True,
                shared_apply_url_reason="Fresh-session detail blocked", blank_summary_reason="E0227SECURITY"))
        with self.assertRaisesRegex(ValueError, "USESSION"):
            finish_source(source.source_id, [candidate], [decision])
        row["apply_url"] = source.fixed_route
        self.assertEqual([row], finish_source(source.source_id, [candidate], [decision]))


class AdvisoryQualityTests(unittest.TestCase):
    SUMMARY = (
        "Coordinate appointments and maintain service records for the team. "
        "Respond to enquiries, prepare meeting papers and update case information. "
        "Work with colleagues to organise daily administrative tasks and keep accurate records of agreed actions."
    )

    def row(self, **values):
        row = {field: "" for field in SUMMARY_COLUMNS}
        row.update(organization="Example Council", job_title="Administrator",
            job_reference="REF-1", salary="£25,000 per annum",
            apply_url="https://example.org/vacancies", job_summary=self.SUMMARY)
        row.update(values)
        return row

    def csv_bytes(self, rows, columns=SUMMARY_COLUMNS):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8")

    def test_residue_checks_find_markup_script_and_placeholders(self):
        for text, code in (
            ("<p>Maintain records.</p>", "markup_residue"),
            ("<script>alert('x')</script>", "script_residue"),
            ("function loadAdvert() { return 1; }", "script_residue"),
            ("const salary = 25000;", "script_residue"),
            ("document.querySelector('#advert')", "script_residue"),
            ("Salary: {{ salary }}", "unresolved_placeholder"),
            ("Pay: ${amount}", "unresolved_placeholder"),
            ("[object Object]", "unresolved_placeholder"),
            ("undefined", "unresolved_placeholder"),
        ):
            with self.subTest(text=text):
                self.assertIn(code, text_review_flags(text))

    def test_residue_checks_leave_ordinary_vacancy_wording_alone(self):
        for text in (
            "Support the service's administrative function and maintain records.",
            "Teach HTML and JavaScript, including functions and variables.",
            "Salary < £30,000; working hours > 20 per week.",
            "Keep paper records in {numbered} folders.",
            "Explain undefined terms to service users.",
            "£25,000–£30,000 plus a location allowance, pro rata for 22 hours.",
        ):
            with self.subTest(text=text):
                self.assertEqual([], text_review_flags(text))

    def test_salary_checks_flag_other_field_labels_without_rejecting_pay_details(self):
        for text in (
            "£25,000. Directorate: Finance. Location: Nottingham.",
            "£30,000\nClosing date: 30 October",
            "£25,000. Contract type: Permanent.",
        ):
            self.assertEqual(["salary_contains_other_fields"], salary_review_flags(text))
        for text in ("", "Competitive", "£25,000 plus location allowance",
                     "£12.50 per hour, 37 hours per week; overtime paid separately"):
            self.assertEqual([], salary_review_flags(text))

    def test_summary_checks_flag_expansion_controls_and_trailing_ellipsis(self):
        for ending in ("Read more", "SHOW MORE.", "See more…", "View more..."):
            self.assertIn("unexpanded_description", summary_review_flags(self.SUMMARY + " " + ending))
        for ending in ("...", "…"):
            self.assertIn("possible_truncation_requires_review", summary_review_flags(self.SUMMARY + ending))
        self.assertEqual([], summary_review_flags(self.SUMMARY))
        self.assertNotIn("unexpanded_description", summary_review_flags(self.SUMMARY + " Help visitors read more books."))

    def test_findings_identify_fields_and_csv_records_without_changing_rows(self):
        rows = [self.row(salary="£25,000. Location: Nottingham.",
                         job_summary="<p>Maintain records.</p> Read more")]
        original = deepcopy(rows)
        findings = quality_review_findings(rows)
        self.assertEqual(original, rows)
        self.assertTrue(all(f["row_numbers"] == [2] and f["reason"] for f in findings))
        self.assertIn(("salary_contains_other_fields", "salary"),
            {(f["code"], f["field"]) for f in findings})
        self.assertIn(("markup_residue", "job_summary"),
            {(f["code"], f["field"]) for f in findings})

    def test_same_substantial_summary_is_flagged_across_distinct_roles(self):
        rows = [self.row(), self.row(job_title="Receptionist", job_reference="REF-2",
            job_summary="  " + self.SUMMARY.upper().replace(" ", "\n") + "  ")]
        repeated = [f for f in quality_review_findings(rows) if f["code"] == "repeated_summary"]
        self.assertEqual(1, len(repeated))
        self.assertEqual([2, 3], repeated[0]["row_numbers"])
        # A shared board URL does not define role identity or itself cause a flag.
        rows[1]["job_summary"] = self.SUMMARY.replace("appointments", "customer visits")
        self.assertEqual([], quality_review_findings(rows))

    def test_repetition_check_ignores_same_role_copies_and_short_summaries(self):
        self.assertNotIn("repeated_summary", {f["code"] for f in quality_review_findings([self.row(), self.row()])})
        rows = [self.row(job_summary="Maintain records."),
                self.row(job_title="Receptionist", job_summary="Maintain records.")]
        self.assertNotIn("repeated_summary", {f["code"] for f in quality_review_findings(rows)})

    def test_all_blank_hints_use_employer_groups_and_do_not_infer_missing_facts(self):
        rows = [self.row(job_title=f"Role {n}", salary="", job_summary="") for n in range(3)]
        rows[1]["organization"] = " example   COUNCIL "
        rows.append(self.row(organization="Other Employer", salary="", job_summary=""))
        findings = [f for f in quality_review_findings(rows) if f["code"] == "employer_field_entirely_blank"]
        self.assertEqual({"salary", "job_summary"}, {f["field"] for f in findings})
        self.assertTrue(all(f["row_numbers"] == [2, 3, 4] for f in findings))
        self.assertTrue(all(f["organization"] == "Example Council" for f in findings))
        rows[0]["salary"] = "Competitive"
        self.assertNotIn("salary", {f["field"] for f in quality_review_findings(rows)
            if f["code"] == "employer_field_entirely_blank"})

    def test_missing_optional_columns_and_empty_dataset_do_not_create_group_flags(self):
        rows = [{"organization": "Example Council", "job_title": f"Role {n}"} for n in range(3)]
        self.assertEqual([], quality_review_findings(rows))
        self.assertEqual([], quality_review_findings([]))
        rows = [self.row(organization="", salary="", job_summary="") for _ in range(3)]
        self.assertNotIn("employer_field_entirely_blank", {f["code"] for f in quality_review_findings(rows)})

    def test_cli_reports_advisories_with_success_and_preserves_exact_csv_bytes(self):
        candidate = self.csv_bytes([self.row(salary="£25,000\nLocation: Nottingham",
            job_summary="<p>Maintain records.</p> Read more")])
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path = Path(root) / "candidate.csv"
            path.write_bytes(candidate)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main([str(path)]))
            self.assertEqual(candidate, path.read_bytes())
        report = json.loads(output.getvalue())
        self.assertTrue(report["advisory_only"])
        self.assertEqual(1, report["row_count"])
        self.assertGreater(report["finding_count"], 0)
        self.assertTrue(all(f["row_numbers"] == [2] for f in report["findings"]))
        # Editorial flags do not become CSV safety failures.
        self.assertTrue(validate_csv_bytes(candidate)["ok"])

    def test_cli_does_not_treat_legacy_summary_absence_as_an_extraction_defect(self):
        candidate = self.csv_bytes([self.row(job_title=f"Role {n}") for n in range(3)], LEGACY_COLUMNS)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path = Path(root) / "legacy.csv"
            path.write_bytes(candidate)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main([str(path)]))
        self.assertEqual([], json.loads(output.getvalue())["findings"])

    def audit_candidate(self, candidate):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path = Path(root) / "candidate.csv"
            path.write_bytes(candidate)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main([str(path)]))
            self.assertEqual(candidate, path.read_bytes())
        return json.loads(output.getvalue())

    def test_cli_keeps_original_record_numbers_after_blank_records_in_both_schemas(self):
        for columns in (LEGACY_COLUMNS, SUMMARY_COLUMNS):
            with self.subTest(columns=len(columns)):
                stream = io.StringIO(newline="")
                writer = csv.writer(stream)
                writer.writerow(columns)
                writer.writerow([])
                for index in range(2):
                    row = self.row(job_title=f"Role {index}", job_reference=f"REF-{index}",
                        salary="£25,000\n\nLocation: Nottingham")
                    writer.writerow([row[field] for field in columns])
                    # Blank records are ignored even if their field count differs.
                    writer.writerow([" ", ""])
                candidate = stream.getvalue().encode("utf-8-sig")
                self.assertTrue(validate_csv_bytes(candidate)["ok"])
                report = self.audit_candidate(candidate)
                self.assertEqual(2, report["row_count"])
                findings = [f for f in report["findings"] if f["code"] == "salary_contains_other_fields"]
                self.assertEqual([[3], [5]], [f["row_numbers"] for f in findings])

    def test_cli_group_findings_keep_blank_and_multiline_record_positions(self):
        for columns in (LEGACY_COLUMNS, SUMMARY_COLUMNS):
            with self.subTest(columns=len(columns)):
                stream = io.StringIO(newline="")
                writer = csv.writer(stream)
                writer.writerow(columns)
                for index in range(3):
                    writer.writerow([""] * len(columns))
                    row = self.row(job_title=f"Role {index}", job_reference=f"REF-{index}",
                        salary="", location="Nottingham\n\nCity",
                        job_summary=self.SUMMARY.replace(". ", ".\n"))
                    writer.writerow([row[field] for field in columns])
                candidate = stream.getvalue().encode("utf-8")
                self.assertTrue(validate_csv_bytes(candidate)["ok"])
                report = self.audit_candidate(candidate)
                self.assertEqual(3, report["row_count"])
                blank_salary = [f for f in report["findings"]
                    if f["code"] == "employer_field_entirely_blank" and f["field"] == "salary"]
                self.assertEqual([[3, 5, 7]], [f["row_numbers"] for f in blank_salary])
                repeated = [f for f in report["findings"] if f["code"] == "repeated_summary"]
                self.assertEqual([[3, 5, 7]] if columns == SUMMARY_COLUMNS else [],
                    [f["row_numbers"] for f in repeated])
