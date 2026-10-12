import unittest

from scripts.collect_weekly_jobs import parse_detail
from scripts.weekly_job_update import load_registry


class OracleSalaryTests(unittest.TestCase):
    def salary(self, description):
        source = load_registry().get("nottingham-city-council")
        row = dict(platform_id="8879", url=source.fixed_route.rstrip("/") + "/job/8879")
        html = '<h1 class="job-details__title">Example role</h1><div class="job-details__description-content">' + description + '</div>'
        return parse_detail(source, row, html)["raw_salary"]

    def test_modern_finance_icons_without_old_next_label_do_not_spill(self):
        for value in ("£58,602 - £62,109 per annum (pro rata for part time)", "£47,665 - £50,908 per annum"):
            with self.subTest(value=value):
                html = '<p>📍 Nottingham / Hybrid<br>💰 <strong>Salary:</strong> ' + value + '<br>🏢 Finance &amp; Resources Directorate</p><p>About the Role</p><p>Lead finance and prepare reports.</p>'
                self.assertEqual(value, self.salary(html))

    def test_gas_engineer_paragraph_is_bounded_despite_base_office_label(self):
        value = "Grade H – starting salary is £42,123 (level 1) raising to £45,529 (level 4) per annum"
        html = '<p>Contract type: Permanent</p><p>Salary: ' + value + '</p><p>Base office: Harvey Road</p><p>We have an exciting opportunity.</p>'
        self.assertEqual(value, self.salary(html))

    def test_long_legitimate_salary_overtime_and_allowance_are_not_truncated(self):
        value = "£37,563 – £40,444 per annum (pro-rata for part-time) Overtime rates are based on time-and-a-half of the basic hourly rate; actual overtime is paid at single time for the first 5 hours, increasing to time-and-a-half thereafter) Plus £980 yearly tool allowance (paid pro rata'd per month)"
        self.assertEqual(value, self.salary('<p>Salary: ' + value + ' Location: Eastcroft Depot, Nottingham</p><p>About the Role</p><p>Maintain vehicles.</p>'))

    def test_flat_legacy_field_requires_a_known_boundary(self):
        self.assertEqual("£45,000", self.salary("Salary: £45,000 Location: Nottingham Contract: Permanent Lead the service."))
        self.assertEqual("", self.salary("Salary: £45,000 We have an exciting opportunity to lead the service and support residents."))

    def test_salary_absent_never_infers_pay_from_role_budget(self):
        self.assertEqual("", self.salary('<p>About the Role</p><p>Manage a £20m programme budget.</p>'))
