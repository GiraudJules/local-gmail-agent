# Development Notes

This guide is for local development on the project itself.

## Environment

Create the local environment:

```bash
uv venv
uv sync
```

Run the tests:

```bash
uv run pytest
```

Run coverage:

```bash
make coverage
```

This writes:

- a terminal coverage summary with missing lines
- an HTML report under `htmlcov/`
- a JSON report at `coverage.json`
- an updated coverage badge in `README.md`

## Useful Commands

```bash
make sync
make test
make coverage
make classify
make labels
```

## Current Runtime Files

- `credentials.json`: local Google OAuth client file
- `data/accounts/<account>/token.json`: local Gmail OAuth token
- `data/accounts/<account>/decisions.jsonl`: decision audit log
- `data/accounts/<account>/managed_labels.json`: managed taxonomy config
- `data/accounts/<account>/gmail_labels.json`: Gmail label inventory snapshot
- `data/accounts/<account>/account.json`: account metadata
- `data/accounts/<account>/automation/`: persisted automation jobs, runner scripts, plists, logs, and reports

These files should stay local.

## Safety Model

- no email deletion path exists in the CLI
- Gmail mutations require modify auth plus explicit apply or sync commands
- label sync is non-destructive
- classification falls back to review for invalid or low-confidence outputs

## Roadmap

Near-term ideas:

- review queue for `LLM/To Review`
- correction memory from user feedback
- sender or domain rules before LLM fallback
- scheduled local automation

Known gaps:

- no web UI
- no built-in scheduler
- no CI workflow committed yet

## Publishing Notes

Before publishing the repository, verify that these files are not committed:

- `credentials.json`
- `data/accounts/*/token.json`
- `.env`
- local decision logs under `data/`
