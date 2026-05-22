from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from local_gmail_agent.readme_coverage import (
    badge_color,
    build_badge_markdown,
    load_coverage_percent,
    update_readme_coverage_badge,
)


class ReadmeCoverageTestCase(unittest.TestCase):
    def test_load_coverage_percent_reads_display_total(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            coverage_path = Path(temp_dir) / "coverage.json"
            coverage_path.write_text(
                json.dumps({"totals": {"percent_covered_display": "87"}}),
                encoding="utf-8",
            )

            self.assertEqual(load_coverage_percent(coverage_path), 87)

    def test_badge_color_uses_thresholds(self) -> None:
        self.assertEqual(badge_color(92), "brightgreen")
        self.assertEqual(badge_color(83), "green")
        self.assertEqual(badge_color(74), "yellowgreen")
        self.assertEqual(badge_color(65), "yellow")
        self.assertEqual(badge_color(51), "red")

    def test_update_readme_coverage_badge_replaces_existing_badge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            readme_path = Path(temp_dir) / "README.md"
            readme_path.write_text(
                "# local-gmail-agent\n"
                "![Coverage](https://img.shields.io/badge/coverage-10%25-red)\n"
                "![Tests](https://img.shields.io/badge/tests-pytest-blue)\n",
                encoding="utf-8",
            )

            update_readme_coverage_badge(readme_path, 88)

            updated = readme_path.read_text(encoding="utf-8")
            self.assertIn(build_badge_markdown(88), updated)
            self.assertNotIn("coverage-10%25-red", updated)

    def test_update_readme_coverage_badge_inserts_badge_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            readme_path = Path(temp_dir) / "README.md"
            readme_path.write_text(
                "# local-gmail-agent\n"
                "![Tests](https://img.shields.io/badge/tests-pytest-blue)\n",
                encoding="utf-8",
            )

            update_readme_coverage_badge(readme_path, 91)

            updated = readme_path.read_text(encoding="utf-8")
            lines = updated.splitlines()
            self.assertEqual(lines[1], build_badge_markdown(91))


if __name__ == "__main__":
    unittest.main()
