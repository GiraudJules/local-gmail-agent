# Automation Guide

This guide covers unattended runs with LM Studio plus macOS scheduling through `launchd`.

## Job Model

Automation is now stored as first-class jobs.

Each job has:

- a UUID
- a human-friendly name
- an attached account
- a query
- a processing limit
- a mode (`apply` or `dry-run`)
- a schedule (`every N hours` or `daily at HH:MM`)
- an enabled or disabled state

Jobs are stored under:

```text
data/accounts/<account>/automation/jobs/
```

Per job, the project manages:

- `<uuid>.json`
- `<uuid>.sh`
- `<uuid>.plist`
- `../logs/<uuid>.stdout.log`
- `../logs/<uuid>.stderr.log`
- `../reports/<uuid>/latest.md`

## Create a Job

Every 8 hours:

```bash
uv run local-gmail-agent automation add \
  --name "Inbox Cleanup" \
  --every-hours 8 \
  --query "in:inbox" \
  --limit 100 \
  --apply
```

Every night at 01:30:

```bash
uv run local-gmail-agent automation add \
  --name "Nightly Pass" \
  --daily-at 01:30 \
  --query "in:inbox newer_than:30d" \
  --limit 100 \
  --apply
```

This creates the job and its local files, but does not enable the scheduler yet.

## List and Inspect Jobs

List all jobs:

```bash
uv run local-gmail-agent automation list
```

List one account only:

```bash
uv run local-gmail-agent automation list --account default
```

Show one job:

```bash
uv run local-gmail-agent automation show --id <uuid>
```

## Enable or Disable a Job

Enable one job through `launchd`:

```bash
uv run local-gmail-agent automation enable --id <uuid>
```

Disable it:

```bash
uv run local-gmail-agent automation disable --id <uuid>
```

Remove it entirely:

```bash
uv run local-gmail-agent automation remove --id <uuid>
```

## Run a Job Immediately

Run one saved automation job manually:

```bash
uv run local-gmail-agent automation run --id <uuid>
```

This uses the job's saved account, query, limit, mode, and LM Studio startup settings.

## One-Off Run Without Saving a Job

You can still run automation ad hoc:

```bash
uv run local-gmail-agent automation run --account default --limit 100 --apply
```

## LM Studio Startup

The job can try to start LM Studio automatically on macOS.

Defaults:

- start app: yes
- app name: `LM Studio`
- wait time: `120` seconds

Example:

```bash
uv run local-gmail-agent automation add \
  --name "Morning Sweep" \
  --every-hours 12 \
  --lm-studio-app "LM Studio" \
  --wait-seconds 180
```

## Reports

Every run writes:

- a timestamped markdown report
- a rolling `latest.md`

Per-job reports are stored in:

```text
data/accounts/<account>/automation/reports/<uuid>/
```

## Suggested Setup

1. Create the job:

```bash
uv run local-gmail-agent automation add \
  --name "Three Times A Day" \
  --every-hours 8 \
  --query "in:inbox" \
  --limit 100 \
  --apply
```

2. Copy the returned UUID.

3. Enable it:

```bash
uv run local-gmail-agent automation enable --id <uuid>
```
