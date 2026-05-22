from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from local_gmail_agent.account_store import DEFAULT_ACCOUNT_KEY, account_dir


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LGA_",
        extra="ignore",
        case_sensitive=False,
    )

    account_name: str = DEFAULT_ACCOUNT_KEY
    account_display_name: str = DEFAULT_ACCOUNT_KEY
    account_email_address: str | None = None

    data_dir: Path = Field(default=Path("data"))
    gmail_credentials_path: Path = Field(default=Path("credentials.json"))
    gmail_user_id: str = "me"

    lm_studio_api_mode: Literal["native", "openai_compat"] = "native"
    lm_studio_native_base_url: str = "http://localhost:1234/api/v1"
    lm_studio_openai_base_url: str = "http://localhost:1234/v1"
    lm_studio_api_token: str | None = None
    llm_api_key: str = "lm-studio"
    llm_model: str | None = None
    llm_context_length: int = 8192
    llm_temperature: float = 0.1
    llm_top_p: float = 0.9
    llm_max_tokens: int = 512
    llm_seed: int | None = 42
    llm_timeout_seconds: float = 120.0

    default_query: str = "in:inbox newer_than:30d"
    default_limit: int = 20
    max_body_chars: int = 6000
    confidence_threshold: float = 0.85

    @property
    def readonly_scopes(self) -> tuple[str, ...]:
        return (GMAIL_READONLY_SCOPE,)

    @property
    def modify_scopes(self) -> tuple[str, ...]:
        return (GMAIL_MODIFY_SCOPE,)

    @property
    def accounts_root(self) -> Path:
        return self.data_dir / "accounts"

    @property
    def account_dir(self) -> Path:
        return account_dir(self.accounts_root, self.account_name)

    @property
    def account_profile_path(self) -> Path:
        return self.account_dir / "account.json"

    @property
    def gmail_token_path(self) -> Path:
        return self.account_dir / "token.json"

    @property
    def decision_log_path(self) -> Path:
        return self.account_dir / "decisions.jsonl"

    @property
    def managed_label_config_path(self) -> Path:
        return self.account_dir / "managed_labels.json"

    @property
    def gmail_label_snapshot_path(self) -> Path:
        return self.account_dir / "gmail_labels.json"

    @property
    def automation_dir(self) -> Path:
        return self.account_dir / "automation"

    @property
    def automation_jobs_dir(self) -> Path:
        return self.automation_dir / "jobs"

    @property
    def automation_reports_dir(self) -> Path:
        return self.automation_dir / "reports"

    @property
    def automation_logs_dir(self) -> Path:
        return self.automation_dir / "logs"

    @property
    def legacy_gmail_token_path(self) -> Path:
        return Path("token.json")

    @property
    def legacy_decision_log_path(self) -> Path:
        return self.data_dir / "decisions.jsonl"

    @property
    def legacy_managed_label_config_path(self) -> Path:
        return self.data_dir / "managed_labels.json"

    @property
    def legacy_gmail_label_snapshot_path(self) -> Path:
        return self.data_dir / "gmail_labels.json"

    def ensure_runtime_dirs(self) -> None:
        self.accounts_root.mkdir(parents=True, exist_ok=True)
        self.account_dir.mkdir(parents=True, exist_ok=True)

    def copy_legacy_runtime_files_if_needed(self) -> None:
        if self.account_name != DEFAULT_ACCOUNT_KEY:
            return

        legacy_pairs = (
            (self.legacy_gmail_token_path, self.gmail_token_path),
            (self.legacy_decision_log_path, self.decision_log_path),
            (self.legacy_managed_label_config_path, self.managed_label_config_path),
            (self.legacy_gmail_label_snapshot_path, self.gmail_label_snapshot_path),
        )
        for legacy_path, target_path in legacy_pairs:
            if not legacy_path.exists() or target_path.exists():
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_path, target_path)
