# Setup Guide

This guide covers the full local setup for Gmail OAuth and LM Studio.

## Prerequisites

- Python `3.12+`
- `uv`
- a Gmail account you control
- LM Studio installed locally

## Platform Notes

- `macOS` is the primary supported platform today
- `Linux` should work for the core CLI, but built-in automation is not available yet
- `Windows` is not supported yet

The current automation commands rely on macOS `launchd`.

## Local Install

```bash
uv venv
uv sync
cp .env.example .env
```

Verify the CLI:

```bash
uv run local-gmail-agent --help
```

## Google Cloud Setup

1. Create a Google Cloud project.
2. Enable the Gmail API.
3. Open `Google Auth Platform`.
4. Configure the app as a desktop application.
5. Add yourself as a test user.
6. Create OAuth credentials of type `Desktop app`.
7. Download the JSON file and place it at `credentials.json` in the project root.

## Google Auth Platform Walkthrough

Google renamed the old `OAuth Consent Screen` flow into `Google Auth Platform`.

Use this sequence:

1. Open `Google Auth Platform`.
2. Click `Get Started`.
3. Fill the app information.
4. Choose `External` for the audience.
5. Add your Gmail address as the contact email.
6. Finish the flow and create the app.
7. Open `Google Auth Platform -> Audience`.
8. Confirm the publishing status is `Testing`.
9. Add your Gmail address to `Test users`.

If you skip the test-user step, local OAuth can fail even with valid credentials.

## Create OAuth Credentials

1. Open `Google Auth Platform -> Clients`.
2. If needed, use `APIs & Services -> Credentials`.
3. Click `+ CREATE CLIENT`.
4. Choose `Desktop App`.
5. Download the generated JSON file.
6. Rename it to `credentials.json`.
7. Place it in the repository root.

Expected path:

```text
local-gmail-agent/credentials.json
```

## Gmail Scopes

The CLI uses two scope levels:

- read-only mode: `https://www.googleapis.com/auth/gmail.readonly`
- modify mode: `https://www.googleapis.com/auth/gmail.modify`

Start with read-only auth:

```bash
uv run local-gmail-agent auth
```

Upgrade to modify mode later when you want label sync or live mutations:

```bash
uv run local-gmail-agent auth --modify
```

## LM Studio Setup

1. Download a local instruct model in LM Studio.
2. Start the LM Studio local server.
3. Confirm the API responds:

```bash
curl -s http://localhost:1234/api/v1/models
```

Recommended starting points on Apple Silicon:

- `Qwen3-14B-Instruct`
- `Qwen3-8B-Instruct`
- `Llama 3.1 8B Instruct`

Recommended runtime settings:

- native API base URL: `http://localhost:1234/api/v1`
- OpenAI-compatible base URL: `http://localhost:1234/v1`
- context length: `8192`
- temperature: `0.1`
- top-p: `0.9`
- max tokens: `512`

If you enabled LM Studio API auth, set `LGA_LM_STUDIO_API_TOKEN` in `.env`.

## OpenAI-Compatible Mode

The project defaults to the LM Studio native REST API, but can use the OpenAI-compatible endpoint if needed:

```bash
LGA_LM_STUDIO_API_MODE=openai_compat uv run local-gmail-agent classify --limit 20 --dry-run
```

## First Run Checklist

1. Install dependencies with `uv`.
2. Put `credentials.json` in the repo root.
3. Start LM Studio and load a model.
4. Run `uv run local-gmail-agent auth`.
5. Run `uv run local-gmail-agent classify --limit 20 --dry-run`.
6. If the dry run looks correct, run `uv run local-gmail-agent auth --modify`.
7. Run `uv run local-gmail-agent labels sync`.

## Additional Accounts

The CLI now stores runtime files per account under:

```text
data/accounts/<account-key>/
```

Create another account profile:

```bash
uv run local-gmail-agent accounts add "Work Gmail" --email you@company.com
```

Then target it explicitly:

```bash
uv run local-gmail-agent auth --account work-gmail
uv run local-gmail-agent classify --account work-gmail --dry-run
```

## Optional Automation

Once one account is authenticated and working manually, you can generate an unattended schedule:

```bash
uv run local-gmail-agent automation add --name "Three Times A Day" --every-hours 8 --limit 100 --apply
uv run local-gmail-agent automation enable --id <uuid>
```

See [Automation Guide](automation.md) for the full workflow.
