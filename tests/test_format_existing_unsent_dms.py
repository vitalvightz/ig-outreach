import unittest
from unittest.mock import patch
from tools.format_existing_unsent_dms import valid_target, proposal
from core import copy_ready_dm

DRAFT = ("M1: Yo Luke, saw you're fighting on November 7th.\n"
         "M2: We're giving fighters early access to Unlxck to plan conditioning around sparring and fight night.\n"
         "M3: Want the details?")

def page(stage="Ready to Send", draft=DRAFT):
    return {"id": "p", "created_time": "2020-01-01T00:00:00Z",
            "archived": False, "in_trash": False,
            "properties": {
                "Stage": {"type": "select", "id": "stage", "select": {"name": stage}},
                "Draft DM": {"type": "rich_text", "rich_text": [{"plain_text": draft}]},
                "AI Qualification Receipt": {"type": "rich_text", "rich_text": []}
            }}

class FormatDMTests(unittest.TestCase):
    def test_format_unchanged_words(self):
        out = copy_ready_dm(DRAFT)
        self.assertEqual(out, "Yo Luke, saw you're fighting on November 7th. We're giving fighters early access to Unlxck to plan conditioning around sparring and fight night. Want the details?")

    def test_never_touch_contacted(self):
        self.assertFalse(valid_target(page(stage="Contacted"), "stage"))

    def test_already_formatted_not_selected(self):
        self.assertFalse(valid_target(page(draft=copy_ready_dm(DRAFT)), "stage"))

    @patch("tools.format_existing_unsent_dms.grandfathered_without_receipt", return_value=True)
    def test_receipt_free_legacy_only_changes_draft(self, grandfathered):
        result = proposal(page(), "stage")
        self.assertEqual(list(result), ["Draft DM"])
        self.assertEqual(result["Draft DM"]["rich_text"][0]["text"]["content"], copy_ready_dm(DRAFT))
