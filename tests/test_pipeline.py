import unittest

from core import instagram_handle_from_profile_url, verified_profile_reason
from pipeline import (
    NEEDS_RESEARCH,
    READY_TO_SEND,
    REJECTED,
    _entry_complete,
    _is_empty_row,
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
