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

Install shell completion:

```bash
uv run local-gmail-agent completion install
# or
make completion
```

The installer writes two files:

- a shell completion file for zsh, bash, or fish
- a `local-gmail-agent` wrapper, usually under `~/.local/bin`, that runs this checkout through `uv`

It also updates your shell startup file, such as `~/.zshrc`, so the wrapper
directory is on `PATH` and completion is loaded in new terminals. Restart the
terminal after install, or run:

```bash
exec $SHELL -l
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

1. Download `lfm3-1.7b` in LM Studio (LiquidAI LFM3 1.7B, GGUF `Q8_0`).
2. Start the LM Studio local server.
3. Confirm the API responds:

```bash
curl -s http://localhost:1234/api/v1/models
```

The default model identifier is `lfm3-1.7b`. Confirm that the `/models`
response includes that exact `key`. The native chat API can load the downloaded
model automatically on the first request when the installed runtime supports it
([LM Studio native API quickstart](https://lmstudio.ai/docs/developer/rest/quickstart)).

For an existing install, update the model line in `.env`:

```dotenv
LGA_LLM_MODEL=lfm3-1.7b
```

`.env` overrides the application default. The previous local Gemma setting was
`LGA_LLM_MODEL=google/gemma-4-e4b`; see the [model history](../README.md#model-configuration-and-history).

Recommended runtime settings:

- native API base URL: `http://localhost:1234/api/v1`
- OpenAI-compatible base URL: `http://localhost:1234/v1`
- context length: `8192`
- temperature: `0.1`
- top-p: `0.9`
- max output tokens: `2048` (`LGA_LLM_MAX_TOKENS=2048`)
- native API reasoning for LFM3: `on` (`LGA_LM_STUDIO_REASONING=on`)

LFM3 enables reasoning by default in LM Studio. In the application smoke test,
the previous 512-token budget ran out before the final classification JSON.
Disabling reasoning also produced unfinished or invalid JSON in this setup.
The LFM3 configuration therefore keeps reasoning enabled and allows 2048 output
tokens for reasoning plus the final answer. The native API supports an explicit
[reasoning setting](https://lmstudio.ai/docs/developer/rest/chat).
The application default `auto` omits the override and uses LM Studio's default;
the example `.env` explicitly selects `on` for LFM3. This setting applies to
native API mode only.

These are the project's starting settings, not a benchmark of classification
quality. Review a dry run with the new model before changing automation behavior.

If you enabled LM Studio API auth, set `LGA_LM_STUDIO_API_TOKEN` in `.env`.

### LFM3 MLX Runtime Compatibility

The project uses the GGUF model `lfm3-1.7b`. The attempted MLX alternative,
LiquidAI `LFM3-1.7B-MLX-8bit` (`lfm3-1.7b-mlx`), failed to load with MLX
runtimes `1.13.1` and `1.14.0`:

```text
Model type lfm3 not supported. Error: No module named 'mlx_vlm.speculative.drafters.lfm3'
```

Runtime `1.14.0` bundles `mlx-vlm 0.7.10.post1`; the model maintainer reports
that LFM3 text support requires `mlx-vlm 0.7.11` or later in
[the upstream issue](https://github.com/lmstudio-ai/mlx-engine/issues/380).

Model discovery alone therefore does not verify inference compatibility.
If you want to try the MLX variant later, check for a compatible official runtime
and test a load before changing the shared model setting:

```bash
lms runtime update mlx --dry-run
lms load lfm3-1.7b-mlx --context-length 8192 --yes
```

If loading fails with this error, keep `LGA_LLM_MODEL=lfm3-1.7b` in `.env` to
continue using the GGUF model. Verify inference before switching to MLX.

## OpenAI-Compatible Mode

The project defaults to the LM Studio native REST API, but can use the OpenAI-compatible endpoint if needed:

```bash
LGA_LM_STUDIO_API_MODE=openai_compat uv run local-gmail-agent classify --limit 20 --dry-run
```

## First Run Checklist

1. Install dependencies with `uv`.
2. Put `credentials.json` in the repo root.
3. Start the LM Studio server with `lfm3-1.7b` downloaded.
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
