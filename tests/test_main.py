import unittest
from datetime import date

from core import (AI_INSTRUCTIONS, deterministic_priority_score, fight_date_issue,
                  has_independent_non_event_hook, preflight_reason, validate_ai_result)


class OutreachLogicTests(unittest.TestCase):
    def test_rejects_expired_explicit_upcoming_fight(self):
        athlete = {"personalised_dm_angle": "JUDGEMENT DAY Saturday September 26 2026 National Stadium Dublin upcoming fight poster"}
        issue = fight_date_issue(athlete, today=date(2026, 10, 8))
        self.assertEqual(issue[0], "Rejected")
        self.assertIn("26 September 2026", issue[1])

    def test_rejects_stale_locked_in_draft(self):
        athlete = {"personalised_dm_angle": "LOCKED IN 26TH SEPT 2026 Bowliers Trafford Park"}
        self.assertEqual(fight_date_issue(athlete, draft="saw you've got Bowliers locked in", today=date(2026, 10, 8))[0], "Rejected")

    def test_expired_month_year_fight_is_rejected(self):
        athlete = {"personalised_dm_angle": "upcoming fight September 2026"}
        self.assertEqual(fight_date_issue(athlete, today=date(2026, 10, 8))[0], "Rejected")

    def test_numeric_short_year_fight_is_rejected(self):
        athlete = {"personalised_dm_angle": "LOCKED IN 26/09/26 fight card"}
        self.assertEqual(fight_date_issue(athlete, today=date(2026, 10, 8))[0], "Rejected")

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

    def test_fight_camp_with_yearless_event_date_needs_research(self):
        athlete = {"personalised_dm_angle": "currently in camp for 7th November Doncaster Dome"}
        self.assertEqual(fight_date_issue(athlete, draft="M1: saw you're in camp", approach="B", today=date(2026, 10, 8))[0], "Needs Research")

    def test_past_result_not_rejected_as_upcoming(self):
        athlete = {"personalised_dm_angle": "WINNER BRENDAN ATHERTON 12 September 2026"}
        self.assertIsNone(fight_date_issue(athlete, draft="Saw you won the Blockone Belter.", approach="A", today=date(2026, 10, 8)))

    def test_current_camp_without_future_bout_date_remains_allowed(self):
        athlete = {"personalised_dm_angle": "currently in camp at Team GB Sheffield October 2026"}
        self.assertIsNone(fight_date_issue(athlete, draft="M1: saw you're at Team GB camp.", approach="B", today=date(2026, 10, 8)))

    def test_post_date_not_confused_with_callum_future_fight(self):
        athlete = {"personalised_dm_angle":
                   "upcoming event posted at 17 august 2026, Blackpool's Callum Espin-Fahy joins "
                   "Fight Club on Saturday 10 October 2026"}
        self.assertIsNone(fight_date_issue(athlete, today=date(2026, 10, 9)))
        self.assertIsNone(fight_date_issue(
            athlete, draft="M1: saw your fight on 10 October 2026. M2: sparring.", approach="B",
            today=date(2026, 10, 9)))

    def test_unverified_elias_event_date_is_not_false_expired_fight(self):
        athlete = {"personalised_dm_angle":
                   "the upcoming event is posted at 1 October 2026, is BANTAMWEIGHT BOUT "
                   "on 24 October 2026"}
        issue = fight_date_issue(athlete, today=date(2026, 10, 9))
        self.assertEqual(issue[0], "Needs Research")
        self.assertIn("participation", issue[1].lower())
        self.assertNotIn("supply the verified full", issue[1])

    def test_harrison_future_event_missing_participation_not_date(self):
        athlete = {"personalised_dm_angle":
                   "upcoming event posted at 3 September 2026, is doncasters top tier "
                   "on saturday 7 November 2026"}
        issue = fight_date_issue(athlete, today=date(2026, 10, 9))
        self.assertEqual(issue[0], "Needs Research")
        self.assertIn("competing", issue[1])
        self.assertNotIn("full future fight date", issue[1])

    def test_maxime_and_oussama_dated_event_without_boxer_link(self):
        for note in (
            "upcoming event posted at 8 October 2026 is, IGNITE the electric ballroom,camden on 15 November 2026",
            "upcoming event posted at 25 September 2026 is, deutsche meisterschaft im lightweight on 14 November 2026",
        ):
            with self.subTest(note=note):
                issue = fight_date_issue({"personalised_dm_angle": note}, today=date(2026, 10, 9))
                self.assertEqual(issue[0], "Needs Research")
                self.assertIn("participation", issue[1])

    def test_explicit_athlete_confirmed_for_named_event_allows_fight_date(self):
        athlete = {"personalised_dm_angle":
                   "upcoming event posted 3 September 2026: Harrison Barker confirmed for "
                   "Doncaster Top Tier on Saturday 7 November 2026"}
        self.assertIsNone(fight_date_issue(
            athlete, draft="M1: saw you're fighting on 7 November 2026.", approach="B",
            today=date(2026, 10, 9)))

    def test_past_publication_does_not_reject_even_when_only_date(self):
        athlete = {"personalised_dm_angle":
                   "upcoming boxing event announced on 20 September 2026"}
        issue = fight_date_issue(athlete, today=date(2026, 10, 9))
        self.assertEqual(issue[0], "Needs Research")

    def test_expired_fight_still_rejected_when_publication_date_is_future(self):
        athlete = {"personalised_dm_angle":
                   "upcoming fight post published on 8 October 2026 says bout on 26 September 2026"}
        issue = fight_date_issue(athlete, today=date(2026, 10, 9))
        self.assertEqual(issue[0], "Rejected")
        self.assertIn("26 September 2026", issue[1])

    def test_full_yearless_event_still_requires_confirmation(self):
        athlete = {"personalised_dm_angle":
                   "upcoming event posted 1 October 2026: Fighter confirmed for Doncaster 7 November"}
        issue = fight_date_issue(athlete, draft="M1: fight coming up", approach="B", today=date(2026, 10, 9))
        self.assertEqual(issue[0], "Needs Research")

    def test_past_fight_can_be_private_beta_personalisation(self):
        athlete = {"personalised_dm_angle":
                   "fought on 26 September 2026, made his UK debut at Home Stretch"}
        self.assertIsNone(fight_date_issue(
            athlete, draft="Yo Mikael, saw you made your UK debut at Home Stretch.",
            approach="A", today=date(2026, 10, 9)))

    def test_every_sop_hook_can_be_independently_assessed(self):
        # No upcoming fight is required for Approach A.
        hooks = {
            "recent_result": "Won the U60 NAC title on 3 October 2026 at Sheffield Arena",
            "gym": "Currently training at Bristol Boxing Academy, shown in gym post on 4 October 2026",
            "coach": "Coached by @coachthomas at East London Boxing Club",
            "training_post": "Shared padwork footage from Saturday 3 October 2026",
            "layoff_return": "Returned to boxing after a year off, announced 2 October 2026",
            "weight_class_move": "Moved to 63kg as announced on 1 October 2026",
        }
        for label, evidence in hooks.items():
            with self.subTest(category=label):
                self.assertTrue(has_independent_non_event_hook(evidence))
                self.assertIsNone(fight_date_issue(
                    {"personalised_dm_angle": evidence},
                    draft="M1: Hey boxer, saw your recent activity. M2: We're giving early access.",
                    approach="A", today=date(2026, 10, 10)))
        self.assertIsNone(fight_date_issue(
            {"personalised_dm_angle": "Currently in camp at Team GB on 6 October 2026"},
            draft="M1: Hey boxer, saw you're currently in camp.",
            approach="B", today=date(2026, 10, 10)))
        self.assertIsNone(fight_date_issue(
            {"personalised_dm_angle": "Confirmed fighting on 24 October 2026 vs James Smith"},
            draft="M1: Hey boxer, saw you've got a fight on the 24th.",
            approach="B", today=date(2026, 10, 10)))

    def test_model_guidance_explicitly_covers_all_eight_sop_hook_types(self):
        for kind in ("RECENT RESULT", "CURRENT CAMP", "UPCOMING FIGHT",
                     "CURRENT GYM", "COACH/TEAM", "RECENT TRAINING POST",
                     "RETURN FROM LAYOFF", "WEIGHT-CLASS MOVE"):
            with self.subTest(category=kind):
                self.assertIn(kind, AI_INSTRUCTIONS)

    def test_old_future_fight_with_current_gym_is_private_beta_not_rejection(self):
        athlete = {"personalised_dm_angle":
                   "Next up 7 March 2026 at Bolton, now training at Manchester Boxing Club "
                   "as confirmed in a 3 October 2026 gym post."}
        self.assertIsNone(fight_date_issue(athlete, approach="A",
                                          draft="M1: Hey boxer, saw you're training at Manchester Boxing Club.",
                                          today=date(2026, 10, 10)))
        self.assertEqual(fight_date_issue(
            athlete, approach="B",
            draft="M1: Hey boxer, saw you've got a fight coming up.",
            today=date(2026, 10, 10))[0], "Rejected")

    def test_unverified_upcoming_event_can_use_separate_recent_training(self):
        athlete = {"personalised_dm_angle":
                   "Upcoming event on 21 November 2026 in Bolton, boxer not yet confirmed. "
                   "Shared sparring footage 5 October 2026."}
        self.assertIsNone(fight_date_issue(
            athlete, draft="M1: Hey boxer, saw your recent sparring footage.",
            approach="A", today=date(2026, 10, 10)))
        issue = fight_date_issue(
            athlete, draft="M1: Hey boxer, saw your fight on November 21st.",
            approach="B", today=date(2026, 10, 10))
        self.assertEqual(issue[0], "Needs Research")
        self.assertIn("participation", issue[1])

    def test_relative_fight_time_remains_blocked_even_with_valid_other_hook(self):
        athlete = {"personalised_dm_angle":
                   "Shared padwork footage on 2 October 2026, upcoming event in November"}
        self.assertEqual(fight_date_issue(
            athlete, draft="M1: saw your fight in two weeks.",
            approach="A", today=date(2026, 10, 10))[0], "Needs Research")

    def test_cancelled_card_not_treated_as_confirmed_future_fight(self):
        athlete = {"personalised_dm_angle":
                   "Upcoming Commonwealth title bout on 24 October 2026, poster says cancelled."}
        issue = fight_date_issue(athlete, today=date(2026, 10, 10))
        self.assertEqual(issue[0], "Needs Research")
        self.assertIn("cancelled", issue[1])
        athlete["personalised_dm_angle"] += " Shared padwork footage 3 October 2026."
        self.assertIsNone(fight_date_issue(
            athlete, approach="A", draft="M1: Hey boxer, saw your recent padwork.",
            today=date(2026, 10, 10)))

    def test_coach_only_no_upcoming_is_not_flagged_for_missing_fight_date(self):
        # Live Notion research: explicitly says no fight announced and focuses
        # on coaching; the AI should decide boxer eligibility, not ask for dates.
        athlete = {"personalised_dm_angle":
                   "Recent match / activity: No pro fight poster found. HEAD Boxing Coach "
                   "at Fighting Fit Manchester, coaching fighters. "
                   "Upcoming one event: No upcoming fight confirmed, coaching-focused."}
        self.assertIsNone(fight_date_issue(athlete, today=date(2026, 10, 10)))
        self.assertIn("coach-only", AI_INSTRUCTIONS)

    def test_recent_result_can_be_assessed_without_upcoming_camp_date(self):
        athlete = {"personalised_dm_angle":
                   "Recent match: boxed Jacob Marrer at the BOXXER Future Now card "
                   "in Leeds on 20 December 2025. Upcoming camp: no verified date yet."}
        self.assertIsNone(fight_date_issue(
            athlete, approach="A", draft="M1: Hey Max, saw you boxed Jacob Marrer in Leeds.",
            today=date(2026, 10, 10)))

    def test_unknown_gym_or_generic_compliment_not_marked_verified(self):
        for vague in ("training hard", "looks serious", "great profile", "generic boxing gym"):
            with self.subTest(vague=vague):
                self.assertFalse(has_independent_non_event_hook(vague))

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
