from __future__ import annotations

from collections import Counter
from email.utils import parseaddr
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from local_gmail_agent.schemas import DecisionLogEntry


SuggestionTargetType = Literal["sender", "domain"]


class SenderIdentity(BaseModel):
    sender: str
    email_address: str | None = None
    domain: str | None = None


class SuggestionCandidate(BaseModel):
    target_type: SuggestionTargetType
    target_value: str
    query: str
    sample_size: int = Field(ge=0)
    successful_count: int = Field(ge=0)
    top_label: str
    top_label_count: int = Field(ge=0)
    top_label_ratio: float = Field(ge=0.0, le=1.0)
    review_required_count: int = Field(ge=0)
    review_required_ratio: float = Field(ge=0.0, le=1.0)
    error_count: int = Field(ge=0)
    error_ratio: float = Field(ge=0.0, le=1.0)
    rationale: str


class SuggestionReport(BaseModel):
    account_name: str
    decision_log_path: Path
    total_log_entries: int = Field(ge=0)
    unique_messages: int = Field(ge=0)
    suggestions: list[SuggestionCandidate]


def read_decision_log(path: Path) -> list[DecisionLogEntry]:
    if not path.exists():
        return []

    entries: list[DecisionLogEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            entries.append(DecisionLogEntry.model_validate_json(stripped))
    return entries


def latest_entries_by_message(entries: list[DecisionLogEntry]) -> list[DecisionLogEntry]:
    latest: dict[str, DecisionLogEntry] = {}
    for entry in sorted(entries, key=lambda item: item.timestamp):
        latest[entry.email.message_id] = entry
    return list(latest.values())


def classify_sender(sender: str) -> SenderIdentity:
    _, email_address = parseaddr(sender)
    normalized_email = email_address.strip().casefold() or None
    domain: str | None = None
    if normalized_email and "@" in normalized_email:
        domain = normalized_email.split("@", maxsplit=1)[1]
    return SenderIdentity(
        sender=sender,
        email_address=normalized_email,
        domain=domain,
    )


def _query_for_target(target_type: SuggestionTargetType, target_value: str) -> str:
    if target_type == "sender":
        return f"from:{target_value}"
    return f"from:{target_value}"


def build_suggestions(
    entries: list[DecisionLogEntry],
    account_name: str,
    decision_log_path: Path,
    min_samples: int = 10,
    min_majority_ratio: float = 0.9,
    max_review_ratio: float = 0.2,
    max_error_ratio: float = 0.1,
    excluded_labels: set[str] | None = None,
) -> SuggestionReport:
    latest_entries = latest_entries_by_message(entries)
    excluded = {label.casefold() for label in (excluded_labels or {"LLM/To Review"})}

    grouped: dict[tuple[SuggestionTargetType, str], list[DecisionLogEntry]] = {}
    for entry in latest_entries:
        identity = classify_sender(entry.email.sender)
        if identity.email_address:
            grouped.setdefault(("sender", identity.email_address), []).append(entry)
        if identity.domain:
            grouped.setdefault(("domain", identity.domain), []).append(entry)

    suggestions: list[SuggestionCandidate] = []
    for (target_type, target_value), target_entries in grouped.items():
        sample_size = len(target_entries)
        if sample_size < min_samples:
            continue

        error_count = sum(1 for entry in target_entries if entry.error is not None)
        error_ratio = error_count / sample_size
        if error_ratio > max_error_ratio:
            continue

        successful_entries = [entry for entry in target_entries if entry.error is None]
        if not successful_entries:
            continue

        review_required_count = sum(
            1 for entry in successful_entries if entry.final_decision.review_required
        )
        review_required_ratio = review_required_count / len(successful_entries)
        if review_required_ratio > max_review_ratio:
            continue

        label_counts = Counter(entry.final_decision.label for entry in successful_entries)
        top_label, top_label_count = label_counts.most_common(1)[0]
        if top_label.casefold() in excluded:
            continue

        top_label_ratio = top_label_count / len(successful_entries)
        if top_label_ratio < min_majority_ratio:
            continue

        rationale = (
            f"{top_label_count} of {len(successful_entries)} successful classifications "
            f"for {target_type} '{target_value}' were labeled '{top_label}'."
        )
        suggestions.append(
            SuggestionCandidate(
                target_type=target_type,
                target_value=target_value,
                query=_query_for_target(target_type, target_value),
                sample_size=sample_size,
                successful_count=len(successful_entries),
                top_label=top_label,
                top_label_count=top_label_count,
                top_label_ratio=top_label_ratio,
                review_required_count=review_required_count,
                review_required_ratio=review_required_ratio,
                error_count=error_count,
                error_ratio=error_ratio,
                rationale=rationale,
            )
        )

    suggestions.sort(
        key=lambda item: (
            item.top_label_ratio,
            item.sample_size,
            item.target_type == "sender",
        ),
        reverse=True,
    )
    return SuggestionReport(
        account_name=account_name,
        decision_log_path=decision_log_path,
        total_log_entries=len(entries),
        unique_messages=len(latest_entries),
        suggestions=suggestions,
    )
