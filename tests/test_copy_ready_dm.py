import unittest
from core import copy_ready_dm
from tools.refresh_legacy_drafts import PROMPT


class CopyReadyDMTests(unittest.TestCase):
    def test_combines_sections_without_labels(self):
        draft = ("M1: Yo Louis, saw you're 6-0 as a pro.\n"
                 "M2: We're giving fighters early access to Unlxck for training built around their goals and daily readiness.\n"
                 "M3: Want the details?")
        self.assertEqual(copy_ready_dm(draft), "Yo Louis, saw you're 6-0 as a pro. We're giving fighters early access to Unlxck for training built around their goals and daily readiness. Want the details?")

    def test_existing_one_message_is_unchanged(self):
        old = "Yo Luke, saw you're fighting on November 7th. Want the details?"
        self.assertEqual(copy_ready_dm(old), old)

    def test_invalid_three_line_output_untouched(self):
        draft = "M1: Hello\nM2: Details\nM3: Something else"
        self.assertEqual(copy_ready_dm(draft), draft)

    def test_legacy_prompt_binds_stored_approach(self):
        self.assertIn("The provided Outreach Approach is fixed", PROMPT)
