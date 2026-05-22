# Usage Guide

This guide covers the CLI workflow after the project is installed and authenticated.

## Core Commands

Authenticate in read-only mode:

```bash
uv run local-gmail-agent auth
```

Authenticate a specific account:

```bash
uv run local-gmail-agent auth --account work-gmail
```

Upgrade the token to modify mode:

```bash
uv run local-gmail-agent auth --modify
```

Run a dry-run classification:

```bash
uv run local-gmail-agent classify --limit 20 --dry-run
```

`--limit` now means the number of eligible emails to process. Messages already marked with the managed reviewed label do not count toward that limit unless you pass `--reprocess`.

Apply labels and archive when policy allows:

```bash
uv run local-gmail-agent classify --query "from:github.com newer_than:30d" --apply
```

Force reclassification even if a message already has the managed reviewed label:

```bash
uv run local-gmail-agent classify --reprocess --limit 100 --query "in:inbox"
```

Inspect a Gmail message by id:

```bash
uv run local-gmail-agent inspect --message-id 18c7f0abc123def4
```

Create and inspect accounts:

```bash
uv run local-gmail-agent accounts add "Work Gmail" --email you@company.com
uv run local-gmail-agent accounts list
uv run local-gmail-agent accounts show --account work-gmail
```

Generate automation files for periodic runs:

```bash
uv run local-gmail-agent automation add --name "Inbox Cleanup" --every-hours 8 --limit 100 --apply
uv run local-gmail-agent automation list
```

Analyze past classifications and surface candidate Gmail rules:

```bash
uv run local-gmail-agent analysis suggestions --account default
uv run local-gmail-agent analysis suggestions --min-samples 5 --majority-threshold 0.85
```

## Typical Workflow

1. Authenticate with `uv run local-gmail-agent auth`.
2. Run `classify --dry-run` and inspect the decisions.
3. Upgrade to modify mode with `auth --modify`.
4. Sync Gmail labels with `labels sync`.
5. Re-run classification with `--apply`.

## Querying the Inbox

Classification accepts any Gmail search query through `--query`.

Examples:

```bash
uv run local-gmail-agent classify --query "in:inbox newer_than:7d" --dry-run
uv run local-gmail-agent classify --query "label:important newer_than:30d" --dry-run
uv run local-gmail-agent classify --query "from:github.com newer_than:30d" --apply
```

## Output Files

The CLI writes local runtime files under `data/`.

- `data/accounts/<account>/decisions.jsonl`: audit log of each account's classification runs
- `data/accounts/<account>/managed_labels.json`: managed logical taxonomy for one account
- `data/accounts/<account>/gmail_labels.json`: optional exported Gmail label snapshot for one account
- `data/accounts/<account>/token.json`: Gmail OAuth token for one account

## Dry Run vs Apply

Dry run:

- fetches mail
- classifies messages
- prints decisions
- writes the audit log
- does not mutate Gmail

Apply mode:

- creates missing managed Gmail labels if needed
- applies labels to the selected messages
- archives messages only when policy allows it

By default, classification skips messages that already carry the managed reviewed label for that account. Use `--reprocess` to override that guard.

## Suggestion Analysis

The analysis command reads `data/accounts/<account>/decisions.jsonl`, keeps the latest logged decision per Gmail message id, and looks for stable sender or domain patterns.

It is read-only for now:

- no Gmail filters are created
- no local rules are written automatically
- the output is intended as a review queue for future deterministic rule creation

Example:

```bash
uv run local-gmail-agent analysis suggestions --account default --min-samples 10
```

Typical high-confidence candidates look like:

- one sender email repeatedly mapped to the same label
- one sender domain repeatedly mapped to the same label
- low review-required rate
- low error rate

## Helper Commands

If you use the included `Makefile`, these shortcuts are available:

```bash
make sync
make test
make classify
make labels
```
