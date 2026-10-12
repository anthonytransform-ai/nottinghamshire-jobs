import unittest

from scripts.participant_job_policy import participant_destination, summary_review_flags, validate_participant_url
from scripts.prepare_weekly_shadow import finish_source
from scripts.validate_job_update import SUMMARY_COLUMNS
from scripts.weekly_job_update import RawCandidate, load_registry


class ParticipantPolicyTests(unittest.TestCase):
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
