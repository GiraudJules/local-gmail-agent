from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from local_gmail_agent.readme_coverage import load_coverage_percent, update_readme_coverage_badge


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: update_readme_coverage.py <coverage.json> <README.md>", file=sys.stderr)
        return 1

    coverage_json_path = Path(argv[1])
    readme_path = Path(argv[2])
    percent = load_coverage_percent(coverage_json_path)
    update_readme_coverage_badge(readme_path, percent)
    print(f"Updated README coverage badge to {percent}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
