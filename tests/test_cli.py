from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from local_gmail_agent.cli import (
    app,
    collect_messages_for_classification,
    resolve_reviewed_label_id,
    should_skip_message,
)
from local_gmail_agent.label_store import ManagedLabelConfig, managed_gmail_label_name
from local_gmail_agent.schemas import EmailMessage


class AccountsCliTestCase(unittest.TestCase):
    def test_accounts_add_list_and_show(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            env = {"LGA_DATA_DIR": str(data_dir)}

            added = runner.invoke(
                app,
                ["accounts", "add", "Work Gmail", "--email", "jules@example.com"],
                env=env,
            )
            self.assertEqual(added.exit_code, 0, added.output)
            self.assertIn("work-gmail", added.output)

            listed = runner.invoke(app, ["accounts", "list"], env=env)
            self.assertEqual(listed.exit_code, 0, listed.output)
            self.assertIn("default", listed.output)
            self.assertIn("work-gmail", listed.output)

            shown = runner.invoke(app, ["accounts", "show", "--account", "work-gmail"], env=env)
            self.assertEqual(shown.exit_code, 0, shown.output)
            self.assertIn("jules@example.com", shown.output)
            self.assertIn("managed_labels.json", shown.output)


class ClassifyHelpersTestCase(unittest.TestCase):
    def test_should_skip_message_when_reviewed_label_present(self) -> None:
        self.assertTrue(should_skip_message(["Label_123"], "Label_123", reprocess=False))

    def test_should_not_skip_message_when_reprocess_is_enabled(self) -> None:
        self.assertFalse(should_skip_message(["Label_123"], "Label_123", reprocess=True))

    def test_resolve_reviewed_label_id_uses_managed_reviewed_label_name(self) -> None:
        label_config = ManagedLabelConfig()
        reviewed_label_name = managed_gmail_label_name(
            label_config.reviewed_label,
            label_config.managed_root,
        )

        class FakeGmailClient:
            def list_labels(self, include_system: bool = False) -> list[dict[str, str]]:
                self.include_system = include_system
                return [
                    {"name": reviewed_label_name, "id": "Reviewed_1"},
                    {"name": "Other", "id": "Other_1"},
                ]

        gmail = FakeGmailClient()

        resolved = resolve_reviewed_label_id(gmail, label_config)

        self.assertEqual(resolved, "Reviewed_1")
        self.assertFalse(gmail.include_system)

    def test_collect_messages_fetches_more_pages_until_limit_of_eligible_messages(self) -> None:
        class FakeGmailClient:
            def __init__(self) -> None:
                self.pages = {
                    None: (["m1", "m2"], "page-2"),
                    "page-2": (["m3", "m4"], None),
                }
                self.messages = {
                    "m1": EmailMessage(
                        message_id="m1",
                        thread_id="t1",
                        sender="a@example.com",
                        subject="one",
                        date="2026-05-20",
                        snippet="one",
                        label_ids=["Reviewed_1"],
                    ),
                    "m2": EmailMessage(
                        message_id="m2",
                        thread_id="t2",
                        sender="b@example.com",
                        subject="two",
                        date="2026-05-20",
                        snippet="two",
                        label_ids=[],
                    ),
                    "m3": EmailMessage(
                        message_id="m3",
                        thread_id="t3",
                        sender="c@example.com",
                        subject="three",
                        date="2026-05-20",
                        snippet="three",
                        label_ids=["Reviewed_1"],
                    ),
                    "m4": EmailMessage(
                        message_id="m4",
                        thread_id="t4",
                        sender="d@example.com",
                        subject="four",
                        date="2026-05-20",
                        snippet="four",
                        label_ids=[],
                    ),
                }

            def list_message_ids(self, query: str, limit: int, page_token: str | None = None) -> tuple[list[str], str | None]:
                return self.pages[page_token]

            def get_message(self, message_id: str) -> EmailMessage:
                return self.messages[message_id]

        gmail = FakeGmailClient()

        messages, skipped_count = collect_messages_for_classification(
            gmail=gmail,
            query="in:inbox",
            limit=2,
            reviewed_label_id="Reviewed_1",
            reprocess=False,
        )

        self.assertEqual([message.message_id for message in messages], ["m2", "m4"])
        self.assertEqual(skipped_count, 2)

    def test_collect_messages_reprocess_uses_limit_without_skipping(self) -> None:
        class FakeGmailClient:
            def list_message_ids(self, query: str, limit: int, page_token: str | None = None) -> tuple[list[str], str | None]:
                return ["m1", "m2"], None

            def get_message(self, message_id: str) -> EmailMessage:
                return EmailMessage(
                    message_id=message_id,
                    thread_id=f"t-{message_id}",
                    sender="x@example.com",
                    subject=message_id,
                    date="2026-05-20",
                    snippet=message_id,
                    label_ids=["Reviewed_1"],
                )

        messages, skipped_count = collect_messages_for_classification(
            gmail=FakeGmailClient(),
            query="in:inbox",
            limit=2,
            reviewed_label_id="Reviewed_1",
            reprocess=True,
        )

        self.assertEqual([message.message_id for message in messages], ["m1", "m2"])
        self.assertEqual(skipped_count, 0)


if __name__ == "__main__":
    unittest.main()
