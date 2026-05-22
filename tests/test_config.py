from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_gmail_agent.config import Settings


class SettingsTestCase(unittest.TestCase):
    def test_account_runtime_paths_are_scoped_per_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                data_dir=Path(temp_dir) / "data",
                account_name="work-gmail",
            )

            self.assertEqual(settings.account_dir, Path(temp_dir) / "data" / "accounts" / "work-gmail")
            self.assertEqual(
                settings.managed_label_config_path,
                Path(temp_dir) / "data" / "accounts" / "work-gmail" / "managed_labels.json",
            )
            self.assertEqual(
                settings.decision_log_path,
                Path(temp_dir) / "data" / "accounts" / "work-gmail" / "decisions.jsonl",
            )

    def test_default_account_copies_legacy_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            old_cwd = Path.cwd()
            try:
                import os

                os.chdir(temp_path)
                settings = Settings(data_dir=Path("data"), account_name="default")
                settings.ensure_runtime_dirs()

                settings.legacy_gmail_token_path.write_text("legacy-token", encoding="utf-8")
                settings.legacy_decision_log_path.parent.mkdir(parents=True, exist_ok=True)
                settings.legacy_decision_log_path.write_text("legacy-log", encoding="utf-8")
                settings.legacy_managed_label_config_path.write_text("{}", encoding="utf-8")
                settings.legacy_gmail_label_snapshot_path.write_text("{}", encoding="utf-8")

                settings.copy_legacy_runtime_files_if_needed()

                self.assertEqual(settings.gmail_token_path.read_text(encoding="utf-8"), "legacy-token")
                self.assertEqual(settings.decision_log_path.read_text(encoding="utf-8"), "legacy-log")
                self.assertTrue(settings.managed_label_config_path.exists())
                self.assertTrue(settings.gmail_label_snapshot_path.exists())
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
