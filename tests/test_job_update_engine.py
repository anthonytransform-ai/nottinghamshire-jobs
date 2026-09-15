import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from job_update.adapters.direct_council import DirectCouncilAdapter
from job_update.adapters.gedling import parse_gedling_html
from job_update.adapters.itrent import ITrentAdapter, parse_itrent_html
from job_update.adapters.nhs import NHSAdapter
from job_update.adapters.nottingham_cvs import NottinghamCVSAdapter
from job_update.adapters.ntu_jobtrain import NTUJobtrainAdapter, parse_jobtrain_html
from job_update.adapters.oracle_hcm import OracleHCMAdapter
from job_update.adapters.tal import TALAdapter
from job_update.adapters.teaching_vacancies import TeachingVacanciesAdapter
from job_update.adapters.university_nottingham import UniversityNottinghamAdapter
from job_update.classify import classify_job_area, classify_location, load_classification_rules
from job_update.configuration import resolution_key
from job_update.dedupe import deduplicate
from job_update.eligibility import evaluate
from job_update.http_client import HttpResponse
from job_update.models import NormalizedVacancy, RawVacancy, RunContext, SourceResult, SourceSpec, SourceStatus
from job_update.pipeline import JobUpdatePipeline
from job_update.registry import SourceRegistry
from job_update.review import write_resolution
from job_update.normalise import normalize_contract
from job_update.timezone import london_timezone


ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"


class FakeHttpClient:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, **_kwargs):
        for key, response in self.routes.items():
            if key in url:
                if isinstance(response, HttpResponse):
                    return response
                return HttpResponse(url=url, status_code=200, text=response)
        return HttpResponse(url=url, status_code=404, error="fixture route not found")


class FakeBrowser:
    def render(self, url, **_kwargs):
        return type("Rendered", (), {"ok": False, "error": "browser not expected", "html": "", "url": url, "captured_urls": []})()


def spec(source_id, adapter, employer_type="Council", **configuration):
    return SourceSpec(
        source_id=source_id,
        display_name=source_id,
        employer_type=employer_type,
        mandatory=True,
        adapter=adapter,
        official_entry_url=f"https://example.test/{source_id}",
        configuration=configuration,
    )


def context(registry, client, run_dir):
    return RunContext(
        date_checked=date(2026, 9, 14),
        run_dir=run_dir,
        http_client=client,
        browser=FakeBrowser(),
        registry=registry,
        allow_browser=False,
        now=datetime(2026, 9, 14, 10, 0, tzinfo=london_timezone()),
    )


class AdapterFixtureTests(unittest.TestCase):
    def read(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_oracle_uses_total_jobs_count_and_ids(self):
        source = spec(
            "city",
            "oracle_hcm",
            api_url="https://oracle.test/requisitions?finder=x,limit=100,offset=0",
            detail_url_template="https://oracle.test/job/{id}",
            organization="Nottingham City Council",
        )
        response = HttpResponse(url="https://oracle.test/requisitions", status_code=200, text=(FIXTURES / "oracle.json").read_text())
        result = OracleHCMAdapter(source).fetch(context(SourceRegistry([source]), FakeHttpClient({"oracle.test": response}), tempfile.mkdtemp()))
        self.assertEqual(SourceStatus.COMPLETE, result.status)
        self.assertEqual(2, result.source_total)
        self.assertEqual({"8178", "8179"}, {item.source_record_id for item in result.raw_vacancies})

    def test_itrent_reconciles_reported_matches(self):
        source = spec("ashfield", "itrent", organization="Ashfield District Council", wvid="W1", location_default="Ashfield")
        client = FakeHttpClient({"example.test/ashfield": self.read("itrent.html")})
        result = ITrentAdapter(source).fetch(context(SourceRegistry([source]), client, tempfile.mkdtemp()))
        self.assertEqual(SourceStatus.COMPLETE, result.status)
        self.assertEqual(2, result.captured_total)
        self.assertEqual("Ashfield District Council", result.raw_vacancies[0].organization_raw)

    def test_itrent_balances_selected_nested_card(self):
        source = spec("ashfield", "itrent", organization="Ashfield District Council", wvid="W1", location_default="Ashfield")
        total, records = parse_itrent_html(self.read("itrent_selected_card.html"), source, "https://example.test/ashfield")
        self.assertEqual(1, total)
        self.assertEqual(1, len(records))
        self.assertEqual("A-100", records[0].source_record_id)
        self.assertEqual("Quantity Surveyor", records[0].title_raw)

    def test_itrent_requires_and_parses_actual_profile_boundary(self):
        source = spec(
            "college-itrent",
            "itrent",
            employer_type="Education",
            organization="West Nottinghamshire College",
            host_organization="West Nottinghamshire College",
            host_association_verified=True,
            detail_required=True,
        )
        record = RawVacancy(
            source_id="college-itrent",
            source_url="https://example.test/college",
            source_record_id="A-100",
            title_raw="((name))",
            apply_url_raw="https://example.test/college",
            evidence={"detail_required": True, "host_association_verified": True},
        )
        adapter = ITrentAdapter(source)
        failures = adapter._enrich_details(
            [record],
            context(SourceRegistry([source]), FakeHttpClient({}), tempfile.mkdtemp()),
            listing_html=self.read("itrent_profile.html"),
        )
        self.assertEqual(0, failures)
        self.assertTrue(record.evidence["detail_verified"])
        self.assertEqual("Quantity Surveyor", record.title_raw)
        self.assertEqual("2026-09-27", record.closing_date_raw)
        self.assertIn("Sutton in Ashfield", record.location_raw)
        self.assertEqual("https://example.test/apply/A-100", record.apply_url_raw)

    def test_tal_discovers_board_and_does_not_silently_zero(self):
        source = spec("ncc", "tal", board_kind="ncc")
        client = FakeHttpClient({"example.test/ncc": self.read("tal_entry.html"), "tal.net": self.read("tal.html")})
        result = TALAdapter(source).fetch(context(SourceRegistry([source]), client, tempfile.mkdtemp()))
        self.assertEqual(SourceStatus.COMPLETE, result.status)
        self.assertEqual(2, result.captured_total)

    def test_tal_challenge_is_blocked(self):
        source = spec("ncc", "tal", board_kind="ncc")
        client = FakeHttpClient({"example.test/ncc": self.read("tal_entry.html"), "tal.net": HttpResponse(url="https://tal.net", status_code=403, text="Quick Check Needed")})
        result = TALAdapter(source).fetch(context(SourceRegistry([source]), client, tempfile.mkdtemp()))
        self.assertEqual(SourceStatus.BLOCKED, result.status)
        self.assertIsNone(result.source_total)

    def test_tal_table_rows_keep_ids_locations_and_deadlines(self):
        source = spec("ncc", "tal", board_kind="ncc")
        total, records, filtered = TALAdapter(source)._parse(self.read("tal_table.html"), "https://tal.test/board")
        self.assertEqual(2, total)
        self.assertFalse(filtered)
        self.assertEqual(2, len(records))
        self.assertEqual("31152", records[0].source_record_id)
        self.assertEqual("2026-09-25", records[0].closing_date_raw)

    def test_direct_nhs_university_ntu_teaching_and_cvs_fixtures(self):
        sources = [
            spec("direct", "direct_council", organization="Broxtowe Borough Council"),
            spec("nhs", "nhs", employer="Nottingham University Hospitals NHS Trust", search_url="https://jobs.test/search", query="NUH", location_default="Nottingham"),
            spec("university", "university_nottingham", organization="University of Nottingham", location_default="Nottingham"),
            spec("ntu", "ntu_jobtrain", organization="Nottingham Trent University", location_default="Nottingham"),
            spec("teaching", "teaching_vacancies", queries=["https://teaching.test/jobs?location=nottinghamshire", "https://teaching.test/jobs?location=nottingham"]),
            spec("cvs", "nottingham_cvs", location_default="Nottinghamshire-wide"),
        ]
        routes = {
            "example.test/direct": self.read("direct_council.html"),
            "jobs.test": self.read("nhs.html"),
            "example.test/university": self.read("university.html"),
            "example.test/ntu": self.read("ntu.html"),
            "teaching.test": self.read("teaching_page.html"),
            "example.test/cvs": self.read("cvs.html"),
        }
        client = FakeHttpClient(routes)
        registry = SourceRegistry(sources)
        results = [
            DirectCouncilAdapter(sources[0]).fetch(context(registry, client, tempfile.mkdtemp())),
            NHSAdapter(sources[1]).fetch(context(registry, client, tempfile.mkdtemp())),
            UniversityNottinghamAdapter(sources[2]).fetch(context(registry, client, tempfile.mkdtemp())),
            NTUJobtrainAdapter(sources[3]).fetch(context(registry, client, tempfile.mkdtemp())),
            TeachingVacanciesAdapter(sources[4]).fetch(context(registry, client, tempfile.mkdtemp())),
            NottinghamCVSAdapter(sources[5]).fetch(context(registry, client, tempfile.mkdtemp())),
        ]
        self.assertEqual(1, results[0].captured_total)
        self.assertEqual(2, results[1].captured_total)
        self.assertEqual(3, results[2].captured_total)
        self.assertEqual(2, results[3].captured_total)
        self.assertEqual(SourceStatus.COMPLETE, results[4].status)
        self.assertEqual(2, results[5].captured_total)
        self.assertIsNone(results[4].source_total)
        self.assertEqual(2, results[4].reported_totals["https://teaching.test/jobs?location=nottinghamshire"])

    def test_nhs_uses_actual_job_base_not_employer_address(self):
        source = spec(
            "nhs-location",
            "nhs",
            employer="Example NHS Trust",
            search_url="https://nhs.test/search",
            query="Example NHS Trust",
        )
        search = """<html><body><h1>1 jobs found</h1>
        <article class='job-card' data-job-reference='NHS-900'><h2>Staff Nurse</h2>
        <p>Employer: Example NHS Trust</p><a href='/jobs/NHS-900'>View job</a></article>
        </body></html>"""
        routes = {
            "example.test/nhs-location": "<html><body>Trust</body></html>",
            "nhs.test/search": search,
            "nhs.test/jobs/NHS-900": self.read("nhs_detail_mansfield.html"),
        }
        result = NHSAdapter(source).fetch(context(SourceRegistry([source]), FakeHttpClient(routes), tempfile.mkdtemp()))
        self.assertEqual(1, len(result.raw_vacancies))
        record = result.raw_vacancies[0]
        self.assertIn("Mansfield", record.location_raw)
        self.assertNotIn("Headquarters", record.location_raw)
        self.assertEqual("Mansfield", classify_location(record.location_raw)[0])

    def test_gedling_generated_retrieval_id_is_not_public_reference(self):
        records, _has_cards = parse_gedling_html(
            """<div class='u-pull-left'><h3>Administrator</h3><p>Closing Date: 31 January 2027</p></div>""",
            "https://gedling.test/jobs",
            source_id="gedling",
            organization="Gedling Borough Council",
            location="Gedling",
        )
        self.assertEqual(1, len(records))
        self.assertEqual("GEDLING-001", records[0].source_record_id)
        self.assertEqual("", records[0].reference_raw)

    def test_teaching_detail_failure_downgrades_source(self):
        source = spec("teaching-failure", "teaching_vacancies", queries=["https://teaching.test/jobs?location=nottinghamshire"])
        page = self.read("teaching_page.html")

        class SearchOnly(FakeHttpClient):
            def get(self, url, **kwargs):
                if "teaching.test/jobs?" in url:
                    return HttpResponse(url=url, status_code=200, text=page)
                return HttpResponse(url=url, status_code=404, error="detail fixture deliberately unavailable")

        result = TeachingVacanciesAdapter(source).fetch(context(SourceRegistry([source]), SearchOnly({}), tempfile.mkdtemp()))
        self.assertEqual(SourceStatus.PARTIALLY_VERIFIED, result.status)
        self.assertTrue(any("detail" in warning.casefold() for warning in result.warnings))

    def test_teaching_structured_detail_uses_jobposting_boundary(self):
        source = spec("teaching-detail", "teaching_vacancies", employer_type="Education", queries=["https://teaching.test/jobs?location=nottinghamshire"])
        record = RawVacancy(
            source_id="teaching-detail",
            source_url="https://teaching.test/jobs?location=nottinghamshire",
            source_record_id="class-teacher",
            title_raw="Class Teacher",
            apply_url_raw="https://teaching.test/jobs/class-teacher",
            evidence={"detail_required": True},
        )
        client = FakeHttpClient({"teaching.test/jobs/class-teacher": self.read("teaching_jobposting_detail.html")})
        adapter = TeachingVacanciesAdapter(source)
        failures = adapter._enrich_details([record], context(SourceRegistry([source]), client, tempfile.mkdtemp()))
        self.assertEqual(0, failures)
        self.assertTrue(record.evidence["detail_verified"])
        self.assertEqual("Bilsthorpe Flying High Academy", record.advertised_employer_raw)
        self.assertIn("Newark", record.location_raw)
        self.assertNotIn("Unrelated similar jobs", record.location_raw)
        self.assertEqual("2026-09-17", record.closing_date_raw)
        self.assertEqual("09:00", record.closing_time_raw)

    def test_nottingham_college_current_route_enumerates_and_details_records(self):
        source = spec(
            "nottingham-college",
            "direct_council",
            employer_type="Education",
            organization="Nottingham College",
            detail_links=True,
            detail_required=True,
            job_link_pattern=r"current-vacancies/[^/]+$",
            card_class="shadow-course-card",
        )
        routes = {
            "example.test/nottingham-college": self.read("nottingham_college.html"),
            "example.test/about-us/working-for-us/current-vacancies/": self.read("college_group_detail.html"),
        }
        result = DirectCouncilAdapter(source).fetch(context(SourceRegistry([source]), FakeHttpClient(routes), tempfile.mkdtemp()))
        self.assertEqual(2, result.captured_total)
        self.assertIsNone(result.source_total)
        self.assertTrue(all(item.evidence.get("detail_verified") for item in result.raw_vacancies))
        self.assertTrue(all(item.reference_raw == "" for item in result.raw_vacancies))
        self.assertEqual(["City Hub, Nottingham", "Mansfield"], [item.location_raw for item in result.raw_vacancies])

    def test_ntu_dynamic_nested_cards_are_parsed_without_page_container_false_positive(self):
        total, records = parse_jobtrain_html(
            self.read("ntu_dynamic.html"),
            "ntu-jobtrain",
            "Nottingham Trent University",
            "https://vacancies.ntu.ac.uk/Home/Job",
            "Nottingham",
        )
        self.assertEqual(2, total)
        self.assertEqual(2, len(records))
        self.assertEqual("HPL Property Management & Development", records[0].title_raw)
        self.assertEqual("2611", records[0].source_record_id)
        self.assertEqual("City Campus", records[0].location_raw)


class PolicyTests(unittest.TestCase):
    def test_location_and_job_area_rules_are_not_naive(self):
        self.assertEqual("Nottinghamshire-wide", classify_location("Nottinghamshire")[0])
        self.assertEqual("Planning, Environment & Regulatory", classify_job_area("Environmental Health Officer")[0])
        self.assertEqual("Property, Facilities & Operations", classify_job_area("School Cleaner")[0])
        self.assertEqual("Finance & Procurement", classify_job_area("Finance Manager")[0])

    def raw(self, **updates):
        value = RawVacancy(
            source_id="source",
            source_url="https://example.test/source",
            source_record_id="R-1",
            organization_raw="Example Council",
            title_raw="Administrator",
            location_raw="Nottingham",
            closing_date_raw="2026-11-09",
            closing_time_raw="",
            apply_url_raw="https://example.test/job/R-1",
            reference_raw="R-1",
        )
        for key, update in updates.items():
            setattr(value, key, update)
        return value

    def test_fixed_deadline_and_same_day_time(self):
        update_date = date(2026, 9, 14)
        decision = evaluate(
            self.raw(),
            update_date=update_date,
            employer_type="Council",
            location_area="Nottingham",
            job_area="Administration & Business Support",
        )
        self.assertTrue(decision.included)
        expired_today = evaluate(
            self.raw(closing_date_raw="2026-09-14", closing_time_raw="09:00"),
            update_date=update_date,
            employer_type="Council",
            location_area="Nottingham",
            job_area="Administration & Business Support",
            now=datetime(2026, 9, 14, 10, 0, tzinfo=london_timezone()),
        )
        self.assertFalse(expired_today.included)
        self.assertTrue(
            evaluate(
                self.raw(closing_date_raw="2027-01-31"),
                update_date=update_date,
                employer_type="Council",
                location_area="Nottingham",
                job_area="Administration & Business Support",
            ).included
        )

    def test_paid_volunteer_role_is_not_misclassified_as_unpaid(self):
        decision = evaluate(
            self.raw(title_raw="Volunteer Coordinator", description_raw="Paid role coordinating volunteers."),
            update_date=date(2026, 9, 14),
            employer_type="VCSE",
            location_area="Nottingham",
            job_area="Community & Outreach",
        )
        self.assertTrue(decision.included)
        unpaid = evaluate(
            self.raw(title_raw="Volunteer", description_raw="Unpaid volunteering opportunity."),
            update_date=date(2026, 9, 14),
            employer_type="VCSE",
            location_area="Nottingham",
            job_area="Community & Outreach",
        )
        self.assertFalse(unpaid.included)

    def test_education_host_and_private_agency_policy(self):
        contractor = self.raw(
            organization_raw="Recruitment Partner",
            advertised_employer_raw="Recruitment Partner",
            host_organization_raw="Nottingham College",
            host_association_verified=True,
            host_association_type="agency",
            host_association_evidence="college named in advert",
        )
        self.assertTrue(
            evaluate(
                contractor,
                update_date=date(2026, 9, 14),
                employer_type="Education",
                location_area="Nottingham",
                job_area="Other",
            ).included
        )
        private = self.raw()
        private.evidence["private"] = True
        self.assertFalse(
            evaluate(
                private,
                update_date=date(2026, 9, 14),
                employer_type="Education",
                location_area="Nottingham",
                job_area="Other",
            ).included
        )
        generic = self.raw(organization_raw="Unknown Recruitment Agency", advertised_employer_raw="Unknown Recruitment Agency")
        generic.evidence["agency"] = True
        self.assertFalse(
            evaluate(
                generic,
                update_date=date(2026, 9, 14),
                employer_type="Education",
                location_area="Nottingham",
                job_area="Other",
            ).included
        )

    def test_term_time_only_is_not_fixed_term(self):
        self.assertEqual("Other", normalize_contract("Term Time Only"))
        self.assertEqual("Fixed-term", normalize_contract("Fixed Term until 31 August 2027"))


class ConsolidationTests(unittest.TestCase):
    def vacancy(self, source_id, method, reference="R-1", *, organization="Example Council", title="Administrator", location="Nottingham", closing_date="2026-09-30", host="", host_verified=False):
        return NormalizedVacancy(
            organization=organization,
            employer_type="Council",
            job_title=title,
            job_area="Administration & Business Support",
            location=location,
            location_area="Nottingham",
            closing_date=closing_date,
            closing_time="",
            contract_type="Permanent",
            work_pattern="Full-time",
            salary="",
            apply_url=f"https://example.test/{source_id}",
            job_reference=reference,
            date_checked="2026-09-14",
            source_url=f"https://example.test/{source_id}",
            source_id=source_id,
            verification_method=method,
            advertised_employer=organization,
            host_organization=host,
            host_association_verified=host_verified,
        )

    def test_dedupe_prefers_direct_primary_advert(self):
        selected, duplicates = deduplicate([
            self.vacancy("cvs", "credible-local-source"),
            self.vacancy("council", "direct-primary-advert"),
        ])
        self.assertEqual(1, len(selected))
        self.assertEqual("council", selected[0].source_id)
        self.assertEqual(1, len(duplicates))

    def test_dedupe_fallback_ignores_different_urls_and_keeps_real_references(self):
        mirror_a = self.vacancy("teaching", "primary-platform-listing", reference="")
        mirror_b = self.vacancy("trust", "direct-primary-advert", reference="")
        selected, duplicates = deduplicate([mirror_a, mirror_b])
        self.assertEqual(1, len(selected))
        self.assertEqual("trust", selected[0].source_id)
        self.assertEqual(1, len(duplicates))

        distinct_ref = self.vacancy("other", "direct-primary-advert", reference="R-2")
        selected, _duplicates = deduplicate([self.vacancy("one", "direct-primary-advert", reference="R-1"), distinct_ref])
        self.assertEqual(2, len(selected))

        distinct_location = self.vacancy("other-location", "direct-primary-advert", reference="", location="Mansfield")
        selected, _duplicates = deduplicate([mirror_a, distinct_location])
        self.assertEqual(2, len(selected))

    def test_host_scope_prevents_unrelated_contractor_collapse(self):
        first = self.vacancy("college", "direct-primary-advert", reference="", organization="Agency A", host="Nottingham College", host_verified=True)
        second = self.vacancy("nhs", "direct-primary-advert", reference="", organization="Agency A", host="Example NHS Trust", host_verified=True)
        selected, duplicates = deduplicate([first, second])
        self.assertEqual(2, len(selected))
        self.assertEqual([], duplicates)

    def test_pipeline_writes_audit_review_and_validator_candidate(self):
        first = spec("one", "direct_council", organization="Example Council")
        second = spec("two", "direct_council", organization="Example Council")
        registry = SourceRegistry([first, second])
        eligible = RawVacancy(
            source_id="one", source_url="https://example.test/one", source_record_id="R-1",
            organization_raw="Example Council", title_raw="Environmental Health Officer", location_raw="Nottingham",
            closing_date_raw="2026-09-30", apply_url_raw="https://example.test/job/R-1", reference_raw="R-1",
            description_raw="Council role", contract_raw="Permanent", work_pattern_raw="Full-time",
        )
        mirror = RawVacancy(**{**eligible.to_dict(), "source_id": "two", "source_url": "https://example.test/two", "apply_url_raw": "https://example.test/two/job/R-1"})
        ambiguous = RawVacancy(
            source_id="one", source_url="https://example.test/one", source_record_id="R-2",
            organization_raw="Example Council", title_raw="Officer", location_raw="Hybrid",
            closing_date_raw="2026-09-30", apply_url_raw="https://example.test/job/R-2", reference_raw="R-2",
        )
        results = [
            SourceResult("one", "one", True, "fixture", 2, 2, [eligible, ambiguous], status=SourceStatus.COMPLETE, verification_method="direct-primary-advert"),
            SourceResult("two", "two", True, "fixture", 1, 1, [mirror], status=SourceStatus.COMPLETE, verification_method="credible-local-source"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            pipeline = JobUpdatePipeline(context(registry, FakeHttpClient({}), run_dir))
            summary = pipeline.build(results)
            self.assertEqual(1, summary["row_count"])
            self.assertGreaterEqual(summary["review_count"], 1)
            self.assertTrue((run_dir / "source_audit.json").exists())
            self.assertTrue((run_dir / "pr_body.md").exists())
            audit = json.loads((run_dir / "source_audit.json").read_text())
            self.assertEqual(2, len(audit))
            self.assertEqual("Complete", audit[0]["status"])

    def test_review_resolution_rebuilds_without_refetch(self):
        source = spec("review-source", "direct_council", organization="Example Council")
        registry = SourceRegistry([source])
        raw = RawVacancy(
            source_id="review-source",
            source_url="https://example.test/review",
            source_record_id="INTERNAL-1",
            organization_raw="Example Council",
            title_raw="Officer",
            location_raw="Hybrid",
            closing_date_raw="2027-01-31",
            apply_url_raw="https://example.test/job/1",
            description_raw="Council role",
        )
        results = [SourceResult("review-source", "review-source", True, "fixture", None, 1, [raw], status=SourceStatus.COMPLETE)]
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            pipeline = JobUpdatePipeline(context(registry, FakeHttpClient({}), run_dir))
            first = pipeline.build(results)
            self.assertEqual(0, first["row_count"])
            key = json.loads((run_dir / "review_queue.json").read_text())[0]["resolution_key"]
            write_resolution(run_dir / "review_resolutions.toml", key=key, field="location_area", value="Nottingham")
            write_resolution(run_dir / "review_resolutions.toml", key=key, field="job_area", value="Administration & Business Support")
            second = pipeline.build([SourceResult.from_dict(item) for item in json.loads(json.dumps([results[0].to_dict()]))])
            self.assertEqual(1, second["row_count"])

    def test_classification_rules_file_is_runtime_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rules.toml"
            path.write_text('[location]\nnottingham = ["madeup campus"]\n', encoding="utf-8")
            rules = load_classification_rules(path)
            self.assertEqual("Nottingham", classify_location("Madeup Campus", rules=rules)[0])


class RegistryTests(unittest.TestCase):
    def test_pack_registry_has_all_mandatory_families(self):
        registry = SourceRegistry.load()
        self.assertEqual(32, len(registry.mandatory))
        self.assertTrue({"nottingham-college", "west-nottinghamshire-college", "north-notts-rnn"}.issubset({source.source_id for source in registry.mandatory}))
        adapters = {source.adapter for source in registry.mandatory}
        self.assertTrue({"oracle_hcm", "tal", "itrent", "nhs", "university_nottingham", "ntu_jobtrain", "teaching_vacancies", "academy_trust", "nottingham_cvs"}.issubset(adapters))


if __name__ == "__main__":
    unittest.main()
