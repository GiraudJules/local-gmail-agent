from __future__ import annotations

import unittest

from local_gmail_agent.label_store import ManagedLabelConfig
from local_gmail_agent.rules import apply_safety_rules, labels_to_apply
from local_gmail_agent.schemas import LLMRawDecision


class RulesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.label_config = ManagedLabelConfig()

    def test_low_confidence_falls_back_to_review(self) -> None:
        raw = LLMRawDecision(
            label="Work/Clients",
            archive=True,
            confidence=0.42,
            reason="Unsure classification.",
        )

        decision = apply_safety_rules(raw, label_config=self.label_config)

        self.assertEqual(decision.label, self.label_config.fallback_label)
        self.assertTrue(decision.review_required)
        self.assertFalse(decision.archive)

    def test_invalid_label_falls_back_to_review(self) -> None:
        raw = LLMRawDecision(
            label="Spam/Unknown",
            archive=True,
            confidence=0.98,
            reason="Model guessed an unsupported category.",
        )

        decision = apply_safety_rules(raw, label_config=self.label_config)

        self.assertEqual(decision.label, self.label_config.fallback_label)
        self.assertFalse(decision.archive)
        self.assertIn("invalid label", decision.fallback_reason or "")

    def test_action_labels_are_never_archived(self) -> None:
        raw = LLMRawDecision(
            label="Action/To Reply",
            archive=True,
            confidence=0.99,
            reason="Needs a direct reply.",
        )

        decision = apply_safety_rules(raw, label_config=self.label_config)

        self.assertEqual(decision.label, "Action/To Reply")
        self.assertFalse(decision.archive)

    def test_labels_to_apply_includes_reviewed(self) -> None:
        raw = LLMRawDecision(
            label="Newsletters",
            archive=True,
            confidence=0.97,
            reason="Subscription content.",
        )

        decision = apply_safety_rules(raw, label_config=self.label_config)
        labels = labels_to_apply(decision, reviewed_label=self.label_config.reviewed_label)

        self.assertEqual(labels[0], "Newsletters")
        self.assertIn(self.label_config.reviewed_label, labels)


if __name__ == "__main__":
    unittest.main()
