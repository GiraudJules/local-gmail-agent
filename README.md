# local-gmail-agent

![Tests](https://img.shields.io/badge/tests-pytest-blue)
![Coverage](https://img.shields.io/badge/coverage-64%25-yellow)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Privacy](https://img.shields.io/badge/LLM-local--only-green)

Local-first Gmail labeling and archiving with Gmail API plus a local LLM served by LM Studio.

Email content stays on your machine and is sent only to your local LM Studio server. No external LLM API is required by this project.

## Status

This project is still in MVP shape.

- intended use: personal local automation
- current stability: usable, but still evolving
- non-goals for now: multi-account orchestration, team workflows, hosted deployment

## What It Does

- fetches Gmail messages with OAuth
- classifies them with a local LLM
- validates outputs against a managed label taxonomy
- can create and apply Gmail labels under `0-LGA/...`
- can archive eligible messages by removing the `INBOX` label
- writes a local decision log for auditability
- can analyze past classifications and suggest stable sender/domain rules
- supports account-scoped runtime data under `data/accounts/<account>/`
- skips messages already marked with the managed `LLM/Reviewed` label unless `--reprocess` is used

## Install

```bash
uv venv
uv sync
cp .env.example .env
```

The project targets Python `3.12+`.

Verify the CLI:

```bash
uv run local-gmail-agent --help
```

Install shell completion and a local command wrapper:

```bash
uv run local-gmail-agent completion install
# or
make completion
```

This writes a completion file for your current shell and a `local-gmail-agent`
wrapper that calls this checkout through `uv`. It also updates your shell
startup file so the wrapper and completion are loaded in new terminals. Restart
your shell after install, or run `exec $SHELL -l`.

Run the tests and coverage:

```bash
uv run pytest
make coverage
```

## Platform Support

- `macOS`: supported for the full workflow, including built-in automation via `launchd`
- `Linux`: core CLI should work, but built-in automation is not implemented yet
- `Windows`: not supported yet

In practice:

- `auth`, `classify`, `labels`, `accounts`, and `analysis` are intended to stay portable
- `automation enable` and the current scheduler integration are macOS-specific today

## Quick Start

1. Put `credentials.json` in the project root.
2. Start the LM Studio local server with `lfm3-1.7b` downloaded (GGUF).
3. Authenticate in read-only mode:

```bash
uv run local-gmail-agent auth
```

4. Run a safe dry-run classification:

```bash
uv run local-gmail-agent classify --limit 20 --dry-run
```

5. When you are ready to mutate Gmail:

```bash
uv run local-gmail-agent auth --modify
uv run local-gmail-agent labels sync
uv run local-gmail-agent classify --apply
```

To create an additional account profile first:

```bash
uv run local-gmail-agent accounts add "Work Gmail" --email you@company.com
uv run local-gmail-agent auth --account work-gmail
```

To create an automation job:

```bash
uv run local-gmail-agent automation add --name "Nightly Cleanup" --daily-at 01:30 --limit 100 --apply
uv run local-gmail-agent automation add
uv run local-gmail-agent automation update
uv run local-gmail-agent automation update --id <uuid> --daily-at 09:15 --dry-run
uv run local-gmail-agent automation enable --id <uuid>
```

To inspect repeated classification patterns and surface candidate rules:

```bash
uv run local-gmail-agent analysis suggestions --account default
```

## Docs

- [Setup Guide](docs/setup.md)
- [Usage Guide](docs/usage.md)
- [Label Management](docs/labels.md)
- [Automation Guide](docs/automation.md)
- [Development Notes](docs/development.md)

## Model Configuration and History

The default model is now `lfm3-1.7b` (LiquidAI LFM3 1.7B, GGUF `Q8_0`),
served locally by LM Studio through its native API.
Set `LGA_LLM_MODEL=lfm3-1.7b` in an existing `.env` as well;
set `LGA_LLM_MAX_TOKENS=2048` and `LGA_LM_STUDIO_REASONING=on` so the model
can finish its reasoning and final JSON. Updating the checkout does not
overwrite local settings. See the
[setup guide](docs/setup.md#lm-studio-setup) for verification and runtime settings.

The GGUF model replaces the attempted `lfm3-1.7b-mlx` configuration, which
failed to load with MLX runtimes `1.13.1` and `1.14.0`. The
[compatibility history](docs/setup.md#lfm3-mlx-runtime-compatibility) records that issue.

The previous model configuration used Gemma 4 E4B (`google/gemma-4-e4b`, GGUF
`Q4_K_M`). It is retained here as configuration history and can still be selected
by setting `LGA_LLM_MODEL=google/gemma-4-e4b` in `.env`. Earlier setup examples
used `qwen3-14b-instruct`.

Existing automation jobs read `.env` from this checkout at each run, so changing
the model there updates their next scheduled run. See
[updating existing automations](docs/automation.md#update-the-model-for-existing-jobs).

## Safety

- defaults to dry-run
- never mutates Gmail unless `--apply` is used
- never deletes emails
- falls back to `LLM/To Review` for invalid or low-confidence classifications
- never archives action labels configured as protected

## Project Layout

```text
src/local_gmail_agent/
tests/
data/
docs/
```
