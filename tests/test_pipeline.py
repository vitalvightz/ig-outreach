import unittest

from pipeline import NEEDS_RESEARCH, READY_TO_SEND, REJECTED, _is_empty_row, stage_from_ai


class PipelineStageTests(unittest.TestCase):
    def test_ready_to_send_when_qualified_with_evidence(self):
        self.assertEqual(
            stage_from_ai({"eligible": True, "evidence_sufficient": True}),
            READY_TO_SEND,
        )

    def test_needs_research_when_evidence_is_missing(self):
        self.assertEqual(
            stage_from_ai({"eligible": True, "evidence_sufficient": False}),
            NEEDS_RESEARCH,
        )

    def test_rejected_when_not_eligible(self):
        self.assertEqual(
            stage_from_ai({"eligible": False, "evidence_sufficient": True}),
            REJECTED,
        )

    def test_completely_empty_row_is_skipped(self):
        self.assertTrue(
            _is_empty_row(
                {
                    "candidate": "",
                    "instagram_handle": "",
                    "personalised_dm_angle": "",
                }
            )
        )

    def test_named_prospect_is_not_empty(self):
        self.assertFalse(
            _is_empty_row(
                {
                    "candidate": "Fighter",
                    "instagram_handle": "",
                    "personalised_dm_angle": "",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
