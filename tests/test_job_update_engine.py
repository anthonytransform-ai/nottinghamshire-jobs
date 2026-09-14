import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from job_update.adapters.direct_council import DirectCouncilAdapter
from job_update.adapters.itrent import ITrentAdapter
from job_update.adapters.nhs import NHSAdapter
from job_update.adapters.nottingham_cvs import NottinghamCVSAdapter
from job_update.adapters.ntu_jobtrain import NTUJobtrainAdapter, parse_jobtrain_html
from job_update.adapters.oracle_hcm import OracleHCMAdapter
from job_update.adapters.tal import TALAdapter
from job_update.adapters.teaching_vacancies import TeachingVacanciesAdapter
from job_update.adapters.university_nottingham import UniversityNottinghamAdapter
from job_update.classify import classify_job_area, classify_location
from job_update.dedupe import deduplicate
from job_update.eligibility import evaluate
from job_update.http_client import HttpResponse
from job_update.models import NormalizedVacancy, RawVacancy, RunContext, SourceResult, SourceSpec, SourceStatus
from job_update.pipeline import JobUpdatePipeline
from job_update.registry import SourceRegistry
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

    def test_inclusive_window_and_same_day_time(self):
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
        self.assertFalse(
            evaluate(
                self.raw(closing_date_raw="2026-11-10"),
                update_date=update_date,
                employer_type="Council",
                location_area="Nottingham",
                job_area="Administration & Business Support",
            ).included
        )


class ConsolidationTests(unittest.TestCase):
    def vacancy(self, source_id, method, reference="R-1"):
        return NormalizedVacancy(
            organization="Example Council",
            employer_type="Council",
            job_title="Administrator",
            job_area="Administration & Business Support",
            location="Nottingham",
            location_area="Nottingham",
            closing_date="2026-09-30",
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
        )

    def test_dedupe_prefers_direct_primary_advert(self):
        selected, duplicates = deduplicate([
            self.vacancy("cvs", "credible-local-source"),
            self.vacancy("council", "direct-primary-advert"),
        ])
        self.assertEqual(1, len(selected))
        self.assertEqual("council", selected[0].source_id)
        self.assertEqual(1, len(duplicates))

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


class RegistryTests(unittest.TestCase):
    def test_pack_registry_has_all_mandatory_families(self):
        registry = SourceRegistry.load()
        self.assertEqual(29, len(registry.mandatory))
        adapters = {source.adapter for source in registry.mandatory}
        self.assertTrue({"oracle_hcm", "tal", "itrent", "nhs", "university_nottingham", "ntu_jobtrain", "teaching_vacancies", "academy_trust", "nottingham_cvs"}.issubset(adapters))


if __name__ == "__main__":
    unittest.main()
