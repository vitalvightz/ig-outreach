import unittest

from tools.refresh_unsent_drafts import new_draft_is_valid, qualified_at


class RefreshDraftFormatTests(unittest.TestCase):
    def test_accepts_short_three_part_dm(self):
        dm = (
            "M1: Yo Sam, saw you've got a bout on 24 October 2026.\n"
            "M2: We're giving fighters early access to Unlxck to plan conditioning around sparring and fight night.\n"
            "M3: Want the details?"
        )
        self.assertTrue(new_draft_is_valid(dm))

    def test_rejects_old_long_format(self):
        dm = (
            "M1: Yo Sam, saw you've got a fight coming up.\n"
            "M2: Unlxck helps make sure your sparring, conditioning, S&C and recovery "
            "aren't pulling in different directions, so the right things get priority "
            "as fight night gets closer.\n"
            "M3: Mind if I send you a bit more on it?"
        )
        self.assertFalse(new_draft_is_valid(dm))

    def test_rejects_more_than_one_m2_benefit(self):
        dm = (
            "M1: Yo Sam, saw you've got a bout on 24 October 2026.\n"
            "M2: We're giving fighters early access to Unlxck for readiness, recovery, "
            "training, timers, food and injury support across every camp session and fight week.\n"
            "M3: Want the details?"
        )
        self.assertFalse(new_draft_is_valid(dm))

    def test_qualification_time_accessor(self):
        page = {"properties": {"Qualified At": {"date": {"start": "2026-10-10T10:30:00Z"}}}}
        self.assertEqual(qualified_at(page), "2026-10-10T10:30:00Z")


if __name__ == "__main__":
    unittest.main()
