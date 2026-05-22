from __future__ import annotations

from local_gmail_agent.label_store import ManagedLabelConfig
from local_gmail_agent.schemas import DecisionOutcome, LLMRawDecision


def normalize_label(label: str, allowed_labels: tuple[str, ...]) -> str | None:
    cleaned = label.strip().casefold()
    for allowed in allowed_labels:
        if allowed.casefold() == cleaned:
            return allowed
    return None


def apply_safety_rules(
    raw_decision: LLMRawDecision,
    label_config: ManagedLabelConfig,
    confidence_threshold: float = 0.85,
) -> DecisionOutcome:
    policy_notes: list[str] = []
    review_required = False

    normalized_label = normalize_label(raw_decision.label, label_config.classification_labels)
    if normalized_label is None:
        normalized_label = label_config.fallback_label
        review_required = True
        policy_notes.append("invalid label replaced with fallback label")

    if raw_decision.confidence < confidence_threshold:
        normalized_label = label_config.fallback_label
        review_required = True
        policy_notes.append(
            f"confidence below threshold {confidence_threshold:.2f}"
        )

    archive = raw_decision.archive
    if review_required and archive:
        archive = False
        policy_notes.append("archiving disabled for review-required items")

    protected_labels = {
        label.casefold() for label in label_config.protected_archive_labels
    }
    if normalized_label.casefold() in protected_labels and archive:
        archive = False
        policy_notes.append("archiving disabled for action labels")

    return DecisionOutcome(
        label=normalized_label,
        archive=archive,
        confidence=raw_decision.confidence,
        reason=raw_decision.reason.strip(),
        review_required=review_required,
        fallback_reason="; ".join(policy_notes) or None,
    )


def labels_to_apply(
    decision: DecisionOutcome,
    reviewed_label: str,
) -> list[str]:
    labels = [decision.label, reviewed_label]
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(label)
    return deduped
