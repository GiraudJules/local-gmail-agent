from __future__ import annotations

import unittest

from pydantic import ValidationError

from local_gmail_agent.label_store import (
    DEFAULT_MANAGED_GMAIL_LABEL_ROOT,
    ManagedLabelConfig,
    managed_gmail_label_name,
)
from local_gmail_agent.schemas import (
    ClassificationPromptPayload,
    EmailMessage,
    LLMRawDecision,
    classification_json_schema,
)


class SchemasTestCase(unittest.TestCase):
    def test_raw_decision_confidence_is_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            LLMRawDecision(
                label="Newsletters",
                archive=False,
                confidence=1.2,
                reason="Invalid confidence.",
            )

    def test_classification_schema_has_expected_fields(self) -> None:
        label_config = ManagedLabelConfig()
        schema = classification_json_schema(label_config.classification_labels)

        self.assertEqual(schema["type"], "object")
        self.assertEqual(
            sorted(schema["required"]),
            ["archive", "confidence", "label", "reason"],
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("Action/To Reply", schema["properties"]["label"]["enum"])

    def test_prompt_payload_is_pydantic_backed(self) -> None:
        email = EmailMessage(
            message_id="m1",
            thread_id="t1",
            sender="sender@example.com",
            subject="Subject",
            date="2026-05-19T00:00:00Z",
            snippet="Snippet",
            plain_text_body="Body",
        )
        label_config = ManagedLabelConfig()

        payload = ClassificationPromptPayload.from_email(
            email,
            allowed_labels=label_config.classification_labels,
        )

        self.assertEqual(payload.email.message_id, "m1")
        self.assertEqual(payload.output_fields[0].name, "label")
        self.assertIn("Action/To Reply", payload.allowed_labels)

    def test_managed_gmail_label_name_uses_top_level_root(self) -> None:
        self.assertEqual(
            managed_gmail_label_name("Action/To Reply"),
            f"{DEFAULT_MANAGED_GMAIL_LABEL_ROOT}/Action/To Reply",
        )


if __name__ == "__main__":
    unittest.main()
