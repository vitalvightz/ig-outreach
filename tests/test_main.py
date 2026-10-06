import unittest

from core import deterministic_priority_score, preflight_reason, validate_ai_result


class OutreachLogicTests(unittest.TestCase):
    def test_preflight_requires_public_personalisation(self):
        candidate = {
            "instagram_handle": "@fighter",
            "profile_url": "",
            "personalised_dm_angle": "",
            "sport": "Boxing",
        }
        self.assertIn("personalisation", preflight_reason(candidate))

    def test_rejects_draft_when_evidence_or_eligibility_fails(self):
        with self.assertRaises(ValueError):
            validate_ai_result(
                {
                    "priority_score": 50,
                    "eligible": False,
                    "evidence_sufficient": True,
                    "outreach_approach": "",
                    "draft_dm": "This should not exist.",
                }
            )

    def test_accepts_valid_qualified_result(self):
        validate_ai_result(
            {
                "priority_score": 85,
                "eligible": True,
                "evidence_sufficient": True,
                "outreach_approach": "B",
                "draft_dm": "M1: verified detail",
            }
        )

    def test_priority_score_ignores_prestige_for_cold_private_beta(self):
        candidate = {"source": "Instagram"}
        result = {
            "eligible": True,
            "evidence_sufficient": True,
            "outreach_approach": "A",
            "priority_signals": {
                "recent_activity": False,
                "timely_reason": False,
                "strong_personalisation": True,
            },
        }
        self.assertEqual(deterministic_priority_score(candidate, result), 45)

    def test_priority_score_rewards_timing_and_warm_source_only(self):
        candidate = {"source": "Athlete referral"}
        result = {
            "eligible": True,
            "evidence_sufficient": True,
            "outreach_approach": "B",
            "priority_signals": {
                "recent_activity": True,
                "timely_reason": True,
                "strong_personalisation": True,
            },
        }
        self.assertEqual(deterministic_priority_score(candidate, result), 97)

    def test_priority_score_keeps_needs_research_low(self):
        candidate = {"source": "Existing follower"}
        result = {
            "eligible": True,
            "evidence_sufficient": False,
            "outreach_approach": "",
            "priority_signals": {
                "recent_activity": False,
                "timely_reason": False,
                "strong_personalisation": False,
            },
        }
        self.assertEqual(deterministic_priority_score(candidate, result), 25)

    def test_priority_score_rewards_recent_cold_activity_without_prestige(self):
        candidate = {"source": "Instagram"}
        result = {
            "eligible": True,
            "evidence_sufficient": True,
            "outreach_approach": "A",
            "priority_signals": {
                "recent_activity": True,
                "timely_reason": True,
                "strong_personalisation": True,
            },
        }
        self.assertEqual(deterministic_priority_score(candidate, result), 65)


if __name__ == "__main__":
    unittest.main()
