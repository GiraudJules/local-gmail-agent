from __future__ import annotations

import unittest

from local_gmail_agent.llm_client import parse_json_response


class LLMClientParsingTestCase(unittest.TestCase):
    def test_parse_plain_json(self) -> None:
        payload = parse_json_response(
            '{"label":"Newsletters","archive":true,"confidence":0.93,"reason":"subscription"}'
        )

        self.assertEqual(payload["label"], "Newsletters")
        self.assertTrue(payload["archive"])

    def test_parse_fenced_json(self) -> None:
        payload = parse_json_response(
            '```json\n{"label":"Personal","archive":false,"confidence":0.91,"reason":"personal"}\n```'
        )

        self.assertEqual(payload["label"], "Personal")
        self.assertFalse(payload["archive"])

    def test_parse_json_after_thinking_block(self) -> None:
        payload = parse_json_response(
            "<think>I should classify this as GitHub notifications.</think>\n"
            '{"label":"Notifications/GitHub","archive":true,"confidence":0.95,"reason":"github email"}'
        )

        self.assertEqual(payload["label"], "Notifications/GitHub")


if __name__ == "__main__":
    unittest.main()
