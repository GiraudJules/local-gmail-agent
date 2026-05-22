# Label Management

This guide covers the managed label taxonomy, Gmail label sync, and the non-destructive update behavior.

## Managed Label Config

The classifier uses a local JSON file as its source of truth:

- path: `data/accounts/<account>/managed_labels.json`
- created automatically on first use
- read by classification and Gmail label sync

You can inspect it with:

```bash
uv run local-gmail-agent labels show
```

For a non-default account:

```bash
uv run local-gmail-agent labels show --account work-gmail
```

## Editing the Managed Taxonomy

Add a label:

```bash
uv run local-gmail-agent labels add "Travel"
```

Remove a label:

```bash
uv run local-gmail-agent labels remove "Travel"
```

You can also edit `data/accounts/<account>/managed_labels.json` directly if you want tighter control.

## Syncing Labels to Gmail

Create or reconcile managed Gmail labels:

```bash
uv run local-gmail-agent auth --modify
uv run local-gmail-agent labels sync
```

Managed Gmail labels are stored under the configured root, which defaults to `0-LGA/...`.

Example:

- logical label: `Finance/Invoices`
- Gmail label: `0-LGA/Finance/Invoices`

## Exporting Existing Gmail Labels

Export the current label list from Gmail to a local JSON snapshot:

```bash
uv run local-gmail-agent labels pull
```

That writes:

- `data/accounts/<account>/gmail_labels.json`

Include Gmail system labels too:

```bash
uv run local-gmail-agent labels pull --include-system
```

This file is an inventory snapshot. It is not the source of truth for classification.

## What Happens When You Update the Managed Label List

Changing `data/accounts/<account>/managed_labels.json` affects future runs only for that account.

If you add a label:

- the classifier can start returning it
- `labels sync` can create its Gmail counterpart under `0-LGA/...`

If you remove a label:

- future classifications stop using it
- `labels sync` does not delete the old Gmail label
- emails already carrying that label keep it

## What Does Not Happen

The current implementation is intentionally non-destructive.

- it does not delete Gmail labels that disappeared from the JSON config
- it does not remove labels from historical messages
- it does not delete emails
- it does not rewrite old decision logs

## Legacy Label Renames

If you used older unmanaged label names, sync can rename those labels into the managed root instead of creating duplicates.

Example:

- old label: `Finance/Invoices`
- new managed label: `0-LGA/Finance/Invoices`

That rename keeps Gmail using the same label object where possible.

## Safety Notes

- fallback classifications go to `LLM/To Review`
- protected action labels are not auto-archived
- `LLM/Reviewed` is handled as a managed marker label during apply flows
- `LLM/Reviewed` is also used as the default skip marker to avoid classifying the same message twice
