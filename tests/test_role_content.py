import unittest

from scripts.collect_weekly_jobs import Document, parse_detail
from scripts.role_content import role_paragraphs, structured_teaching_facts
from scripts.weekly_job_update import load_registry


class RoleContentTests(unittest.TestCase):
    def test_ntu_2494_shape_prefers_role_over_branding_and_about_us(self):
        source = load_registry().get("nottingham-trent-university")
        html = '''<div id="Media_Rich_Advert"><h2>Build a Rewarding Career.</h2>
        <h2>Doing things differently.</h2><h3>About the Role</h3>
        <p>Teach Computer Science on undergraduate and postgraduate programmes.</p>
        <h3>About Us</h3><p>Our outstanding campus and benefits.</p></div>
        <script type="application/ld+json">{"@type":"JobPosting","description":"Branding first","url":"https://vacancies.ntu.ac.uk/Job/JobDetail?JobId=2494"}</script>'''
        detail = parse_detail(source, {"url": "https://vacancies.ntu.ac.uk/Job/JobDetail?JobId=2494", "platform_id": "2494"}, html)
        self.assertEqual("Teach Computer Science on undergraduate and postgraduate programmes.", detail["detail_body"])

    def test_oracle_role_section_excludes_metadata_generic_copy_and_about_you(self):
        source = load_registry().get("nottingham-city-council")
        html = '''<div class="job-details__description-content"><p>Contract: Permanent. We've got an exciting opportunity.</p>
        <h3>About the Role</h3><p>Manage payables and receivables and reconcile financial controls.</p>
        <h3>About You</h3><p>You must have finance experience.</p></div>'''
        self.assertEqual(["Manage payables and receivables and reconcile financial controls."], role_paragraphs(source, Document(html).root))

    def test_uon_role_paragraphs_skip_fact_header_and_application_furniture(self):
        source = load_registry().get("university-of-nottingham")
        html = '''<div id="main"><h1>Researcher</h1><div class="advertheader"><p>Area Chemistry Location Jubilee Campus Salary £40,000</p></div>
        <p>Develop electrolytes and study aluminium battery interphases.</p><p>Informal enquiries: email us.</p><p>Apply Online</p></div>'''
        self.assertEqual(["Develop electrolytes and study aluminium battery interphases."], role_paragraphs(source, Document(html).root))

    def test_nhs_overview_and_duties_are_available_without_trust_boilerplate(self):
        source = load_registry().get("nottingham-university-hospitals")
        html = '''<section id="hj-job-advert"><h3>Job overview</h3><p>Join our fantastic team.</p>
        <h3>Main duties of the job</h3><p>Coordinate nursing care and supervise staff.</p>
        <h3>Working for our organisation</h3><p>Excellent benefits.</p></section>'''
        self.assertEqual(["Join our fantastic team.", "Coordinate nursing care and supervise staff."], role_paragraphs(source, Document(html).root))

    def test_govuk_structured_facts_do_not_depend_on_title(self):
        html = '''<h3>Job role</h3><ul><li>Teacher or lecturer</li></ul><h3>Subject</h3><p>History</p>
        <h3>Key stage</h3><p>Key stage 4</p>'''
        facts = structured_teaching_facts(Document(html).root)
        self.assertEqual("History", facts["subject"])
        self.assertEqual("Key stage 4", facts["key stage"])

    def test_govuk_summary_list_facts_and_named_job_summary_section(self):
        source = load_registry().get("govuk-teaching-vacancies")
        html = '''<section id="job-details"><dl><div><dt><h3>Subject</h3></dt><dd>History</dd></div></dl>
        <h2>Teacher job summary</h2><p>Teach History to Key stage 4 pupils.</p>
        <h2>What the school offers its staff</h2><p>Excellent benefits.</p></section>'''
        root = Document(html).root
        self.assertEqual("History", structured_teaching_facts(root)["subject"])
        self.assertEqual(["Teach History to Key stage 4 pupils."], role_paragraphs(source, root))

    def test_govuk_later_mission_section_survives_earlier_benefits(self):
        source = load_registry().get("govuk-teaching-vacancies")
        html = '''<section id="job-details"><h2>Site Manager job summary</h2><p>Exciting career.</p>
        <p>What's in it for you?</p><p>Benefits.</p><p>Your mission as site manager:</p>
        <p>Maintain the school buildings and supervise contractors.</p><h2>About the school</h2><p>Branding.</p></section>'''
        self.assertEqual(["Maintain the school buildings and supervise contractors."], role_paragraphs(source, Document(html).root))

    def test_uon_about_you_label_can_contain_explicit_duties(self):
        source = load_registry().get("university-of-nottingham")
        html = '''<div id="main"><p>About you</p><p>Support trial administration and maintain study records.</p>
        <p>About us</p><p>Our leading university.</p></div>'''
        self.assertIn("Support trial administration and maintain study records.", role_paragraphs(source, Document(html).root))


if __name__ == "__main__":
    unittest.main()
