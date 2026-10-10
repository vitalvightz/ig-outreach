import unittest
from datetime import date
from core import _draft_mentions_verified_future_date, AI_INSTRUCTIONS

class NaturalFightDateTests(unittest.TestCase):
    def test_same_month_day_ordinal(self):
        self.assertTrue(_draft_mentions_verified_future_date("M1: Yo Sam, saw you're fighting on the 24th.", [date(2026,10,24)], date(2026,10,10)))
        self.assertFalse(_draft_mentions_verified_future_date("M1: Yo Sam, saw you're fighting on the 24th.", [date(2026,11,24)], date(2026,10,10)))

    def test_other_month_requires_month_name(self):
        self.assertTrue(_draft_mentions_verified_future_date("M1: Yo Sam, saw you're fighting on November 21st.", [date(2026,11,21)], date(2026,10,10)))
        self.assertFalse(_draft_mentions_verified_future_date("M1: Yo Sam, saw you're fighting on December 21st.", [date(2026,11,21)], date(2026,10,10)))

    def test_full_verified_date_still_accepted_for_existing_drafts(self):
        self.assertTrue(_draft_mentions_verified_future_date("M1: Yo Sam, fight on 24 October 2026.", [date(2026,10,24)], date(2026,10,10)))

    def test_prompt_instructs_natural_yearless_writing(self):
        self.assertIn("Do not mention the year in the DM", AI_INSTRUCTIONS)
        self.assertIn("on November 21st", AI_INSTRUCTIONS)
