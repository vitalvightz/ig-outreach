import unittest

from prepare_intake import planned_updates


class PrepareIntakeTests(unittest.TestCase):
    def test_new_blank_record_gets_found_and_boxing(self):
        page = {
            "properties": {
                "Stage": {"type": "select", "select": None},
                "Sport": {"type": "select", "select": None},
            }
        }
        self.assertEqual(
            planned_updates(page),
            {
                "Stage": {"select": {"name": "Found"}},
                "Sport": {"select": {"name": "Boxing"}},
            },
        )

    def test_found_record_with_blank_sport_gets_boxing_only(self):
        page = {
            "properties": {
                "Stage": {"type": "select", "select": {"name": "Found"}},
                "Sport": {"type": "select", "select": None},
            }
        }
        self.assertEqual(
            planned_updates(page),
            {"Sport": {"select": {"name": "Boxing"}}},
        )

    def test_existing_non_found_record_is_untouched(self):
        page = {
            "properties": {
                "Stage": {"type": "select", "select": {"name": "Contacted"}},
                "Sport": {"type": "select", "select": None},
            }
        }
        self.assertEqual(planned_updates(page), {})


if __name__ == "__main__":
    unittest.main()
