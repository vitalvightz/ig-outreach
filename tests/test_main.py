import unittest
from datetime import date

from core import deterministic_priority_score, fight_date_issue, preflight_reason, validate_ai_result


class OutreachLogicTests(unittest.TestCase):
    def test_rejects_expired_explicit_upcoming_fight(self):
        athlete = {"personalised_dm_angle": "JUDGEMENT DAY Saturday September 26 2026 National Stadium Dublin upcoming fight poster"}
        issue = fight_date_issue(athlete, today=date(2026, 10, 8))
        self.assertEqual(issue[0], "Rejected")
        self.assertIn("26 September 2026", issue[1])

    def test_rejects_stale_locked_in_draft(self):
        athlete = {"personalised_dm_angle": "LOCKED IN 26TH SEPT 2026 Bowliers Trafford Park"}
        self.assertEqual(fight_date_issue(athlete, draft="saw you've got Bowliers locked in", today=date(2026, 10, 8))[0], "Rejected")

    def test_unanchored_relative_fight_needs_research(self):
        athlete = {"personalised_dm_angle": "2 weeks out world championships"}
        self.assertEqual(fight_date_issue(athlete, today=date(2026, 10, 8))[0], "Needs Research")

    def test_unanchored_tomorrow_needs_research(self):
        athlete = {"personalised_dm_angle": "TOMORROW NIGHT fight weigh-in"}
        self.assertEqual(fight_date_issue(athlete, today=date(2026, 10, 8))[0], "Needs Research")

    def test_future_fight_draft_must_use_exact_date(self):
        athlete = {"personalised_dm_angle": "upcoming fight on 24 October 2026"}
        self.assertEqual(
            fight_date_issue(athlete, draft="M1: saw your fight coming up in two weeks.", approach="B", today=date(2026, 10, 8))[0],
            "Needs Research",
        )
        self.assertIsNone(
            fight_date_issue(athlete, draft="M1: saw your fight on 24 October 2026. M2: Fight night.", approach="B", today=date(2026, 10, 8))
        )

    def test_past_result_not_rejected_as_upcoming(self):
        athlete = {"personalised_dm_angle": "WINNER BRENDAN ATHERTON 12 September 2026"}
        self.assertIsNone(fight_date_issue(athlete, draft="Saw you won the Blockone Belter.", approach="A", today=date(2026, 10, 8)))

    def test_current_camp_without_future_bout_date_remains_allowed(self):
        athlete = {"personalised_dm_angle": "currently in camp at Team GB Sheffield October 2026"}
        self.assertIsNone(fight_date_issue(athlete, draft="M1: saw you're at Team GB camp.", approach="B", today=date(2026, 10, 8)))

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
