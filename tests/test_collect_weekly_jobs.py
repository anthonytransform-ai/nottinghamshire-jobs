import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.collect_weekly_jobs import (
    CollectionError, PILOTS, Transport, collect, next_page, parse_detail, parse_list, rendered_access_blocked,
)
from scripts.weekly_job_update import RawCandidateStatus, SourceRun, SourceRunStatus, WorkingStateStore, load_registry


UON_LIST = '''<h2>Administrative opportunities</h2><div class="vacancylist">
<p><a href="vacancy.aspx?ref=REF1">Example Administrator</a>
<span><b>Closing Date: </b>23 October 2026</span><span><b>Salary: </b>£30,000</span></p>
<p><a href="vacancy.aspx?ref=REF2">Example Technician</a></p></div>'''
UON_DETAIL = '''<div id="main"><h1 class="pagetitle">Example Administrator</h1>
<div class="advertheader"><p><b>Location</b><br>University Park</p>
<p><b>Salary</b><br>£30,000</p><p><b>Closing Date</b><br>23 October 2026</p>
<p><b>Reference</b><br>REF1</p></div><p>Support student events and maintain administrative records.</p></div>'''
NUH_LIST = '''<div class="hj-job-list"><h2>Vacancies</h2><ol>
<li class="hj-job"><a href="/job/UK/Nottingham/Clinical-v100?_ts=1">
<div class="hj-jobtitle">Example Nurse</div><div class="hj-employername">Example NHS Trust</div>
<div class="hj-locationtown">Nottingham</div><div class="hj-salary">Salary: £30,000</div>
</a></li></ol></div>'''
NUH_DETAIL = '''<div class="hj-job-details"><dl><dt>Contract</dt><dd>Permanent</dd>
<dt>Hours</dt><dd>Part time - 20 hours</dd><dt>Job ref</dt><dd>NHS-1</dd>
<dt>Site</dt><dd>City Hospital</dd><dt>Town</dt><dd>Nottingham</dd>
<dt>Closing</dt><dd>23/10/2026 23:59</dd><dt>Employer</dt><dd>Example NHS Trust</dd></dl></div>
<section id="hj-job-advert"><h3>Job overview</h3><p><strong></strong>Provide patient care and support colleagues.</p></section>'''


class FixtureTransport:
    list_html = UON_LIST
    detail_html = UON_DETAIL
    fail_list = False
    fail_detail = False
    calls = []

    def __init__(self, root, source, **options):
        self.source = source
        self.timeout = 25000
        self.requests = self.cache_hits = 0

    def fetch(self, url, rendered=False):
        type(self).calls.append(url)
        self.requests += 1
        is_list = "ref=" not in url and "-v" not in url
        if (is_list and self.fail_list) or (not is_list and self.fail_detail):
            raise CollectionError("Controlled unavailable response")
        detail = self.detail_html.replace("REF1", "REF2") if "ref=REF2" in url else self.detail_html
        return (self.list_html if is_list else detail), dict(url=url, file="fixture.html", sha256="fixture")

    def close(self):
        pass


class CollectorParserTests(unittest.TestCase):
    def test_uon_preserves_exact_hrefs_references_facts_and_section(self):
        source = load_registry().get(PILOTS[0])
        rows = parse_list(source, UON_LIST, source.fixed_route)
        self.assertEqual(["REF1", "REF2"], [r["reference"] for r in rows])
        self.assertEqual("https://jobs.nottingham.ac.uk/vacancy.aspx?ref=REF1", rows[0]["url"])
        self.assertEqual("23 October 2026", rows[0]["deadline"])
        self.assertEqual("£30,000", rows[0]["salary"])
        self.assertEqual("Administrative opportunities", rows[0]["context"])
        detail = parse_detail(source, rows[0], UON_DETAIL)
        self.assertEqual("University Park", detail["raw_location"])
        self.assertIn("Support student events", detail["detail_body"])
        self.assertEqual("", detail["raw_contract"])
        self.assertNotIn("job_area", detail)

    def test_missing_list_challenge_and_missing_identity_are_errors(self):
        for source_id, html in ((PILOTS[0], "<p>Server unavailable</p>"), (PILOTS[2], '<div class="hj-job-list">Please complete the security check</div>'), (PILOTS[2], '<div class="hj-job-list"><li class="hj-job">Missing link</li></div>')):
            source = load_registry().get(source_id)
            with self.subTest(source_id=source_id), self.assertRaises(CollectionError):
                parse_list(source, html, source.fixed_route)

    def test_ntu_keeps_jobtrain_id_separate_from_public_reference(self):
        source = load_registry().get(PILOTS[1])
        html = '''<input id="totalMatchRecords" value="1"><div class="job-card">
<a href="/Job/JobDetail?JobId=12">Administrator</a><p><strong>Job reference:</strong> PUBLIC-2</p>
<p><strong>Location:</strong> City Campus</p><p><strong>Employment type:</strong> Fixed Term Contract</p>
<p><strong>Salary / Grade :</strong> £30,000</p><a href="/Job/JobDetail?JobId=12">More..</a></div>'''
        rows = parse_list(source, html, source.fixed_route)
        self.assertEqual(1, len(rows))
        self.assertEqual("12", rows[0]["platform_id"])
        self.assertEqual("PUBLIC-2", rows[0]["reference"])
        self.assertEqual("£30,000", rows[0]["salary"])
        posting = {"@type": "JobPosting", "description": "<p>Support students &amp; lecturers.</p>", "employmentType": "Fixed Term Contract", "validThrough": "2026-10-23T00:00"}
        detail = parse_detail(source, rows[0], '<script type="application/ld+json">' + json.dumps(posting) + '</script>')
        self.assertEqual("Support students & lecturers.", detail["detail_body"])
        self.assertEqual("2026-10-23T00:00", detail["raw_deadline"])

    def test_ntu_static_zero_shell_is_not_accepted(self):
        source = load_registry().get(PILOTS[1])
        with self.assertRaises(CollectionError):
            parse_list(source, '<div id="searchResults">No jobs loaded</div>', source.fixed_route)

    def test_nuh_preserves_individual_link_public_ref_and_raw_contract(self):
        source = load_registry().get(PILOTS[2])
        row = parse_list(source, NUH_LIST, source.fixed_route)[0]
        self.assertEqual("100", row["platform_id"])
        self.assertTrue(row["url"].endswith("Clinical-v100?_ts=1"))
        detail = parse_detail(source, row, NUH_DETAIL)
        self.assertEqual("NHS-1", detail["source_reference"])
        self.assertEqual("City Hospital, Nottingham", detail["raw_location"])
        self.assertEqual("Part time - 20 hours", detail["raw_work_pattern"])
        self.assertEqual("Permanent", detail["raw_contract"])
        self.assertIn("Provide patient care", detail["detail_body"])

    def test_nuh_zero_requires_explicit_empty_message(self):
        source = load_registry().get(PILOTS[2])
        self.assertEqual([], parse_list(source, '<div class="hj-job-list">No current vacancies</div>', source.fixed_route))
        with self.assertRaises(CollectionError):
            parse_list(source, '<div class="hj-job-list"></div>', source.fixed_route)

    def test_detail_cannot_silently_switch_advert_identity(self):
        source = load_registry().get(PILOTS[0])
        row = parse_list(source, UON_LIST, source.fixed_route)[1]
        with self.assertRaises(CollectionError):
            parse_detail(source, row, UON_DETAIL)

    def test_next_retains_registered_employer_and_rejects_ambiguous_route(self):
        source = load_registry().get(PILOTS[2])
        self.assertEqual("https://www.healthjobsuk.com/jobs_emp?emp=358&page=2", next_page(source, '<a rel="next" href="?emp=358&page=2">Next</a>', source.fixed_route))
        with self.assertRaises(CollectionError):
            next_page(source, '<a rel="next" href="?emp=999&page=2">Next</a>', source.fixed_route)
        with self.assertRaises(CollectionError):
            next_page(source, '<a href="?emp=358&page=2">Next</a><a href="?emp=358&page=3">Next</a>', source.fixed_route)

    def test_govuk_teaching_vacancies_preserves_slug_and_detail_application(self):
        source = load_registry().get("govuk-teaching-vacancies")
        listing = '''<ul><li class="search-results__item"><h2><a class="view-vacancy-link" href="/jobs/teacher-tuxford">Teacher</a></h2>
        <p class="address">Tuxford Primary Academy, Nottinghamshire</p><dl><dt>Closing date</dt><dd>31 October 2026</dd>
        <dt>Full time equivalent salary</dt><dd>£30,000 to £46,000</dd></dl></li></ul>'''
        row = parse_list(source, listing, source.fixed_route)[0]
        self.assertEqual("teacher-tuxford", row["platform_id"])
        self.assertEqual("https://teaching-vacancies.service.gov.uk/jobs/teacher-tuxford", row["url"])
        detail = '''<h1>Teacher</h1><span class="govuk-caption-l">Tuxford Primary Academy, Nottinghamshire</span>
        <div id="job-details"><dl><dt>Contract type</dt><dd>Permanent</dd><dt>Working pattern</dt><dd>Full time</dd></dl></div>
        <div class="editor-rendered-content"><p>Teach pupils and support the school community.</p></div>
        <a data-link-type="external_advert_link" href="https://example.org/apply/teacher-tuxford">Apply</a>
        <script type="application/ld+json">''' + json.dumps({"@type": "JobPosting", "url": row["url"], "validThrough": "2026-10-31", "hiringOrganization": {"name": "Tuxford Primary Academy"}}) + '''</script>'''
        facts = parse_detail(source, row, detail)
        self.assertIn("Teach pupils", facts["detail_body"])
        self.assertEqual("Permanent", facts["raw_contract"])
        self.assertEqual("https://example.org/apply/teacher-tuxford", facts["raw_apply_url"])

    def test_govuk_detail_uses_supplementary_body_when_editor_content_is_empty(self):
        source = load_registry().get("govuk-teaching-vacancies")
        row = {"url": "https://teaching-vacancies.service.gov.uk/jobs/teacher-tuxford"}
        detail = '''<h1>Teacher</h1><div class="editor-rendered-content"><p><br></p></div>
        <div class="govuk_body"><p>Teach pupils and support the school community.</p></div>
        <script type="application/ld+json">''' + json.dumps({"@type": "JobPosting", "url": row["url"]}) + '''</script>'''
        facts = parse_detail(source, row, detail)
        self.assertIn("Teach pupils", facts["detail_body"])

    def test_rendered_itrent_security_marker_is_classified_as_access_block(self):
        self.assertTrue(rendered_access_blocked("A possible security violation has been detected on displaying this page. [E0227SECURITY]"))
        self.assertFalse(rendered_access_blocked("Job profile for Housing Officer"))

    def test_itrent_preserves_registered_wvid_and_vacancy_id(self):
        source = load_registry().get("ashfield-district-council")
        listing = '''<p>Results - 1 match found</p><div class="Mhr-card Mhr-jobDetail Mhr-jobDetail--listItem"
        vac-id="0947126vEt" bu-send="/ce0930li_webrecruitment/wrd/run/ETREC148GF.open?WVID=6777852QI7&amp;VACANCY_ID=0947126vEt">
        <a class="Mhr-jobDetailTitleLink" href="#">Housing Officer</a><div><span class="Mhr-jobDetailEntry--label">Salary</span><span class="Mhr-jobDetailEntry--text">£35,000</span></div>
        <div><span class="Mhr-jobDetailEntry--label">Location</span><span class="Mhr-jobDetailEntry--text">Kirkby-in-Ashfield</span></div></div>'''
        row = parse_list(source, listing, source.fixed_route)[0]
        self.assertEqual("0947126vEt", row["platform_id"])
        self.assertIn("WVID=6777852QI7", row["url"])
        detail = '''<div class="Mhr-jobProfile"><h1 class="Mhr-jobProfile--title">Housing Officer</h1>
        <div class="Mhr-jobProfile--closingDate">Apply by 31 October 2026</div>
        <div><span class="Mhr-jobProfile--dataListLabel">Salary</span><span class="Mhr-jobProfile--dataListData">£35,000</span></div>
        <div><span class="Mhr-jobProfile--dataListLabel">Basis</span><span class="Mhr-jobProfile--dataListData">Full time</span></div>
        <div class="Mhr-jobProfile--description"><p>Support residents and deliver housing services.</p></div>
        <a href="/apply/0947126vEt">Apply online</a></div>'''
        facts = parse_detail(source, row, detail)
        self.assertEqual("Full time", facts["raw_work_pattern"])
        self.assertEqual("31 October 2026", facts["raw_deadline"])
        self.assertTrue(facts["raw_apply_url"].endswith("/apply/0947126vEt"))

    def test_oracle_cloud_preserves_rendered_job_id_and_detail_facts(self):
        source = load_registry().get("nottingham-city-council")
        listing = '''<div>Job search results 1</div><div class="job-list-item"><a class="job-list-item__link"
        href="/hcmUI/CandidateExperience/en/sites/ncc/job/8462"><span class="job-tile__title">Service Manager</span>
        <span class="job-list-item__job-info-value">Nottingham</span></a></div>'''
        row = parse_list(source, listing, source.fixed_route)[0]
        self.assertEqual("8462", row["platform_id"])
        detail = '''<h1 class="heading job-details__title">Service Manager</h1><div class="job-details__subtitle">Nottingham</div>
        <div class="job-details__description-content">Salary: £45,000 Location: Nottingham Contract: Permanent Number of posts: 1 Closing Date: 31 October 2026 Job Identification 8462
        Lead the service and support residents.</div>'''
        facts = parse_detail(source, row, detail)
        self.assertEqual("£45,000", facts["raw_salary"])
        self.assertEqual("Permanent", facts["raw_contract"])
        self.assertIn("Lead the service", facts["detail_body"])


class CollectorLifecycleTests(unittest.TestCase):
    def setUp(self):
        FixtureTransport.calls = []
        FixtureTransport.fail_list = FixtureTransport.fail_detail = False
        FixtureTransport.list_html, FixtureTransport.detail_html = UON_LIST, UON_DETAIL
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, **options):
        return collect(PILOTS[0], self.root, transport_factory=FixtureTransport, **options)

    def test_success_and_completed_resume_make_no_new_requests(self):
        result = self.collect()
        self.assertEqual(SourceRunStatus.OK, result.status)
        self.assertEqual(2, result.candidate_count)
        self.assertEqual(2, result.collection_context["detail_count"])
        calls = list(FixtureTransport.calls)
        self.assertEqual(SourceRunStatus.OK, self.collect().status)
        self.assertEqual(calls, FixtureTransport.calls)

    def test_controlled_interruption_is_partial_and_resume_reuses_done_details(self):
        result = self.collect(stop_after=1)
        self.assertEqual(SourceRunStatus.PARTIAL, result.status)
        self.assertEqual(1, result.collection_context["detail_count"])
        self.assertFalse(result.normal_collection_completed)
        self.assertIn("Controlled interruption", result.limitation)
        FixtureTransport.calls = []
        resumed = self.collect()
        self.assertEqual(SourceRunStatus.OK, resumed.status)
        self.assertEqual(1, len(FixtureTransport.calls))
        self.assertIn("REF2", FixtureTransport.calls[0])
        self.assertTrue(all(c.status == RawCandidateStatus.DETAIL_COMPLETE for c in WorkingStateStore(self.root).load_raw_candidates()))

    def test_failed_access_never_becomes_empty(self):
        FixtureTransport.fail_list = True
        result = self.collect()
        self.assertEqual(SourceRunStatus.ERROR, result.status)
        self.assertEqual(0, result.candidate_count)
        self.assertIn("Controlled unavailable", result.error)
        self.assertFalse(result.normal_collection_completed)

    def test_successful_explicit_zero_is_empty(self):
        FixtureTransport.list_html = '<div class="vacancylist">No vacancies</div>'
        result = self.collect()
        self.assertEqual(SourceRunStatus.EMPTY, result.status)
        self.assertTrue(result.normal_collection_completed)

    def test_unexplained_zero_is_error(self):
        FixtureTransport.list_html = '<div class="vacancylist"></div>'
        self.assertEqual(SourceRunStatus.ERROR, self.collect().status)

    def test_detail_failure_retains_useful_rows_with_partial(self):
        FixtureTransport.fail_detail = True
        result = self.collect()
        self.assertEqual(SourceRunStatus.PARTIAL, result.status)
        self.assertEqual(2, result.candidate_count)
        self.assertEqual(0, result.collection_context["detail_count"])
        self.assertTrue(all(c.provenance.get("detail_error") for c in WorkingStateStore(self.root).load_raw_candidates()))

    def test_missing_detail_shape_is_partial_not_ok(self):
        FixtureTransport.detail_html = '<html><p>Unexpected response</p></html>'
        self.assertEqual(SourceRunStatus.PARTIAL, self.collect().status)

    def test_same_run_concurrent_writer_is_refused(self):
        (self.root / ".collector.lock").write_text("another process")
        with self.assertRaises(FileExistsError):
            self.collect()
        self.assertFalse((self.root / "source-runs.json").exists())

    def test_corrupt_success_checkpoint_cannot_skip_collection(self):
        self.collect()
        (self.root / "raw-candidates.jsonl").write_text("")
        with self.assertRaises(CollectionError):
            self.collect()

    def test_running_state_without_checkpoint_is_not_reused_as_fresh_evidence(self):
        run = SourceRun(PILOTS[0])
        run.begin("2026-10-12T10:00:00+01:00")
        WorkingStateStore(self.root).save_source_runs([run])
        with self.assertRaises(CollectionError):
            self.collect()

    def test_cached_evidence_checksum_is_verified(self):
        source = load_registry().get(PILOTS[0])
        transport = Transport(self.root, source)
        meta = transport.save(UON_LIST, source.fixed_route, "http:" + source.fixed_route)
        (transport.root / meta["file"]).write_text("corrupt", encoding="utf-8")
        with self.assertRaises(CollectionError):
            transport.fetch(source.fixed_route)

    def test_evidence_cache_preserves_exact_crlf_bytes_on_windows(self):
        source = load_registry().get(PILOTS[0])
        transport = Transport(self.root, source)
        html = UON_LIST.replace("\n", "\r\n")
        meta = transport.save(html, source.fixed_route, "http:" + source.fixed_route)
        self.assertEqual(html.encode("utf-8"), (transport.root / meta["file"]).read_bytes())
        cached, _ = transport.fetch(source.fixed_route)
        self.assertEqual(html, cached)
        self.assertEqual(1, transport.cache_hits)

    def test_source_candidate_checkpoint_keeps_other_source_evidence(self):
        self.collect(stop_after=1)
        store = WorkingStateStore(self.root)
        other = store.load_raw_candidates()[0]
        from dataclasses import replace
        other = replace(other, source_id=PILOTS[2])
        store.append_raw_candidate(other)
        self.collect()
        self.assertEqual(3, len(store.load_raw_candidates()))
        self.assertEqual(1, sum(c.source_id == PILOTS[2] for c in store.load_raw_candidates()))


class RenderedFixture:
    """Normal NTU DOM snapshots and controls, with no external browser dependency."""
    def __init__(self, stages, counts, stalled=False):
        self.stages, self.counts, self.stalled = stages, counts, stalled
        self.index = 0
        self.url = load_registry().get(PILOTS[1]).fixed_route

    def goto(self, *args, **kwargs):
        self.index = 0
        return type("Response", (), {"status": 200})()

    def wait_for_function(self, expression, **kwargs):
        if "arg" in kwargs and self.stages[self.index] <= kwargs["arg"]:
            raise TimeoutError("Controlled stalled Load More")

    def get_by_text(self, *args, **kwargs):
        return type("NoCookieBanner", (), {"count": lambda self: 0})()

    def content(self):
        count = self.stages[self.index]
        empty = "No jobs found" if count == 0 else ""
        return '<input id="totalMatchRecords" value="' + str(self.counts[self.index][0]) + '">' + empty + ''.join(f'<div class="job-card"><a href="/Job/JobDetail?JobId={n}">Role {n}</a><p><strong>Job reference:</strong> PUBLIC-{n}</p></div>' for n in range(count))

    def locator(self, selector):
        parent = self
        class Control:
            def evaluate_all(self, expression):
                return [str(c) for c in parent.counts[parent.index]]

            def is_visible(self):
                return parent.index < len(parent.stages) - 1 or parent.stalled

            def click(self, **kwargs):
                if not parent.stalled:
                    parent.index += 1
        return Control()


class RenderedTransport(FixtureTransport):
    fixture = None

    def browser_page(self):
        return self.fixture

    def save(self, html, url, key):
        return dict(url=url, file=key, sha256="fixture")

    def fetch(self, url, rendered=False):
        self.requests += 1
        return '<script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "url": url, "description": "<p>Deliver current role duties.</p>"}) + '</script>', dict(url=url)


class RenderedEnumerationTests(unittest.TestCase):
    def run_fixture(self, fixture):
        RenderedTransport.fixture = fixture
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            return collect(PILOTS[1], root, transport_factory=RenderedTransport)

    def test_normal_load_more_with_duplicate_agreeing_counts_completes(self):
        result = self.run_fixture(RenderedFixture([2, 4, 5], [[5], [5, 5], [5, 5, 5]]))
        self.assertEqual(SourceRunStatus.OK, result.status)
        self.assertEqual(5, result.candidate_count)
        self.assertEqual(3, result.collection_context["pages"])

    def test_hidden_load_more_with_missing_jobs_is_partial(self):
        result = self.run_fixture(RenderedFixture([2, 4], [[5], [5, 5]]))
        self.assertEqual(SourceRunStatus.PARTIAL, result.status)
        self.assertIn("4 of 5", result.limitation)

    def test_conflicting_duplicate_counts_are_partial(self):
        result = self.run_fixture(RenderedFixture([2, 4], [[5], [5, 6]]))
        self.assertEqual(SourceRunStatus.PARTIAL, result.status)
        self.assertIn("counts conflict", result.limitation)

    def test_stalled_load_more_retains_candidates_as_partial(self):
        result = self.run_fixture(RenderedFixture([2], [[5]], stalled=True))
        self.assertEqual(SourceRunStatus.PARTIAL, result.status)
        self.assertEqual(2, result.candidate_count)
        self.assertIn("stalled Load More", result.limitation)

    def test_rendered_explicit_zero_is_empty(self):
        result = self.run_fixture(RenderedFixture([0], [[0]]))
        self.assertEqual(SourceRunStatus.EMPTY, result.status)
        self.assertTrue(result.normal_collection_completed)


if __name__ == "__main__":
    unittest.main()
