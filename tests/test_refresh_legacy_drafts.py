import unittest
from tools.refresh_legacy_drafts import dm_ok, eligible
from unittest.mock import patch


class LegacyDraftRefreshTests(unittest.TestCase):
    def test_short_three_part_copy(self):
        dm = (
            "M1: Yo Josh, saw your Commonwealth silver lightweight title win.\n"
            "M2: We're giving fighters early access to Unlxck for training built around their goals and daily readiness.\n"
            "M3: Want the details?"
        )
        self.assertTrue(dm_ok(dm))

    def test_old_or_unqualified_copy(self):
        self.assertFalse(dm_ok("Yo Josh, saw your recent fight. Want me to send details?"))
        self.assertFalse(dm_ok("M1: Yo Josh, saw your fight.\nM2: We're offering access.\nM3: Want the details?"))

    @patch("tools.refresh_legacy_drafts.grandfathered_without_receipt", return_value=True)
    @patch("tools.refresh_legacy_drafts.receipt", return_value=None)
    def test_legacy_requires_unsent_and_no_receipt(self, proof, grandfather):
        page = {"archived": False, "in_trash": False, "properties": {
            "Stage": {"type": "select", "id": "stage-id", "select": {"name": "Ready to Send"}},
            "Draft DM": {"type": "rich_text", "rich_text": [{"type": "text", "text": {"content": "Yo Josh, saw your training. Want details?"}, "plain_text": "Yo Josh, saw your training. Want details?"}]},
            "AI Qualification Receipt": {"type": "rich_text", "rich_text": []}
        }}
        self.assertTrue(eligible(page, "stage-id"))
        page["properties"]["Stage"]["select"]["name"] = "Contacted"
        self.assertFalse(eligible(page, "stage-id"))
