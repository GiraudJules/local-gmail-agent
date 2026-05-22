from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from local_gmail_agent.account_store import (
    DEFAULT_ACCOUNT_KEY,
    AccountProfile,
    create_account_profile,
    ensure_account_profile,
    list_account_profiles,
    load_account_profile,
    normalize_account_key,
)
from local_gmail_agent.analysis import SuggestionReport, build_suggestions, read_decision_log
from local_gmail_agent.automation import (
    build_launchd_plist,
    build_runner_script,
    ensure_lm_studio_ready,
    install_launch_agent,
    installed_launch_agent_path,
    is_launch_agent_loaded,
    launchd_label_for_job,
    parse_daily_time,
    uninstall_launch_agent,
)
from local_gmail_agent.automation_store import (
    AutomationJob,
    find_automation_job,
    job_paths,
    list_automation_jobs,
    remove_automation_job,
    save_automation_job,
)
from local_gmail_agent.config import Settings
from local_gmail_agent.gmail_client import GmailClient
from local_gmail_agent.label_store import (
    GmailLabelSnapshot,
    ManagedLabelConfig,
    load_or_create_label_config,
    managed_gmail_label_name,
    save_gmail_label_snapshot,
    save_label_config,
)
from local_gmail_agent.llm_client import LMStudioClient
from local_gmail_agent.logging import DecisionLogger, configure_logging
from local_gmail_agent.rules import apply_safety_rules, labels_to_apply
from local_gmail_agent.schemas import DecisionLogEntry, LLMRawDecision


app = typer.Typer(help="Local-first Gmail labeling agent backed by LM Studio.")
labels_app = typer.Typer(help="Label management commands.")
accounts_app = typer.Typer(help="Account management commands.")
analysis_app = typer.Typer(help="Classification analysis commands.")
automation_app = typer.Typer(help="Automation and scheduling commands.")
app.add_typer(labels_app, name="labels")
app.add_typer(accounts_app, name="accounts")
app.add_typer(analysis_app, name="analysis")
app.add_typer(automation_app, name="automation")

console = Console()


@dataclass
class ClassificationItem:
    message_id: str
    sender: str
    subject: str
    label: str
    archive: bool
    confidence: float
    status: str
    applied: bool
    review_required: bool
    error: str | None


@dataclass
class ClassificationRunResult:
    account_name: str
    query: str
    effective_dry_run: bool
    limit_requested: int
    skipped_count: int
    reviewed_label_name: str
    items: list[ClassificationItem]
    decision_log_path: Path
    started_at: datetime
    finished_at: datetime


def account_option() -> str:
    return typer.Option(
        DEFAULT_ACCOUNT_KEY,
        "--account",
        help="Account key to use. Run `accounts list` to see available accounts.",
    )


def load_settings(
    account_name: str = DEFAULT_ACCOUNT_KEY,
    require_existing: bool = True,
) -> Settings:
    normalized_account_name = normalize_account_key(account_name)
    settings = Settings(account_name=normalized_account_name)
    settings.ensure_runtime_dirs()
    settings.copy_legacy_runtime_files_if_needed()

    if settings.account_profile_path.exists():
        profile = load_account_profile(settings.account_profile_path)
    elif normalized_account_name == DEFAULT_ACCOUNT_KEY:
        profile = ensure_account_profile(
            settings.accounts_root,
            normalized_account_name,
            display_name="Default",
        )
    elif require_existing:
        raise typer.BadParameter(
            f"Unknown account '{normalized_account_name}'. Run `local-gmail-agent accounts add {normalized_account_name}` first."
        )
    else:
        profile = ensure_account_profile(settings.accounts_root, normalized_account_name)

    settings.account_name = profile.key
    settings.account_display_name = profile.display_name
    settings.account_email_address = profile.email_address
    settings.gmail_user_id = profile.gmail_user_id
    return settings


def load_label_config(settings: Settings) -> ManagedLabelConfig:
    return load_or_create_label_config(settings.managed_label_config_path)


def bootstrap_settings() -> Settings:
    return load_settings(DEFAULT_ACCOUNT_KEY, require_existing=False)


def optional_account_option() -> str | None:
    return typer.Option(
        None,
        "--account",
        help="Optional account filter.",
    )


def resolve_job(
    job_id: str,
) -> tuple[Settings, AutomationJob]:
    settings = bootstrap_settings()
    located = find_automation_job(settings.accounts_root, job_id)
    if located is None:
        raise typer.BadParameter(f"Unknown automation job '{job_id}'.")

    job, _ = located
    account_settings = load_settings(job.account_name)
    return account_settings, job


def _job_name_default(account_name: str, every_hours: int | None, daily_at: str | None) -> str:
    if every_hours is not None:
        return f"{account_name} every {every_hours}h"
    assert daily_at is not None
    return f"{account_name} daily {daily_at}"


def resolve_reviewed_label_id(
    gmail: GmailClient,
    label_config: ManagedLabelConfig,
) -> str | None:
    reviewed_label_name = managed_gmail_label_name(
        label_config.reviewed_label,
        label_config.managed_root,
    )
    labels = gmail.list_labels(include_system=False)
    label_map = {label["name"]: label["id"] for label in labels}
    return label_map.get(reviewed_label_name)


def should_skip_message(
    message_label_ids: list[str],
    reviewed_label_id: str | None,
    reprocess: bool,
) -> bool:
    if reprocess or reviewed_label_id is None:
        return False
    return reviewed_label_id in message_label_ids


def collect_messages_for_classification(
    gmail: GmailClient,
    query: str,
    limit: int,
    reviewed_label_id: str | None,
    reprocess: bool,
) -> tuple[list["EmailMessage"], int]:
    collected: list["EmailMessage"] = []
    skipped_count = 0
    page_token: str | None = None
    page_size = max(1, min(limit, 100))

    while len(collected) < limit:
        message_ids, page_token = gmail.list_message_ids(
            query=query,
            limit=page_size,
            page_token=page_token,
        )
        if not message_ids:
            break

        for message_id in message_ids:
            message = gmail.get_message(message_id)
            if should_skip_message(message.label_ids, reviewed_label_id, reprocess):
                skipped_count += 1
                continue
            collected.append(message)
            if len(collected) >= limit:
                break

        if page_token is None:
            break

    return collected, skipped_count


def run_classification(
    settings: Settings,
    query: str,
    limit: int,
    apply: bool,
    reprocess: bool,
) -> ClassificationRunResult:
    started_at = datetime.now(UTC)
    label_config = load_label_config(settings)
    effective_dry_run = not apply

    gmail = GmailClient(settings, modify_enabled=not effective_dry_run)
    llm = LMStudioClient(settings, label_config=label_config)
    decision_logger = DecisionLogger(settings.decision_log_path)
    reviewed_label_id = resolve_reviewed_label_id(gmail, label_config)
    messages, skipped_count = collect_messages_for_classification(
        gmail=gmail,
        query=query,
        limit=limit,
        reviewed_label_id=reviewed_label_id,
        reprocess=reprocess,
    )

    items: list[ClassificationItem] = []
    for message in messages:
        raw_decision = LLMRawDecision(
            label=label_config.fallback_label,
            archive=False,
            confidence=0.0,
            reason="Classification not attempted.",
        )
        final_decision = apply_safety_rules(
            raw_decision,
            label_config=label_config,
            confidence_threshold=settings.confidence_threshold,
        )
        labels: list[str] = []
        applied = False
        error: str | None = None

        try:
            raw_decision = llm.classify_email(message)
            final_decision = apply_safety_rules(
                raw_decision,
                label_config=label_config,
                confidence_threshold=settings.confidence_threshold,
            )
            labels = [
                managed_gmail_label_name(label, label_config.managed_root)
                for label in labels_to_apply(
                    final_decision,
                    reviewed_label=label_config.reviewed_label,
                )
            ]

            if not effective_dry_run:
                gmail.apply_labels_and_archive(
                    message_id=message.message_id,
                    label_names=labels,
                    archive=final_decision.archive,
                    legacy_name_map=label_config.legacy_to_managed_map,
                )
                applied = True
        except Exception as exc:
            error = str(exc)

        decision_logger.append(
            DecisionLogEntry(
                timestamp=datetime.now(UTC),
                email=message.to_log_context(),
                raw_decision=raw_decision,
                final_decision=final_decision,
                labels_to_apply=labels,
                dry_run=effective_dry_run,
                applied=applied,
                error=error,
            )
        )

        status = "would apply" if effective_dry_run else ("applied" if applied else "failed")
        if error:
            status = f"{status}: {error}"

        items.append(
            ClassificationItem(
                message_id=message.message_id,
                sender=message.sender or "-",
                subject=message.subject or "-",
                label=final_decision.label,
                archive=final_decision.archive,
                confidence=final_decision.confidence,
                status=status,
                applied=applied,
                review_required=final_decision.review_required,
                error=error,
            )
        )

    return ClassificationRunResult(
        account_name=settings.account_name,
        query=query,
        effective_dry_run=effective_dry_run,
        limit_requested=limit,
        skipped_count=skipped_count,
        reviewed_label_name=managed_gmail_label_name(
            label_config.reviewed_label,
            label_config.managed_root,
        ),
        items=items,
        decision_log_path=settings.decision_log_path,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )


def render_classification_result(result: ClassificationRunResult) -> None:
    if not result.items:
        if result.skipped_count:
            console.print(
                "No unprocessed messages matched the query. "
                "Use --reprocess to include messages already marked as reviewed."
            )
        else:
            console.print("No messages matched the query.")
        return

    table = Table(
        title=(
            f"Gmail classification for {result.account_name} "
            f"({'dry-run' if result.effective_dry_run else 'apply'})"
        )
    )
    table.add_column("Message ID", overflow="fold")
    table.add_column("Sender", overflow="fold")
    table.add_column("Subject", overflow="fold")
    table.add_column("Label")
    table.add_column("Archive")
    table.add_column("Confidence", justify="right")
    table.add_column("Status")

    for item in result.items:
        table.add_row(
            item.message_id,
            item.sender,
            item.subject,
            item.label,
            "yes" if item.archive else "no",
            f"{item.confidence:.2f}",
            item.status,
        )

    console.print(table)
    console.print(f"Decision log: [bold]{result.decision_log_path}[/bold]")
    if result.skipped_count:
        console.print(
            f"Skipped [bold]{result.skipped_count}[/bold] message(s) already marked with "
            f"[bold]{result.reviewed_label_name}[/bold]."
        )


def write_automation_report(
    reports_dir: Path,
    result: ClassificationRunResult,
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = result.finished_at.strftime("%Y%m%d-%H%M%S")
    report_path = reports_dir / f"{timestamp}.md"
    latest_path = reports_dir / "latest.md"

    label_counts = Counter(item.label for item in result.items)
    applied_count = sum(1 for item in result.items if item.applied)
    failed_count = sum(1 for item in result.items if item.error)
    review_required_count = sum(1 for item in result.items if item.review_required)
    lines = [
        "# Local Gmail Agent Automation Report",
        "",
        f"- Account: `{result.account_name}`",
        f"- Started at: `{result.started_at.isoformat()}`",
        f"- Finished at: `{result.finished_at.isoformat()}`",
        f"- Query: `{result.query}`",
        f"- Requested limit: `{result.limit_requested}`",
        f"- Mode: `{'dry-run' if result.effective_dry_run else 'apply'}`",
        f"- Processed: `{len(result.items)}`",
        f"- Skipped already reviewed: `{result.skipped_count}`",
        f"- Applied successfully: `{applied_count}`",
        f"- Failed: `{failed_count}`",
        f"- Review required: `{review_required_count}`",
        "",
        "## Label Counts",
        "",
    ]
    if label_counts:
        for label, count in sorted(label_counts.items()):
            lines.append(f"- `{label}`: `{count}`")
    else:
        lines.append("- none")

    failures = [item for item in result.items if item.error]
    if failures:
        lines.extend(["", "## Failures", ""])
        for item in failures:
            lines.append(
                f"- `{item.message_id}` | `{item.sender}` | `{item.subject}` | `{item.error}`"
            )

    report_content = "\n".join(lines) + "\n"
    report_path.write_text(report_content, encoding="utf-8")
    latest_path.write_text(report_content, encoding="utf-8")
    return report_path, latest_path


def save_automation_job_artifacts(
    settings: Settings,
    job: AutomationJob,
) -> tuple[Path, Path]:
    settings.automation_jobs_dir.mkdir(parents=True, exist_ok=True)
    settings.automation_logs_dir.mkdir(parents=True, exist_ok=True)
    paths = job_paths(settings.automation_dir, job.id)
    save_automation_job(settings.automation_dir, job)

    project_root = Path.cwd().resolve()
    command = [
        "uv",
        "run",
        "local-gmail-agent",
        "automation",
        "run",
        "--id",
        job.id,
    ]
    runner_content = build_runner_script(project_root, command)
    paths.runner_path.write_text(runner_content, encoding="utf-8")
    paths.runner_path.chmod(0o755)

    start_interval_seconds: int | None = None
    start_calendar_time: tuple[int, int] | None = None
    if job.schedule_type == "interval":
        assert job.every_hours is not None
        start_interval_seconds = job.every_hours * 3600
    else:
        assert job.daily_at is not None
        start_calendar_time = parse_daily_time(job.daily_at)

    plist_content = build_launchd_plist(
        label=launchd_label_for_job(job.account_name, job.id),
        script_path=paths.runner_path,
        stdout_path=paths.stdout_log_path,
        stderr_path=paths.stderr_log_path,
        start_interval_seconds=start_interval_seconds,
        start_calendar_time=start_calendar_time,
    )
    paths.plist_path.write_text(plist_content, encoding="utf-8")
    return paths.runner_path, paths.plist_path


def _render_automation_jobs_table(jobs: list[AutomationJob]) -> Table:
    table = Table(title="Automation Jobs")
    table.add_column("UUID")
    table.add_column("Name")
    table.add_column("Account")
    table.add_column("Schedule")
    table.add_column("Mode")
    table.add_column("Enabled")
    for job in jobs:
        table.add_row(
            job.id,
            job.name,
            job.account_name,
            job.schedule_description,
            "apply" if job.apply else "dry-run",
            "yes" if job.enabled else "no",
        )
    return table


def _render_account_table(profiles: list[AccountProfile], active_account: str | None = None) -> Table:
    table = Table(title="Accounts")
    table.add_column("Key")
    table.add_column("Display Name")
    table.add_column("Email")
    table.add_column("Gmail User ID")
    table.add_column("Active")
    for profile in profiles:
        table.add_row(
            profile.key,
            profile.display_name,
            profile.email_address or "-",
            profile.gmail_user_id,
            "yes" if profile.key == active_account else "",
        )
    return table


def _render_suggestion_table(report: SuggestionReport) -> Table:
    table = Table(title=f"Rule Suggestions for {report.account_name}")
    table.add_column("Type")
    table.add_column("Target", overflow="fold")
    table.add_column("Suggested Label")
    table.add_column("Samples", justify="right")
    table.add_column("Successful", justify="right")
    table.add_column("Majority", justify="right")
    table.add_column("Review", justify="right")
    table.add_column("Error", justify="right")
    table.add_column("Gmail Query", overflow="fold")
    for suggestion in report.suggestions:
        table.add_row(
            suggestion.target_type,
            suggestion.target_value,
            suggestion.top_label,
            str(suggestion.sample_size),
            str(suggestion.successful_count),
            f"{suggestion.top_label_ratio:.0%}",
            f"{suggestion.review_required_ratio:.0%}",
            f"{suggestion.error_ratio:.0%}",
            suggestion.query,
        )
    return table


@app.command()
def auth(
    account: str = account_option(),
    modify: bool = typer.Option(
        False,
        "--modify",
        help="Request gmail.modify access instead of gmail.readonly.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Authenticate with Gmail and save the account token locally."""
    configure_logging(verbose)
    settings = load_settings(account)
    gmail = GmailClient(settings, modify_enabled=modify)
    gmail.authenticate()
    scope_mode = "modify" if modify else "read-only"
    console.print(
        f"Authenticated account [bold]{settings.account_name}[/bold] in {scope_mode} mode. "
        f"Token saved to [bold]{settings.gmail_token_path}[/bold]."
    )


@app.command()
def classify(
    account: str = account_option(),
    query: str | None = typer.Option(
        None,
        "--query",
        help="Gmail search query.",
    ),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum emails to inspect."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Preview decisions without mutating Gmail.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Create labels, apply labels, and archive when allowed.",
    ),
    reprocess: bool = typer.Option(
        False,
        "--reprocess",
        help="Re-run classification even for messages that already have the managed reviewed label.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Fetch Gmail messages, classify them locally, and optionally apply labels."""
    configure_logging(verbose)
    settings = load_settings(account)
    effective_query = query or settings.default_query
    if not apply and not dry_run:
        raise typer.BadParameter("Use --apply to allow Gmail mutations.")

    result = run_classification(
        settings=settings,
        query=effective_query,
        limit=limit,
        apply=apply,
        reprocess=reprocess,
    )
    render_classification_result(result)


@labels_app.command("show")
def show_labels(account: str = account_option()) -> None:
    """Show the managed label configuration used by classification and sync."""
    settings = load_settings(account)
    label_config = load_label_config(settings)

    table = Table(title=f"Managed label configuration for {settings.account_name}")
    table.add_column("Setting")
    table.add_column("Value", overflow="fold")
    table.add_row("Account", settings.account_name)
    table.add_row("Config path", str(settings.managed_label_config_path))
    table.add_row("Managed root", label_config.managed_root)
    table.add_row("Fallback label", label_config.fallback_label)
    table.add_row("Reviewed label", label_config.reviewed_label)
    table.add_row(
        "Protected archive labels",
        ", ".join(label_config.protected_archive_labels),
    )
    table.add_row("Allowed labels", "\n".join(label_config.classification_labels))
    console.print(table)


@labels_app.command("add")
def add_label(
    name: str = typer.Argument(..., help="Logical label name, e.g. Work/Invoices."),
    account: str = account_option(),
) -> None:
    """Add a label to the managed JSON taxonomy."""
    settings = load_settings(account)
    label_config = load_label_config(settings)
    changed = label_config.add_label(name)
    save_label_config(settings.managed_label_config_path, label_config)

    if changed:
        console.print(
            f"Added label [bold]{name}[/bold] to [bold]{settings.managed_label_config_path}[/bold]."
        )
    else:
        console.print(
            f"Label [bold]{name}[/bold] is already present in [bold]{settings.managed_label_config_path}[/bold]."
        )


@labels_app.command("remove")
def remove_label(
    name: str = typer.Argument(
        ...,
        help="Logical label name to remove from the managed JSON taxonomy.",
    ),
    account: str = account_option(),
) -> None:
    """Remove a label from the managed JSON taxonomy."""
    settings = load_settings(account)
    label_config = load_label_config(settings)

    try:
        changed = label_config.remove_label(name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    save_label_config(settings.managed_label_config_path, label_config)

    if changed:
        console.print(
            f"Removed label [bold]{name}[/bold] from [bold]{settings.managed_label_config_path}[/bold]."
        )
    else:
        console.print(
            f"Label [bold]{name}[/bold] was not present in [bold]{settings.managed_label_config_path}[/bold]."
        )


@labels_app.command("pull")
def pull_labels(
    account: str = account_option(),
    include_system: bool = typer.Option(
        False,
        "--include-system",
        help="Include Gmail system labels like INBOX and SENT.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Export current Gmail labels to a local JSON snapshot."""
    configure_logging(verbose)
    settings = load_settings(account)
    gmail = GmailClient(settings, modify_enabled=False)
    snapshot = GmailLabelSnapshot.from_api_payloads(
        gmail.list_labels(include_system=include_system)
    )
    save_gmail_label_snapshot(settings.gmail_label_snapshot_path, snapshot)

    table = Table(title=f"Exported Gmail labels for {settings.account_name}")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Gmail ID")
    for label in snapshot.labels:
        table.add_row(label.name, label.type, label.id)
    console.print(table)
    console.print(f"Snapshot saved to [bold]{settings.gmail_label_snapshot_path}[/bold].")


@labels_app.command("sync")
def sync_labels(
    account: str = account_option(),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Create any missing managed labels in Gmail."""
    configure_logging(verbose)
    settings = load_settings(account)
    label_config = load_label_config(settings)
    gmail = GmailClient(settings, modify_enabled=True)
    label_map = gmail.sync_labels(
        label_config.managed_gmail_labels,
        legacy_name_map=label_config.legacy_to_managed_map,
    )

    table = Table(title=f"Synced Gmail labels for {settings.account_name}")
    table.add_column("Label")
    table.add_column("Gmail ID")
    for label_name, label_id in label_map.items():
        table.add_row(label_name, label_id)
    console.print(table)
    console.print("Sync is non-destructive: missing labels are created, stale labels are not deleted.")


@accounts_app.command("add")
def add_account(
    name: str = typer.Argument(..., help="Account name. This will be normalized into an account key."),
    email: str | None = typer.Option(
        None,
        "--email",
        help="Optional email address metadata for this account.",
    ),
    gmail_user_id: str = typer.Option(
        "me",
        "--gmail-user-id",
        help="Gmail API user id. Keep the default unless you know you need something else.",
    ),
) -> None:
    """Create a new account profile with its own runtime directory."""
    bootstrap_settings = load_settings(DEFAULT_ACCOUNT_KEY, require_existing=False)
    try:
        profile = create_account_profile(
            bootstrap_settings.accounts_root,
            name=name,
            email_address=email,
            gmail_user_id=gmail_user_id,
        )
    except FileExistsError as exc:
        raise typer.BadParameter(str(exc)) from exc

    account_settings = load_settings(profile.key)
    console.print(
        f"Created account [bold]{profile.key}[/bold] at [bold]{account_settings.account_dir}[/bold]."
    )


@accounts_app.command("list")
def list_accounts() -> None:
    """List configured accounts."""
    settings = load_settings(DEFAULT_ACCOUNT_KEY, require_existing=False)
    profiles = list_account_profiles(settings.accounts_root)
    if not profiles:
        console.print("No accounts configured.")
        return

    console.print(_render_account_table(profiles, active_account=DEFAULT_ACCOUNT_KEY))


@accounts_app.command("show")
def show_account(
    account: str = account_option(),
) -> None:
    """Show one account profile and its runtime paths."""
    settings = load_settings(account)
    table = Table(title=f"Account {settings.account_name}")
    table.add_column("Setting")
    table.add_column("Value", overflow="fold")
    table.add_row("Key", settings.account_name)
    table.add_row("Display name", settings.account_display_name)
    table.add_row("Email", settings.account_email_address or "-")
    table.add_row("Gmail user id", settings.gmail_user_id)
    table.add_row("Account dir", str(settings.account_dir))
    table.add_row("Token path", str(settings.gmail_token_path))
    table.add_row("Managed labels", str(settings.managed_label_config_path))
    table.add_row("Gmail label snapshot", str(settings.gmail_label_snapshot_path))
    table.add_row("Decision log", str(settings.decision_log_path))
    console.print(table)


@analysis_app.command("suggestions")
def analysis_suggestions(
    account: str = account_option(),
    min_samples: int = typer.Option(
        10,
        "--min-samples",
        min=1,
        help="Minimum latest-message sample size before surfacing a suggestion.",
    ),
    majority_threshold: float = typer.Option(
        0.9,
        "--majority-threshold",
        min=0.0,
        max=1.0,
        help="Minimum ratio for the dominant label.",
    ),
    max_review_rate: float = typer.Option(
        0.2,
        "--max-review-rate",
        min=0.0,
        max=1.0,
        help="Maximum allowed review-required ratio among successful classifications.",
    ),
    max_error_rate: float = typer.Option(
        0.1,
        "--max-error-rate",
        min=0.0,
        max=1.0,
        help="Maximum allowed failure ratio for the suggestion candidate.",
    ),
) -> None:
    """Analyze the decision log and suggest stable sender/domain Gmail rules."""
    settings = load_settings(account)
    entries = read_decision_log(settings.decision_log_path)
    if not entries:
        console.print(
            f"No decision log entries found for [bold]{settings.account_name}[/bold] at "
            f"[bold]{settings.decision_log_path}[/bold]."
        )
        return

    report = build_suggestions(
        entries=entries,
        account_name=settings.account_name,
        decision_log_path=settings.decision_log_path,
        min_samples=min_samples,
        min_majority_ratio=majority_threshold,
        max_review_ratio=max_review_rate,
        max_error_ratio=max_error_rate,
    )

    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Log entries: {report.total_log_entries}",
                    f"Unique messages: {report.unique_messages}",
                    f"Suggestions: {len(report.suggestions)}",
                ]
            ),
            title=f"Decision Analysis for {report.account_name}",
        )
    )

    if not report.suggestions:
        console.print(
            "No stable rule suggestions found with the current thresholds. "
            "Try lowering --min-samples or --majority-threshold."
        )
        return

    console.print(_render_suggestion_table(report))
    console.print("Suggestion summary:")
    for suggestion in report.suggestions:
        console.print(
            f"- {suggestion.target_type} {suggestion.target_value} -> "
            f"{suggestion.top_label} ({suggestion.query})"
        )
    console.print(
        "Suggestions are read-only. They do not create Gmail filters or local rules yet."
    )


@automation_app.command("run")
def automation_run(
    job_id: str | None = typer.Option(None, "--id", help="Automation job UUID."),
    account: str = account_option(),
    query: str | None = typer.Option(
        None,
        "--query",
        help="Gmail search query.",
    ),
    limit: int = typer.Option(20, "--limit", min=1, help="Number of eligible emails to process."),
    apply: bool = typer.Option(
        True,
        "--apply/--dry-run",
        help="Apply Gmail mutations during the automation run.",
    ),
    reprocess: bool = typer.Option(
        False,
        "--reprocess",
        help="Include emails already marked as reviewed.",
    ),
    start_lm_studio: bool = typer.Option(
        True,
        "--start-lm-studio/--no-start-lm-studio",
        help="Start LM Studio automatically before classification.",
    ),
    lm_studio_app: str = typer.Option(
        "LM Studio",
        "--lm-studio-app",
        help="macOS app name used when auto-starting LM Studio.",
    ),
    wait_seconds: int = typer.Option(
        120,
        "--wait-seconds",
        min=5,
        help="How long to wait for LM Studio to be ready.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run one unattended automation cycle and write a report."""
    configure_logging(verbose)

    if job_id is not None:
        settings, job = resolve_job(job_id)
        effective_query = job.query
        limit = job.limit
        apply = job.apply
        reprocess = job.reprocess
        start_lm_studio = job.start_lm_studio
        lm_studio_app = job.lm_studio_app
        wait_seconds = job.wait_seconds
        report_dir = job_paths(settings.automation_dir, job.id).reports_dir
    else:
        settings = load_settings(account)
        effective_query = query or settings.default_query
        report_dir = settings.automation_reports_dir

    ensure_lm_studio_ready(
        base_url=settings.lm_studio_native_base_url,
        app_name=lm_studio_app,
        timeout_seconds=wait_seconds,
        autostart=start_lm_studio,
    )

    result = run_classification(
        settings=settings,
        query=effective_query,
        limit=limit,
        apply=apply,
        reprocess=reprocess,
    )
    render_classification_result(result)
    report_path, latest_path = write_automation_report(report_dir, result)
    console.print(f"Automation report: [bold]{report_path}[/bold]")
    console.print(f"Latest report: [bold]{latest_path}[/bold]")


@automation_app.command("add")
def automation_add(
    account: str = account_option(),
    name: str | None = typer.Option(None, "--name", help="Human-friendly automation name."),
    query: str | None = typer.Option(
        None,
        "--query",
        help="Gmail search query to use for automated runs.",
    ),
    limit: int = typer.Option(100, "--limit", min=1, help="Eligible emails to process per run."),
    apply: bool = typer.Option(
        True,
        "--apply/--dry-run",
        help="Whether the automated run should mutate Gmail.",
    ),
    reprocess: bool = typer.Option(
        False,
        "--reprocess",
        help="Whether the automated run should include already reviewed emails.",
    ),
    every_hours: int | None = typer.Option(
        None,
        "--every-hours",
        min=1,
        help="Run the automation every N hours.",
    ),
    daily_at: str | None = typer.Option(
        None,
        "--daily-at",
        help="Run the automation every day at HH:MM (24h format).",
    ),
    start_lm_studio: bool = typer.Option(
        True,
        "--start-lm-studio/--no-start-lm-studio",
        help="Whether the automated run should try to start LM Studio first.",
    ),
    lm_studio_app: str = typer.Option(
        "LM Studio",
        "--lm-studio-app",
        help="macOS app name used when auto-starting LM Studio.",
    ),
    wait_seconds: int = typer.Option(
        120,
        "--wait-seconds",
        min=5,
        help="How long the automation run should wait for LM Studio.",
    ),
) -> None:
    """Create a persisted automation job without enabling it."""
    if every_hours is None and daily_at is None:
        raise typer.BadParameter("Choose either --every-hours or --daily-at.")
    if every_hours is not None and daily_at is not None:
        raise typer.BadParameter("Choose either --every-hours or --daily-at, not both.")

    settings = load_settings(account)
    effective_query = query or settings.default_query
    schedule_type = "interval" if every_hours is not None else "daily"
    job = AutomationJob(
        name=name or _job_name_default(settings.account_name, every_hours, daily_at),
        account_name=settings.account_name,
        query=effective_query,
        limit=limit,
        apply=apply,
        reprocess=reprocess,
        schedule_type=schedule_type,
        every_hours=every_hours,
        daily_at=daily_at,
        start_lm_studio=start_lm_studio,
        lm_studio_app=lm_studio_app,
        wait_seconds=wait_seconds,
        enabled=False,
    )
    runner_path, plist_path = save_automation_job_artifacts(settings, job)
    console.print(f"Job ID: {job.id}")
    console.print(f"Name: [bold]{job.name}[/bold]")
    console.print(f"Account: [bold]{job.account_name}[/bold]")
    console.print(f"Schedule: [bold]{job.schedule_description}[/bold]")
    console.print(f"Runner script: [bold]{runner_path}[/bold]")
    console.print(f"launchd plist: [bold]{plist_path}[/bold]")


@automation_app.command("list")
def automation_list(
    account: str | None = optional_account_option(),
) -> None:
    """List persisted automation jobs."""
    jobs: list[AutomationJob] = []
    if account is not None:
        settings = load_settings(account)
        jobs = list_automation_jobs(settings.automation_dir)
    else:
        settings = bootstrap_settings()
        for profile in list_account_profiles(settings.accounts_root):
            account_settings = load_settings(profile.key)
            jobs.extend(list_automation_jobs(account_settings.automation_dir))

    if not jobs:
        console.print("No automation jobs configured.")
        return
    console.print(_render_automation_jobs_table(jobs))


@automation_app.command("show")
def automation_show(
    job_id: str = typer.Option(..., "--id", help="Automation job UUID."),
) -> None:
    """Show one automation job and its runtime state."""
    settings, job = resolve_job(job_id)
    paths = job_paths(settings.automation_dir, job.id)
    installed_path = installed_launch_agent_path(job.account_name, job.id)
    table = Table(title=f"Automation job {job.id}")
    table.add_column("Setting")
    table.add_column("Value", overflow="fold")
    table.add_row("Name", job.name)
    table.add_row("Account", job.account_name)
    table.add_row("Query", job.query)
    table.add_row("Limit", str(job.limit))
    table.add_row("Mode", "apply" if job.apply else "dry-run")
    table.add_row("Reprocess", str(job.reprocess))
    table.add_row("Schedule", job.schedule_description)
    table.add_row("Enabled", str(job.enabled))
    table.add_row("Loaded in launchd", str(is_launch_agent_loaded(job.account_name, job.id)))
    table.add_row("JSON path", str(paths.json_path))
    table.add_row("Runner path", str(paths.runner_path))
    table.add_row("Plist path", str(paths.plist_path))
    table.add_row("Installed plist", str(installed_path))
    table.add_row("Latest report", str(paths.latest_report_path))
    console.print(table)


@automation_app.command("enable")
def automation_enable(
    job_id: str = typer.Option(..., "--id", help="Automation job UUID."),
) -> None:
    """Enable one automation job by installing its launchd agent."""
    settings, job = resolve_job(job_id)
    runner_path, plist_path = save_automation_job_artifacts(settings, job)
    installed_path = install_launch_agent(plist_path, job.account_name, job.id)
    job.enabled = True
    job.updated_at = datetime.now(UTC)
    save_automation_job(settings.automation_dir, job)
    console.print(f"Enabled automation job [bold]{job.id}[/bold].")
    console.print(f"Installed launchd agent: [bold]{installed_path}[/bold]")
    console.print(f"Runner script: [bold]{runner_path}[/bold]")


@automation_app.command("disable")
def automation_disable(
    job_id: str = typer.Option(..., "--id", help="Automation job UUID."),
) -> None:
    """Disable one automation job by unloading its launchd agent."""
    settings, job = resolve_job(job_id)
    removed_path = uninstall_launch_agent(job.account_name, job.id)
    job.enabled = False
    job.updated_at = datetime.now(UTC)
    save_automation_job(settings.automation_dir, job)
    console.print(f"Disabled automation job [bold]{job.id}[/bold].")
    console.print(f"Removed installed plist: [bold]{removed_path}[/bold]")


@automation_app.command("remove")
def automation_remove(
    job_id: str = typer.Option(..., "--id", help="Automation job UUID."),
) -> None:
    """Delete one automation job and its generated local files."""
    settings, job = resolve_job(job_id)
    uninstall_launch_agent(job.account_name, job.id)
    paths = remove_automation_job(settings.automation_dir, job.id)
    console.print(f"Removed automation job [bold]{job.id}[/bold].")
    console.print(f"Deleted job file: [bold]{paths.json_path}[/bold]")


@app.command()
def inspect(
    message_id: str = typer.Option(..., "--message-id", help="Gmail message id."),
    account: str = account_option(),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Inspect a Gmail message payload used for classification."""
    configure_logging(verbose)
    settings = load_settings(account)
    gmail = GmailClient(settings, modify_enabled=False)
    message = gmail.get_message(message_id)

    panel_text = (
        f"Account: {settings.account_name}\n"
        f"Sender: {message.sender or '-'}\n"
        f"Subject: {message.subject or '-'}\n"
        f"Date: {message.date or '-'}\n"
        f"Thread ID: {message.thread_id}\n\n"
        f"Snippet:\n{message.snippet or '-'}\n\n"
        f"Body preview:\n{message.plain_text_body or '-'}"
    )
    console.print(Panel(panel_text, title=f"Message {message.message_id}", expand=True))


if __name__ == "__main__":
    app()
