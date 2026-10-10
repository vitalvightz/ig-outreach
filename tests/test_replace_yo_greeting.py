import unittest
from unittest.mock import patch
from tools.replace_yo_greeting import replacement, valid_target, proposal

def page(stage="Ready to Send", draft="Yo Louis, saw you're 6-0. Want the details?"):
    return {"id":"p","created_time":"2020-01-01T00:00:00Z","archived":False,"in_trash":False,
            "properties":{"Stage":{"type":"select","id":"stage","select":{"name":stage}},
            "Draft DM":{"type":"rich_text","rich_text":[{"plain_text":draft}]},
            "AI Qualification Receipt":{"type":"rich_text","rich_text":[]}}}

class GreetingTests(unittest.TestCase):
    def test_single_message(self):
        self.assertEqual(replacement("Yo Louis, nice work."),"Hey Louis, nice work.")
    def test_labelled_message(self):
        self.assertEqual(replacement("M1: Yo Louis, nice work.\nM2: Pitch\nM3: Want the details?"),
                         "M1: Hey Louis, nice work.\nM2: Pitch\nM3: Want the details?")
    def test_no_interior_replacement(self):
        self.assertEqual(replacement("Hello Yo Louis"),"Hello Yo Louis")
    def test_stage_protection(self):
        self.assertTrue(valid_target(page(),"stage"))
        self.assertFalse(valid_target(page(stage="Contacted"),"stage"))
    @patch("tools.replace_yo_greeting.grandfathered_without_receipt", return_value=True)
    def test_legacy_only_dm(self, _):
        self.assertEqual(list(proposal(page(),"stage")),["Draft DM"])
