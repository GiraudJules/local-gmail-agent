from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, model_validator


DEFAULT_ACCOUNT_KEY = "default"
ACCOUNT_PROFILE_FILENAME = "account.json"


class AccountProfile(BaseModel):
    version: int = 1
    key: str
    display_name: str
    email_address: str | None = None
    gmail_user_id: str = "me"

    @model_validator(mode="after")
    def _normalize(self) -> "AccountProfile":
        self.key = normalize_account_key(self.key)
        self.display_name = self.display_name.strip() or self.key
        self.email_address = self.email_address.strip() if self.email_address else None
        self.gmail_user_id = self.gmail_user_id.strip() or "me"
        return self


def normalize_account_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    if not normalized:
        raise ValueError("Account name must contain at least one letter or number.")
    return normalized


def account_dir(accounts_root: Path, account_key: str) -> Path:
    return accounts_root / normalize_account_key(account_key)


def account_profile_path(accounts_root: Path, account_key: str) -> Path:
    return account_dir(accounts_root, account_key) / ACCOUNT_PROFILE_FILENAME


def load_account_profile(path: Path) -> AccountProfile:
    return AccountProfile.model_validate_json(path.read_text(encoding="utf-8"))


def save_account_profile(path: Path, profile: AccountProfile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.model_dump_json(indent=2) + "\n", encoding="utf-8")


def create_account_profile(
    accounts_root: Path,
    name: str,
    email_address: str | None = None,
    gmail_user_id: str = "me",
) -> AccountProfile:
    key = normalize_account_key(name)
    path = account_profile_path(accounts_root, key)
    if path.exists():
        raise FileExistsError(f"Account '{key}' already exists.")

    profile = AccountProfile(
        key=key,
        display_name=name.strip() or key,
        email_address=email_address,
        gmail_user_id=gmail_user_id,
    )
    save_account_profile(path, profile)
    return profile


def ensure_account_profile(
    accounts_root: Path,
    account_key: str,
    display_name: str | None = None,
) -> AccountProfile:
    key = normalize_account_key(account_key)
    path = account_profile_path(accounts_root, key)
    if path.exists():
        return load_account_profile(path)

    profile = AccountProfile(
        key=key,
        display_name=display_name or key,
    )
    save_account_profile(path, profile)
    return profile


def list_account_profiles(accounts_root: Path) -> list[AccountProfile]:
    if not accounts_root.exists():
        return []

    profiles: list[AccountProfile] = []
    for profile_path in sorted(accounts_root.glob(f"*/{ACCOUNT_PROFILE_FILENAME}")):
        profiles.append(load_account_profile(profile_path))
    return profiles
