from __future__ import annotations

import unittest

import json
import httpx

from local_gmail_agent.config import Settings
from local_gmail_agent.label_store import ManagedLabelConfig
from local_gmail_agent.llm_client import OllamaClient, build_llm_client, parse_json_response
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


class LLMProviderClientTestCase(unittest.TestCase):
    def test_factory_builds_ollama_client(self) -> None:
        settings = Settings(llm_provider="ollama", llm_model="qwen3:8b")

        client = build_llm_client(settings, ManagedLabelConfig())

        self.assertIsInstance(client, OllamaClient)

    def test_ollama_native_classification_uses_chat_schema(self) -> None:
        settings = Settings(llm_provider="ollama", llm_model="qwen3:8b")
        label_config = ManagedLabelConfig()
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertEqual(request.url.path, "/api/chat")
            payload = json.loads(request.read().decode("utf-8"))
            self.assertEqual(payload["model"], "qwen3:8b")
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["format"]["type"], "object")
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"label":"Newsletters","archive":true,'
                            '"confidence":0.92,"reason":"subscription update"}'
                        ),
                    }
                },
            )

        client = OllamaClient(settings, label_config)
        client.http_client = httpx.Client(
            base_url=settings.ollama_base_url,
            transport=httpx.MockTransport(handler),
        )

        decision = client.classify_email(
            EmailMessage(
                message_id="m1",
                thread_id="t1",
                sender="news@example.com",
                subject="Weekly update",
                date="2026-06-27",
                snippet="Newsletter",
                plain_text_body="A weekly product update.",
                label_ids=[],
            )
        )

        self.assertEqual(decision.label, "Newsletters")
        self.assertTrue(decision.archive)
        self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
