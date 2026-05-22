from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_gmail_agent.label_store import (
    ManagedLabelConfig,
    load_or_create_label_config,
    save_label_config,
)


class LabelStoreTestCase(unittest.TestCase):
    def test_missing_config_is_bootstrapped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "managed_labels.json"

            config = load_or_create_label_config(config_path)

            self.assertTrue(config_path.exists())
            self.assertIn("Action/To Reply", config.classification_labels)
            self.assertIn(config.reviewed_label, config.sync_label_names)

    def test_add_and_remove_label_round_trip(self) -> None:
        config = ManagedLabelConfig()

        added = config.add_label("Travel")
        removed = config.remove_label("Travel")

        self.assertTrue(added)
        self.assertTrue(removed)
        self.assertNotIn("Travel", config.classification_labels)

    def test_save_and_reload_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "managed_labels.json"
            config = ManagedLabelConfig()
            config.add_label("Travel")
            save_label_config(config_path, config)

            reloaded = load_or_create_label_config(config_path)

            self.assertIn("Travel", reloaded.classification_labels)


if __name__ == "__main__":
    unittest.main()
