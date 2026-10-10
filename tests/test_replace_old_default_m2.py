import unittest
from unittest.mock import patch
from tools.replace_old_default_m2 import OLD, NEW, replacement, valid_target, proposal

def page(stage="Ready to Send", phrase=OLD):
    dm = "Yo Louis, saw you're 6-0 as a pro. We're giving fighters early access to Unlxck " + phrase + " Want the details?"
    return {"id":"p","created_time":"2020-01-01T00:00:00Z","archived":False,"in_trash":False,
            "properties":{"Stage":{"type":"select","id":"stage","select":{"name":stage}},
            "Draft DM":{"type":"rich_text","rich_text":[{"plain_text":dm}]},
            "AI Qualification Receipt":{"type":"rich_text","rich_text":[]}}}

class ReplaceM2Tests(unittest.TestCase):
    def test_exact_replacement(self):
        self.assertEqual(replacement("Before " + OLD + " After"), "Before " + NEW + " After")
    def test_only_ready_to_send(self):
        self.assertTrue(valid_target(page(), "stage"))
        self.assertFalse(valid_target(page(stage="Contacted"), "stage"))
    def test_no_match_skips(self):
        self.assertFalse(valid_target(page(phrase=NEW), "stage"))
    @patch("tools.replace_old_default_m2.grandfathered_without_receipt", return_value=True)
    def test_no_receipt_legacy_changes_draft_only(self, _):
        self.assertEqual(list(proposal(page(), "stage")), ["Draft DM"])
