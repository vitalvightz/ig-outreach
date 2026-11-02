import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core import Settings, qualify_and_draft


class OpenAIResponseTests(unittest.TestCase):
    def test_incomplete_responses_are_reported_before_json_parsing(self):
        client = Mock()
        settings = Settings("key", "notion", "source", "gpt-6-luna", 100, True)
        for output in ("", '{"eligible":'):
            with self.subTest(output=output):
                client.responses.create.return_value = SimpleNamespace(
                    status="incomplete",
                    incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                    output_text=output,
                )
                with self.assertRaisesRegex(RuntimeError, "max_output_tokens"):
                    qualify_and_draft(client, settings, {"page_id": "test"})
                self.assertEqual(
                    client.responses.create.call_args.kwargs["max_output_tokens"], 4000
                )
