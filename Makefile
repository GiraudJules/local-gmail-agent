PYTHON ?= uv run

.PHONY: sync auth auth-modify classify classify-apply labels automation test coverage

sync:
	uv sync

auth:
	$(PYTHON) local-gmail-agent auth

auth-modify:
	$(PYTHON) local-gmail-agent auth --modify

classify:
	$(PYTHON) local-gmail-agent classify --limit 20 --dry-run

classify-apply:
	$(PYTHON) local-gmail-agent classify --query "in:inbox newer_than:30d" --apply

labels:
	$(PYTHON) local-gmail-agent labels sync

automation:
	$(PYTHON) local-gmail-agent automation add --name "Every 8 Hours" --every-hours 8 --limit 100 --apply

test:
	$(PYTHON) pytest

coverage:
	.venv/bin/pytest --cov=local_gmail_agent --cov-report=term-missing --cov-report=html --cov-report=json:coverage.json
	.venv/bin/python scripts/update_readme_coverage.py coverage.json README.md
