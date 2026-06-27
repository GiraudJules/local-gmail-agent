from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_gmail_agent.config import Settings


class SettingsTestCase(unittest.TestCase):
    def test_generic_llm_settings_default_to_lm_studio(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(settings.llm_provider, "lm_studio")
        self.assertEqual(settings.llm_api_mode, "native")
        self.assertEqual(settings.llm_native_base_url, "http://localhost:1234/api/v1")
        self.assertEqual(settings.llm_openai_base_url, "http://localhost:1234/v1")
        self.assertEqual(settings.llm_provider_display_name, "LM Studio")
        self.assertEqual(settings.llm_ready_url, "http://localhost:1234/api/v1/models")

    def test_ollama_provider_uses_tags_readiness_endpoint(self) -> None:
        settings = Settings(llm_provider="ollama", _env_file=None)

        self.assertEqual(settings.llm_provider_display_name, "Ollama")
        self.assertEqual(settings.llm_provider_app_name, "Ollama")
        self.assertEqual(settings.llm_ready_url, "http://localhost:11434/api/tags")

    def test_legacy_lm_studio_settings_feed_generic_llm_settings(self) -> None:
        settings = Settings(
            llm_base_url="http://localhost:8888/v1",
            lm_studio_api_mode="openai_compat",
            lm_studio_native_base_url="http://localhost:9999/api/v1",
            lm_studio_api_token="legacy-token",
            _env_file=None,
        )

        self.assertEqual(settings.llm_api_mode, "openai_compat")
        self.assertEqual(settings.llm_native_base_url, "http://localhost:9999/api/v1")
        self.assertEqual(settings.llm_openai_base_url, "http://localhost:8888/v1")
        self.assertEqual(settings.llm_api_token, "legacy-token")

    def test_generic_llm_settings_win_over_legacy_lm_studio_settings(self) -> None:
        settings = Settings(
            llm_api_mode="native",
            llm_openai_base_url="http://localhost:7777/v1",
            lm_studio_api_mode="openai_compat",
            lm_studio_openai_base_url="http://localhost:9999/v1",
            _env_file=None,
        )

        self.assertEqual(settings.llm_api_mode, "native")
        self.assertEqual(settings.llm_openai_base_url, "http://localhost:7777/v1")

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
