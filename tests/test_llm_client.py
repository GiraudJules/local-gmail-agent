from __future__ import annotations

import json
import unittest

import httpx

from local_gmail_agent.config import Settings
from local_gmail_agent.label_store import ManagedLabelConfig
from local_gmail_agent.llm_client import LMStudioClient, parse_json_response
from local_gmail_agent.schemas import EmailMessage


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

    def test_parse_final_json_after_reasoning_with_only_closing_tag(self) -> None:
        payload = parse_json_response(
            '{"label":"Newsletters","archive":true? Let me correct this.\n'
            '</think>{"label":"Newsletters","archive":true,"confidence":0.95,'
            '"reason":"Weekly subscription."}'
        )

        self.assertEqual(payload["label"], "Newsletters")
        self.assertTrue(payload["archive"])


class NativeClassificationTestCase(unittest.TestCase):
    def test_native_classification_controls_reasoning_and_reads_final_message(self) -> None:
        for reasoning in ("off", "on", "auto"):
            with self.subTest(reasoning=reasoning):
                settings = Settings(
                    _env_file=None,
                    llm_model="lfm3-1.7b",
                    lm_studio_api_mode="native",
                    lm_studio_reasoning=reasoning,
                )
                client = LMStudioClient(settings, ManagedLabelConfig())

                def handle(request: httpx.Request) -> httpx.Response:
                    payload = json.loads(request.content)
                    if reasoning == "auto":
                        self.assertNotIn("reasoning", payload)
                    else:
                        self.assertEqual(payload["reasoning"], reasoning)
                    self.assertFalse(payload["store"])
                    return httpx.Response(200, json={
                        "output": [
                            {"type": "reasoning", "content": "This is a newsletter."},
                            {"type": "message", "content": json.dumps({
                                "label": "Newsletters",
                                "archive": True,
                                "confidence": 0.95,
                                "reason": "Weekly subscription.",
                            })},
                        ],
                    })

                client.http_client.close()
                client.http_client = httpx.Client(
                    base_url="http://localhost:1234/api/v1",
                    transport=httpx.MockTransport(handle),
                )
                try:
                    decision = client.classify_email(EmailMessage(
                        message_id="test", thread_id="test", sender="news@example.com",
                        subject="Weekly newsletter", date="2026-11-18",
                        snippet="Your weekly subscription.",
                    ))
                    self.assertEqual(decision.label, "Newsletters")
                    self.assertTrue(decision.archive)
                finally:
                    client.http_client.close()
                    client.openai_client.close()


if __name__ == "__main__":
    unittest.main()
