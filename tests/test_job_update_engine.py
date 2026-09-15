import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from job_update.adapters.oracle_hcm import OracleHCMAdapter
from job_update.classify import JOB_AREAS, LOCATION_AREAS, classify_job_area, classify_location
from job_update.configuration import resolution_key
from job_update.dedupe import deduplicate
from job_update.eligibility import evaluate
from job_update.http_client import HttpResponse
from job_update.html_tools import clean_text
from job_update.ingestion import IngestionError, load_source_results, validate_source_results, write_structured_source_results
from job_update.models import NormalizedVacancy, RawVacancy, RunContext, SourceResult, SourceSpec, SourceStatus
from job_update.normalise import normalize_contract
from job_update.pipeline import JobUpdatePipeline
from job_update.registry import SourceRegistry
from job_update.review import write_resolution
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


def source(source_id: str, *, employer_type: str = "Council", **kwargs) -> SourceSpec:
    return SourceSpec(
        source_id=source_id,
        display_name=kwargs.pop("display_name", source_id),
        employer_type=employer_type,
        mandatory=kwargs.pop("mandatory", True),
        official_entry_url=kwargs.pop("official_entry_url", f"https://{source_id}.test/jobs"),
        source_type=kwargs.pop("source_type", "agent-researched"),
        collector=kwargs.pop("collector", ""),
        expected_host_service=kwargs.pop("expected_host_service", ""),
        completeness_evidence=kwargs.pop("completeness_evidence", "fixture evidence"),
        configuration=kwargs,
    )


def context(registry, client=None, run_dir=None):
    return RunContext(
        date_checked=date(2026, 9, 15),
        run_dir=run_dir or tempfile.mkdtemp(),
        registry=registry,
        http_client=client,
        live=client is not None,
        now=datetime(2026, 9, 15, 10, 0, tzinfo=london_timezone()),
    )


class IngestionTests(unittest.TestCase):
    def fixture_payload(self):
        return json.loads((FIXTURES / "agent_source_results.json").read_text(encoding="utf-8"))

    def fixture_registry(self):
        return SourceRegistry([
            source("example-council", expected_host_service="Example Council"),
            source("empty-source", expected_host_service="Empty Source"),
        ])

    def test_structured_evidence_is_validated_and_preserves_public_reference_boundary(self):
        registry = self.fixture_registry()
        payload = self.fixture_payload()
        summary = validate_source_results(payload, registry, expected_date=date(2026, 9, 15))
        self.assertEqual(2, summary["source_count"])
        results = load_source_results(FIXTURES / "agent_source_results.json", registry, expected_date=date(2026, 9, 15))
        record = results[0].raw_vacancies[0]
        self.assertEqual("INTERNAL-1", record.source_record_id)
        self.assertEqual("PUBLIC-1", record.reference_raw)
        self.assertEqual("Agency Partner", record.advertised_employer_raw)
        self.assertEqual("Example Council", record.host_organization_raw)
        self.assertEqual("Nottingham", record.location_area_raw)
        self.assertEqual("Planning, Environment & Regulatory", record.job_area_raw)

    def test_invalid_semantic_enum_is_rejected(self):
        registry = self.fixture_registry()
        payload = self.fixture_payload()
        payload["sources"][0]["records"][0]["job_area"] = "Invented category"
        with self.assertRaises(IngestionError):
            validate_source_results(payload, registry)

    def test_complete_source_total_must_reconcile(self):
        registry = self.fixture_registry()
        payload = self.fixture_payload()
        payload["sources"][0]["source_total"] = 2
        with self.assertRaises(IngestionError):
            validate_source_results(payload, registry)

    def test_verified_host_association_requires_evidence(self):
        registry = self.fixture_registry()
        payload = self.fixture_payload()
        payload["sources"][0]["records"][0]["host_association_evidence"] = ""
        with self.assertRaises(IngestionError):
            validate_source_results(payload, registry)

    def test_blocked_source_is_explicit_not_a_complete_zero(self):
        registry = self.fixture_registry()
        payload = self.fixture_payload()
        payload["sources"][0]["status"] = "Blocked"
        payload["sources"][0]["source_total"] = None
        payload["sources"][0]["captured_total"] = 0
        payload["sources"][0]["records"] = []
        payload["sources"][0]["errors"] = ["official route unavailable"]
        validate_source_results(payload, registry)

    def test_every_mandatory_source_is_required_even_when_zero(self):
        registry = SourceRegistry([
            source("required-one"),
            source("required-two"),
        ])
        payload = self.fixture_payload()
        payload["sources"] = [payload["sources"][0]]
        payload["sources"][0]["source_id"] = "required-one"
        with self.assertRaises(IngestionError):
            validate_source_results(payload, registry)

    def test_round_trip_writer_keeps_structured_shape(self):
        registry = self.fixture_registry()
        results = load_source_results(FIXTURES / "agent_source_results.json", registry)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source_results.json"
            write_structured_source_results(results, path, date_checked=date(2026, 9, 15))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, payload["schema_version"])
            self.assertIn("records", next(item for item in payload["sources"] if item["source_id"] == "example-council"))
            self.assertEqual(2, len(payload["sources"]))


class StableCollectorTests(unittest.TestCase):
    def test_oracle_html_text_excludes_script_and_style_payloads(self):
        value = clean_text("<style>.hidden { color: red; }</style><div>Closing date: 31 October 2026</div><script>window.noise = true;</script>")
        self.assertEqual("Closing date: 31 October 2026", value)

    def test_oracle_is_the_only_retained_stable_collector(self):
        registry = SourceRegistry.load()
        collectors = registry.collectors()
        self.assertEqual(["nottingham-city-oracle"], [collector.spec.source_id for collector in collectors])
        self.assertEqual(32, len(registry.mandatory))
        self.assertEqual(33, len(registry.sources))
        self.assertTrue(all(source.playbook_notes and source.completeness_evidence for source in registry.sources))
        self.assertTrue(all(source.source_type in {"agent-researched", "stable-api"} for source in registry.sources))

    def test_oracle_fixture_collector_reconciles_total_and_keeps_reference(self):
        spec = source(
            "nottingham-city-oracle",
            source_type="stable-api",
            collector="oracle_hcm",
            expected_host_service="Nottingham City Council",
            api_url="https://oracle.test/api?limit=100&offset=0",
            detail_url_template="https://oracle.test/job/{id}",
            organization="Nottingham City Council",
        )
        payload = {
            "items": [{
                "TotalJobsCount": 1,
                "requisitionList": [{
                    "Id": "100",
                    "RequisitionNumber": "NCC-100",
                    "Title": "Environmental Health Officer",
                    "PrimaryLocation": "Nottingham",
                    "PostingEndDate": "2027-01-31",
                    "ShortDescriptionStr": "Council role",
                }],
            }],
        }

        class OracleFixtureClient(FakeHttpClient):
            def get(self, url, **kwargs):
                return HttpResponse(url=url, status_code=200, text=json.dumps(payload))

        result = OracleHCMAdapter(spec).fetch(context(SourceRegistry([spec]), OracleFixtureClient({})))
        self.assertEqual(SourceStatus.COMPLETE, result.status)
        self.assertEqual(1, result.source_total)
        self.assertEqual(1, result.captured_total)
        self.assertEqual("NCC-100", result.raw_vacancies[0].reference_raw)
        self.assertTrue(result.raw_vacancies[0].host_association_verified)


class DeterministicBuildTests(unittest.TestCase):
    def test_build_consumes_agent_evidence_without_network_and_writes_audit(self):
        registry = SourceRegistry([
            source("example-council", expected_host_service="Example Council"),
            source("empty-source", expected_host_service="Empty Source"),
        ])
        results = load_source_results(FIXTURES / "agent_source_results.json", registry)
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            pipeline = JobUpdatePipeline(context(registry, run_dir=run_dir))
            summary = pipeline.build(results)
            self.assertEqual(1, summary["row_count"])
            self.assertEqual(0, summary["review_count"])
            self.assertTrue((run_dir / "source_audit.json").exists())
            self.assertTrue((run_dir / "jobs.csv").exists())
            rows = json.loads((run_dir / "normalized_records.json").read_text(encoding="utf-8"))
            self.assertEqual("Agency Partner", rows[0]["advertised_employer"])
            self.assertEqual("Example Council", rows[0]["host_organization"])

    def test_agent_semantics_are_preferred_over_fallback_classifiers(self):
        registry = SourceRegistry([source("semantic")])
        raw = RawVacancy(
            source_id="semantic",
            source_url="https://semantic.test/jobs",
            source_record_id="S-1",
            organization_raw="Example Council",
            title_raw="Officer",
            location_raw="A place requiring judgement",
            closing_date_raw="2027-01-31",
            apply_url_raw="https://semantic.test/jobs/S-1",
            reference_raw="S-1",
            location_area_raw="Mansfield",
            job_area_raw="Administration & Business Support",
            host_organization_raw="Example Council",
            host_association_verified=True,
            evidence={"source_url": "https://semantic.test/jobs/S-1"},
        )
        result = SourceResult("semantic", "semantic", True, "codex-agent-research", None, 1, [raw], status=SourceStatus.COMPLETE)
        with tempfile.TemporaryDirectory() as temp:
            summary = JobUpdatePipeline(context(registry, run_dir=Path(temp))).build([result])
            self.assertEqual(1, summary["row_count"])
            row = json.loads((Path(temp) / "normalized_records.json").read_text(encoding="utf-8"))[0]
            self.assertEqual("Mansfield", row["location_area"])

    def test_missing_base_enters_review_but_does_not_become_zero_source(self):
        registry = SourceRegistry([source("review-source", expected_host_service="Review Council")])
        raw = RawVacancy(
            source_id="review-source",
            source_url="https://review.test/jobs",
            source_record_id="R-1",
            organization_raw="Review Council",
            title_raw="Officer",
            location_raw="Hybrid",
            closing_date_raw="2027-01-31",
            apply_url_raw="https://review.test/jobs/R-1",
            reference_raw="R-1",
            host_organization_raw="Review Council",
            host_association_verified=True,
            evidence={"source_url": "https://review.test/jobs/R-1"},
        )
        result = SourceResult("review-source", "review-source", True, "codex-agent-research", None, 1, [raw], status=SourceStatus.COMPLETE)
        with tempfile.TemporaryDirectory() as temp:
            summary = JobUpdatePipeline(context(registry, run_dir=Path(temp))).build([result])
            self.assertEqual(0, summary["row_count"])
            self.assertEqual(1, summary["review_count"])
            self.assertEqual("Complete", json.loads((Path(temp) / "source_audit.json").read_text(encoding="utf-8"))[0]["status"])

    def test_review_resolution_rebuilds_without_network_or_refetch(self):
        registry = SourceRegistry([source("review-source", expected_host_service="Review Council")])
        raw = RawVacancy(
            source_id="review-source",
            source_url="https://review.test/jobs",
            source_record_id="R-1",
            organization_raw="Review Council",
            title_raw="Officer",
            location_raw="Hybrid",
            closing_date_raw="2027-01-31",
            apply_url_raw="https://review.test/jobs/R-1",
            reference_raw="R-1",
            host_organization_raw="Review Council",
            host_association_verified=True,
            evidence={"source_url": "https://review.test/jobs/R-1"},
        )
        result = SourceResult("review-source", "review-source", True, "codex-agent-research", None, 1, [raw], status=SourceStatus.COMPLETE)
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            pipeline = JobUpdatePipeline(context(registry, run_dir=run_dir))
            pipeline.build([result])
            key = json.loads((run_dir / "review_queue.json").read_text(encoding="utf-8"))[0]["resolution_key"]
            write_resolution(run_dir / "review_resolutions.toml", key=key, field="location_area", value="Nottingham")
            write_resolution(run_dir / "review_resolutions.toml", key=key, field="job_area", value="Administration & Business Support")
            summary = pipeline.build([result])
            self.assertEqual(1, summary["row_count"])


class PolicyAndDedupeTests(unittest.TestCase):
    def raw(self, **updates):
        value = RawVacancy(
            source_id="source",
            source_url="https://example.test/source",
            source_record_id="R-1",
            organization_raw="Example Council",
            title_raw="Administrator",
            location_raw="Nottingham",
            closing_date_raw="2026-09-15",
            apply_url_raw="https://example.test/job/R-1",
            reference_raw="R-1",
            host_organization_raw="Example Council",
            host_association_verified=True,
        )
        for key, update in updates.items():
            setattr(value, key, update)
        return value

    def test_controlled_values_and_obvious_fallbacks(self):
        self.assertTrue(set(("Nottingham", "Mansfield")).issubset(LOCATION_AREAS))
        self.assertTrue("Education & Training" in JOB_AREAS)
        self.assertEqual("Nottinghamshire-wide", classify_location("Nottinghamshire")[0])
        self.assertEqual("Planning, Environment & Regulatory", classify_job_area("Environmental Health Officer")[0])
        self.assertEqual("Other", classify_job_area("Officer", "A role with no obvious function")[0])

    def test_deadline_policy_has_no_maximum_horizon_and_handles_same_day_time(self):
        self.assertTrue(evaluate(
            self.raw(closing_date_raw="2035-01-31"),
            update_date=date(2026, 9, 15),
            employer_type="Council",
            location_area="Nottingham",
            job_area="Administration & Business Support",
        ).included)
        self.assertFalse(evaluate(
            self.raw(closing_time_raw="09:00"),
            update_date=date(2026, 9, 15),
            employer_type="Council",
            location_area="Nottingham",
            job_area="Administration & Business Support",
            now=datetime(2026, 9, 15, 10, 0, tzinfo=london_timezone()),
        ).included)

    def test_paid_volunteer_and_term_time_policy(self):
        self.assertTrue(evaluate(
            self.raw(title_raw="Volunteer Coordinator", description_raw="Paid role"),
            update_date=date(2026, 9, 15),
            employer_type="VCSE",
            location_area="Nottingham",
            job_area="Community & Outreach",
        ).included)
        self.assertFalse(evaluate(
            self.raw(title_raw="Volunteer", description_raw="Unpaid volunteering opportunity"),
            update_date=date(2026, 9, 15),
            employer_type="VCSE",
            location_area="Nottingham",
            job_area="Community & Outreach",
        ).included)
        self.assertEqual("Other", normalize_contract("Term Time Only"))

    def vacancy(self, source_id, reference="", *, organization="Example Council", location="Nottingham", host=""):
        return NormalizedVacancy(
            organization=organization,
            employer_type="Council",
            job_title="Administrator",
            job_area="Administration & Business Support",
            location=location,
            location_area="Nottingham",
            closing_date="2027-01-31",
            closing_time="",
            contract_type="Permanent",
            work_pattern="Full-time",
            salary="",
            apply_url=f"https://example.test/{source_id}",
            job_reference=reference,
            date_checked="2026-09-15",
            source_url=f"https://example.test/{source_id}",
            source_id=source_id,
            verification_method="direct-primary-advert",
            advertised_employer=organization,
            host_organization=host,
            host_association_verified=bool(host),
        )

    def test_dedupe_uses_real_reference_and_host_scope(self):
        selected, duplicates = deduplicate([
            self.vacancy("mirror", "R-1", organization="Agency", host="Example Council"),
            self.vacancy("primary", "R-1", organization="Agency", host="Example Council"),
        ])
        self.assertEqual(1, len(selected))
        self.assertEqual(1, len(duplicates))
        selected, duplicates = deduplicate([
            self.vacancy("college", organization="Agency", host="Nottingham College"),
            self.vacancy("nhs", organization="Agency", host="Example NHS Trust"),
        ])
        self.assertEqual(2, len(selected))
        self.assertEqual([], duplicates)

    def test_resolution_key_never_uses_public_url_as_public_reference(self):
        record = self.raw(source_record_id="INTERNAL-7", reference_raw="")
        self.assertEqual("source::INTERNAL-7", resolution_key(record))
        self.assertEqual("", record.reference_raw)


if __name__ == "__main__":
    unittest.main()
