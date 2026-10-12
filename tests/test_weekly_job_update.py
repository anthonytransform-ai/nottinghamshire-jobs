import tempfile
import unittest
from pathlib import Path

from scripts.weekly_job_update import (
    RawCandidate,
    RawCandidateStatus,
    SourceRun,
    SourceRunStatus,
    WorkingStateStore,
    load_registry,
)


EXPECTED_SOURCE_IDS = [
    "nottinghamshire-tal",
    "nottingham-city-council",
    "ashfield-district-council",
    "mansfield-district-council",
    "bassetlaw-district-council",
    "newark-and-sherwood-district-council",
    "gedling-borough-council",
    "broxtowe-borough-council",
    "rushcliffe-borough-council",
    "nottingham-university-hospitals",
    "nottinghamshire-healthcare",
    "sherwood-forest-hospitals",
    "university-of-nottingham",
    "nottingham-trent-university",
    "nottingham-college",
    "west-nottinghamshire-college",
    "north-notts-college-rnn-group",
    "govuk-teaching-vacancies",
    "nottingham-cvs",
]


class RegistryTests(unittest.TestCase):
    def test_canonical_registry_contains_the_fixed_19_sources(self):
        registry = load_registry()

        self.assertEqual(19, registry.source_count)
        self.assertEqual(EXPECTED_SOURCE_IDS, [source.source_id for source in registry.sources])
        self.assertEqual(19, len({source.source_id for source in registry.sources}))
        self.assertTrue(all(source.fixed_route.startswith(("http://", "https://")) for source in registry.sources))

    def test_critical_routes_and_platform_identity_are_preserved(self):
        registry = load_registry()

        tal = registry.get("nottinghamshire-tal")
        self.assertIn("appcentre-ext/brand-8", tal.fixed_route)
        self.assertEqual("/opp/<id>-.../", tal.individual_route_pattern)

        university = registry.get("university-of-nottingham")
        self.assertEqual("https://jobs.nottingham.ac.uk/vacancies.aspx?cat=-1", university.fixed_route)

        ntu = registry.get("nottingham-trent-university")
        self.assertEqual("https://vacancies.ntu.ac.uk/Home/Job", ntu.fixed_route)

        teaching = registry.get("govuk-teaching-vacancies")
        self.assertIn("location=Nottinghamshire&page=1", teaching.fixed_route)

        self.assertEqual("6777852QI7", registry.get("ashfield-district-council").wvid)
        self.assertEqual("4128782IuI", registry.get("mansfield-district-council").wvid)
        self.assertEqual("8070960wxx", registry.get("bassetlaw-district-council").wvid)
        self.assertEqual("3373962BPM", registry.get("newark-and-sherwood-district-council").wvid)
        self.assertEqual("5245470Prv", registry.get("west-nottinghamshire-college").wvid)
        self.assertEqual("8759023jQy", registry.get("north-notts-college-rnn-group").wvid)

    def test_skill_routes_to_the_same_registry_and_playbook_reference(self):
        root = Path(__file__).resolve().parents[1]
        skill = (root / ".agents/skills/weekly-job-update/SKILL.md").read_text(encoding="utf-8")
        playbook = (root / ".agents/skills/weekly-job-update/references/playbook.md").read_text(encoding="utf-8")

        self.assertIn("references/source-registry.json", skill)
        self.assertIn("references/playbook.md", skill)
        self.assertIn("cat=-1", playbook)
        self.assertIn("/Home/Job", playbook)
        self.assertIn("exact 16-column `jobs.csv`", playbook)
        self.assertIn("source completion gate", playbook.lower())


class SourceRunTests(unittest.TestCase):
    def test_empty_is_a_successful_zero_candidate_collection(self):
        run = SourceRun("example-source")
        run.begin("2026-10-12T10:00:00+01:00")
        run.complete(
            SourceRunStatus.EMPTY,
            candidate_count=0,
            finished_at="2026-10-12T10:01:00+01:00",
            normal_collection_completed=True,
        )

        self.assertEqual(SourceRunStatus.EMPTY, run.status)
        self.assertTrue(run.normal_collection_completed)
        self.assertEqual(0, run.candidate_count)

    def test_empty_cannot_hide_a_blocked_or_failed_source(self):
        for normal_collection_completed, limitation, error in (
            (False, "", ""),
            (True, "", "blocked by verification"),
        ):
            with self.subTest(normal_collection_completed=normal_collection_completed, error=error):
                run = SourceRun("example-source")
                run.begin("2026-10-12T10:00:00+01:00")
                with self.assertRaises(ValueError):
                    run.complete(
                        SourceRunStatus.EMPTY,
                        candidate_count=0,
                        finished_at="2026-10-12T10:01:00+01:00",
                        normal_collection_completed=normal_collection_completed,
                        limitation=limitation,
                        error=error,
                    )

    def test_partial_and_error_require_their_material_explanation(self):
        partial = SourceRun("partial-source")
        partial.begin("2026-10-12T10:00:00+01:00")
        with self.assertRaises(ValueError):
            partial.complete(
                SourceRunStatus.PARTIAL,
                candidate_count=2,
                finished_at="2026-10-12T10:01:00+01:00",
                normal_collection_completed=False,
            )

        error = SourceRun("error-source")
        error.begin("2026-10-12T10:00:00+01:00")
        with self.assertRaises(ValueError):
            error.complete(
                SourceRunStatus.ERROR,
                candidate_count=0,
                finished_at="2026-10-12T10:01:00+01:00",
                normal_collection_completed=False,
            )


class RawCandidateTests(unittest.TestCase):
    def test_raw_candidate_preserves_uncertain_text_and_provenance(self):
        candidate = RawCandidate(
            source_id="nottinghamshire-tal",
            source_family="council",
            raw_organization="Example School",
            raw_title="Administrator",
            raw_location="Nottinghamshire (location to verify)",
            raw_deadline="No closing date shown",
            raw_salary="See advert",
            raw_contract="",
            raw_work_pattern="",
            source_reference="REF-1",
            source_platform_id="31234",
            list_url="https://example.org/jobs",
            source_url="https://example.org/jobs",
            detail_url="https://example.org/jobs/1",
            apply_url="https://example.org/jobs/1",
            detail_body="Role purpose and duties as exposed by the advert.",
            collected_at="2026-10-12T10:00:00+01:00",
            collection_method="tal-rendered-list",
            provenance={"page": 1, "href_observed": True},
        )

        restored = RawCandidate.from_mapping(candidate.to_mapping())
        self.assertEqual(RawCandidateStatus.CAPTURED, restored.status)
        self.assertEqual("See advert", restored.raw_salary)
        self.assertEqual("", restored.raw_contract)
        self.assertEqual("31234", restored.source_platform_id)
        self.assertEqual("Role purpose and duties as exposed by the advert.", restored.detail_body)
        self.assertEqual(True, restored.provenance["href_observed"])

    def test_raw_candidate_requires_a_source_url(self):
        with self.assertRaises(ValueError):
            RawCandidate(
                source_id="example-source",
                source_family="education",
                collected_at="2026-10-12T10:00:00+01:00",
                collection_method="test",
            )


class WorkingStateTests(unittest.TestCase):
    def test_state_store_persists_runs_raw_candidates_and_candidate_states(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
            store = WorkingStateStore(temporary_directory)
            run = SourceRun("example-source")
            run.begin("2026-10-12T10:00:00+01:00")
            run.complete(
                SourceRunStatus.OK,
                candidate_count=1,
                finished_at="2026-10-12T10:01:00+01:00",
                normal_collection_completed=True,
            )
            store.save_source_runs([run])
            store.append_raw_candidate(
                RawCandidate(
                    source_id="example-source",
                    source_family="education",
                    raw_title="Administrator",
                    list_url="https://example.org/jobs",
                    collected_at="2026-10-12T10:00:00+01:00",
                    collection_method="test",
                )
            )
            store.save_draft_candidates([{"job_title": "Administrator", "status": "draft"}])
            store.save_final_candidates([{"job_title": "Administrator", "status": "final"}])

            self.assertEqual(SourceRunStatus.OK, store.load_source_runs()[0].status)
            self.assertEqual(1, len(store.load_raw_candidates()))
            self.assertEqual("draft", store.load_candidate_state("draft")[0]["status"])
            self.assertEqual("final", store.load_candidate_state("final")[0]["status"])


if __name__ == "__main__":
    unittest.main()
