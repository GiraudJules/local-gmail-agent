from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from local_gmail_agent.analysis import (
    build_suggestions,
    classify_sender,
    latest_entries_by_message,
)
from local_gmail_agent.cli import app
from local_gmail_agent.schemas import DecisionLogEntry, DecisionOutcome, EmailLogContext, LLMRawDecision


def make_entry(
    *,
    message_id: str,
    sender: str,
    label: str,
    review_required: bool = False,
    error: str | None = None,
    timestamp: datetime | None = None,
) -> DecisionLogEntry:
    decision = DecisionOutcome(
        label=label,
        archive=False,
        confidence=0.95,
        reason="test",
        review_required=review_required,
    )
    return DecisionLogEntry(
        timestamp=timestamp or datetime.now(UTC),
        email=EmailLogContext(
            message_id=message_id,
            thread_id=f"thread-{message_id}",
            sender=sender,
            subject=f"Subject {message_id}",
            date="2026-05-22",
            snippet="Snippet",
        ),
        raw_decision=LLMRawDecision(
            label=label,
            archive=False,
            confidence=0.95,
            reason="test",
        ),
        final_decision=decision,
        labels_to_apply=[label],
        dry_run=True,
        applied=False,
        error=error,
    )


class AnalysisHelpersTestCase(unittest.TestCase):
    def test_classify_sender_extracts_email_address_and_domain(self) -> None:
        identity = classify_sender('GitHub <notifications@github.com>')

        self.assertEqual(identity.email_address, "notifications@github.com")
        self.assertEqual(identity.domain, "github.com")

    def test_latest_entries_by_message_keeps_newest_entry(self) -> None:
        older = make_entry(
            message_id="m1",
            sender="one@example.com",
            label="Newsletters",
            timestamp=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        )
        newer = make_entry(
            message_id="m1",
            sender="one@example.com",
            label="Notifications/Tools",
            timestamp=datetime(2026, 5, 21, 10, 0, tzinfo=UTC),
        )

        latest = latest_entries_by_message([newer, older])

        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0].final_decision.label, "Notifications/Tools")

    def test_build_suggestions_returns_sender_and_domain_candidates(self) -> None:
        entries = [
            make_entry(
                message_id="m1",
                sender="GitHub <notifications@github.com>",
                label="Notifications/Tools",
            ),
            make_entry(
                message_id="m2",
                sender="GitHub <notifications@github.com>",
                label="Notifications/Tools",
            ),
            make_entry(
                message_id="m3",
                sender="GitHub <notifications@github.com>",
                label="Notifications/Tools",
            ),
            make_entry(
                message_id="m4",
                sender="GitHub <notifications@github.com>",
                label="Notifications/Tools",
                error="LLM timeout",
            ),
        ]

        report = build_suggestions(
            entries=entries,
            account_name="default",
            decision_log_path=Path("data/accounts/default/decisions.jsonl"),
            min_samples=3,
            min_majority_ratio=0.9,
            max_review_ratio=0.2,
            max_error_ratio=0.5,
        )

        self.assertEqual(report.total_log_entries, 4)
        self.assertEqual(report.unique_messages, 4)
        self.assertEqual(len(report.suggestions), 2)
        self.assertEqual(report.suggestions[0].top_label, "Notifications/Tools")
        self.assertIn(report.suggestions[0].target_type, {"sender", "domain"})
        self.assertEqual(
            {suggestion.target_type for suggestion in report.suggestions},
            {"sender", "domain"},
        )


class AnalysisCliTestCase(unittest.TestCase):
    def test_analysis_suggestions_reads_account_decision_log(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            decision_log_path = data_dir / "accounts" / "default" / "decisions.jsonl"
            decision_log_path.parent.mkdir(parents=True, exist_ok=True)
            entries = [
                make_entry(
                    message_id="m1",
                    sender="GitHub <notifications@github.com>",
                    label="Notifications/Tools",
                ),
                make_entry(
                    message_id="m2",
                    sender="GitHub <notifications@github.com>",
                    label="Notifications/Tools",
                ),
            ]
            decision_log_path.write_text(
                "\n".join(entry.model_dump_json() for entry in entries) + "\n",
                encoding="utf-8",
            )

            result = runner.invoke(
                app,
                [
                    "analysis",
                    "suggestions",
                    "--min-samples",
                    "2",
                    "--majority-threshold",
                    "0.9",
                ],
                env={"LGA_DATA_DIR": str(data_dir)},
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Decision Analysis for default", result.output)
            self.assertIn("notifications@github.com", result.output)
            self.assertIn("from:github.com", result.output)
            self.assertIn("Notifications/Tools", result.output)
            self.assertIn("Suggestions are read-only", result.output)


if __name__ == "__main__":
    unittest.main()
