from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_gmail_agent.account_store import (
    DEFAULT_ACCOUNT_KEY,
    create_account_profile,
    ensure_account_profile,
    list_account_profiles,
    normalize_account_key,
)


class AccountStoreTestCase(unittest.TestCase):
    def test_normalize_account_key_slugifies_name(self) -> None:
        self.assertEqual(normalize_account_key("Work Gmail"), "work-gmail")

    def test_create_and_list_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts_root = Path(temp_dir) / "accounts"

            create_account_profile(
                accounts_root,
                name="Work Gmail",
                email_address="jules@example.com",
            )
            ensure_account_profile(accounts_root, DEFAULT_ACCOUNT_KEY, display_name="Default")

            profiles = list_account_profiles(accounts_root)

            self.assertEqual([profile.key for profile in profiles], ["default", "work-gmail"])
            self.assertEqual(profiles[1].email_address, "jules@example.com")


if __name__ == "__main__":
    unittest.main()
