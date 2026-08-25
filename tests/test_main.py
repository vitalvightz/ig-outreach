import unittest

from main import preflight_reason, stage_from_result, validate_ai_result


class OutreachLogicTests(unittest.TestCase):
    def test_ready_to_dm_when_qualified_with_evidence(self):
        self.assertEqual(
            stage_from_result({"eligible": True, "evidence_sufficient": True}),
            "Ready to DM",
        )

    def test_researching_when_evidence_is_missing(self):
        self.assertEqual(
            stage_from_result({"eligible": True, "evidence_sufficient": False}),
            "Researching",
        )

    def test_rejected_when_not_eligible(self):
        self.assertEqual(
            stage_from_result({"eligible": False, "evidence_sufficient": True}),
            "Rejected",
        )

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


if __name__ == "__main__":
    unittest.main()
