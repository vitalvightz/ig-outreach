import unittest
from datetime import datetime, timezone

from core import instagram_handle_from_profile_url, verified_profile_reason
from pipeline import (
    NEEDS_RESEARCH,
    READY_TO_SEND,
    REJECTED,
    _candidate_counts_toward_daily_target,
    _entry_complete,
    _is_empty_row,
    _ready_row_needs_repair,
    _today_utc_bounds,
    stage_from_ai,
)


class PipelineStageTests(unittest.TestCase):
    def test_ready_to_send_when_qualified_with_evidence(self):
        self.assertEqual(
            stage_from_ai({"eligible": True, "evidence_sufficient": True}),
            READY_TO_SEND,
        )

    def test_needs_research_when_evidence_is_missing(self):
        self.assertEqual(
            stage_from_ai({"eligible": True, "evidence_sufficient": False}),
            NEEDS_RESEARCH,
        )

    def test_rejected_when_not_eligible(self):
        self.assertEqual(
            stage_from_ai({"eligible": False, "evidence_sufficient": True}),
            REJECTED,
        )

    def test_completely_empty_row_is_skipped(self):
        self.assertTrue(
            _is_empty_row(
                {
                    "candidate": "",
                    "instagram_handle": "",
                    "personalised_dm_angle": "",
                }
            )
        )

    def test_named_prospect_is_not_empty(self):
        self.assertFalse(
            _is_empty_row(
                {
                    "candidate": "Fighter",
                    "instagram_handle": "",
                    "personalised_dm_angle": "",
                }
            )
        )

    def test_entry_runs_profile_gate_when_candidate_and_evidence_exist(self):
        self.assertTrue(
            _entry_complete(
                {
                    "candidate": "Yash Patel",
                    "verified_profile_url": "",
                    "instagram_handle": "",
                    "personalised_dm_angle": "Won his second European title.",
                }
            )
        )

    def test_partial_entry_does_not_run_ai(self):
        self.assertFalse(
            _entry_complete(
                {
                    "candidate": "Yash Patel",
                    "verified_profile_url": "https://www.instagram.com/yashboxing/",
                    "instagram_handle": "",
                    "personalised_dm_angle": "",
                }
            )
        )

    def test_broken_ready_row_is_reprocessed(self):
        page = {
            "properties": {
                "Priority Score": {"number": 0},
                "AI Qualification Reason": {"rich_text": []},
                "Draft DM": {"rich_text": []},
                "Instagram Handle": {"rich_text": []},
                "Outreach Approach": {"select": None},
            }
        }
        self.assertTrue(_ready_row_needs_repair(page))

    def test_stale_ready_fight_is_reprocessed(self):
        page = {
            "id": "test-id",
            "properties": {
                "Candidate": {"type": "title", "title": [{"plain_text": "Dean"}]},
                "Personalised DM Angle": {"type": "rich_text", "rich_text": [{"plain_text": "upcoming fight 26 September 2026"}]},
                "Priority Score": {"number": 80},
                "AI Qualification Reason": {"rich_text": [{"plain_text": "Upcoming bout"}]},
                "Draft DM": {"type": "rich_text", "rich_text": [{"plain_text": "M1: you've got a fight coming up"}]},
                "Instagram Handle": {"rich_text": [{"plain_text": "dean"}]},
                "Outreach Approach": {"type": "select", "select": {"name": "B"}},
            },
        }
        self.assertTrue(_ready_row_needs_repair(page))

    def test_complete_ready_row_is_not_reprocessed(self):
        page = {
            "properties": {
                "Priority Score": {"number": 70},
                "AI Qualification Reason": {"rich_text": [{"plain_text": "Qualified"}]},
                "Draft DM": {"rich_text": [{"plain_text": "Yo..."}]},
                "Instagram Handle": {"rich_text": [{"plain_text": "fighter"}]},
                "Outreach Approach": {"select": {"name": "A"}},
            }
        }
        self.assertFalse(_ready_row_needs_repair(page))


    def test_daily_target_requires_all_three_human_fields(self):
        self.assertTrue(
            _candidate_counts_toward_daily_target(
                {
                    "candidate": "Fighter",
                    "verified_profile_url": "https://www.instagram.com/fighter/",
                    "personalised_dm_angle": "Recent public boxing detail.",
                }
            )
        )
        self.assertFalse(
            _candidate_counts_toward_daily_target(
                {
                    "candidate": "Fighter",
                    "verified_profile_url": "",
                    "personalised_dm_angle": "Recent public boxing detail.",
                }
            )
        )

    def test_daily_counter_uses_london_calendar_day(self):
        start, end = _today_utc_bounds(
            datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(start.isoformat(), "2026-10-07T23:00:00+00:00")
        self.assertEqual(end.isoformat(), "2026-10-08T23:00:00+00:00")





class InstagramVerificationTests(unittest.TestCase):
    def test_extracts_handle_from_copied_profile_url(self):
        self.assertEqual(
            instagram_handle_from_profile_url(
                "https://www.instagram.com/poonia_boxer_/?igsh=abc123"
            ),
            "poonia_boxer_",
        )

    def test_rejects_typed_handle_without_profile_url(self):
        self.assertIsNone(instagram_handle_from_profile_url("poonia_boxer_"))

    def test_rejects_instagram_post_url(self):
        self.assertIsNone(
            instagram_handle_from_profile_url(
                "https://www.instagram.com/p/ABC123/"
            )
        )

    def test_rejects_non_instagram_url(self):
        self.assertIsNone(
            instagram_handle_from_profile_url("https://example.com/poonia_boxer_/")
        )

    def test_missing_verified_url_requires_research(self):
        handle, reason = verified_profile_reason(
            {"verified_profile_url": "", "instagram_handle": "made_up_handle"}
        )
        self.assertIsNone(handle)
        self.assertIn("Verified Profile URL", reason)

    def test_verified_url_becomes_authoritative_handle(self):
        handle, reason = verified_profile_reason(
            {
                "verified_profile_url": "https://instagram.com/poonia_boxer_/",
                "instagram_handle": "deepak_poonia_boxer",
            }
        )
        self.assertEqual(handle, "poonia_boxer_")
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
