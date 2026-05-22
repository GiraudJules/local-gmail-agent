from __future__ import annotations

import json
import re
from pathlib import Path


README_COVERAGE_PATTERN = re.compile(r"!\[Coverage\]\(https://img\.shields\.io/badge/coverage-[^)]+\)")


def load_coverage_percent(coverage_json_path: Path) -> int:
    payload = json.loads(coverage_json_path.read_text(encoding="utf-8"))
    total = payload.get("totals", {})
    percent = total.get("percent_covered_display")
    if percent is None:
        raise ValueError("coverage.json does not contain totals.percent_covered_display")
    return int(str(percent).rstrip("%"))


def badge_color(percent: int) -> str:
    if percent >= 90:
        return "brightgreen"
    if percent >= 80:
        return "green"
    if percent >= 70:
        return "yellowgreen"
    if percent >= 60:
        return "yellow"
    return "red"


def build_badge_markdown(percent: int) -> str:
    color = badge_color(percent)
    return f"![Coverage](https://img.shields.io/badge/coverage-{percent}%25-{color})"


def update_readme_coverage_badge(readme_path: Path, percent: int) -> None:
    content = readme_path.read_text(encoding="utf-8")
    badge = build_badge_markdown(percent)

    if README_COVERAGE_PATTERN.search(content):
        updated = README_COVERAGE_PATTERN.sub(badge, content, count=1)
    else:
        lines = content.splitlines()
        insert_at = 1 if lines and lines[0].startswith("# ") else 0
        lines.insert(insert_at, badge)
        updated = "\n".join(lines) + ("\n" if content.endswith("\n") else "")

    readme_path.write_text(updated, encoding="utf-8")
