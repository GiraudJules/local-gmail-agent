from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


DEFAULT_ALLOWED_LABELS: tuple[str, ...] = (
    "Action/To Reply",
    "Action/Important",
    "Finance/Invoices",
    "Finance/Receipts",
    "Work/Clients",
    "Work/Recruiting",
    "Work/Partners",
    "Notifications/GitHub",
    "Notifications/Tools",
    "Newsletters",
    "Personal",
    "LLM/To Review",
)
DEFAULT_PROTECTED_ARCHIVE_LABELS: tuple[str, ...] = (
    "Action/Important",
    "Action/To Reply",
)
DEFAULT_MANAGED_GMAIL_LABEL_ROOT = "0-LGA"
DEFAULT_FALLBACK_LABEL = "LLM/To Review"
DEFAULT_REVIEWED_LABEL = "LLM/Reviewed"


def managed_gmail_label_name(label: str, managed_root: str = DEFAULT_MANAGED_GMAIL_LABEL_ROOT) -> str:
    return f"{managed_root}/{label}"


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


class ManagedLabelConfig(BaseModel):
    version: int = 1
    managed_root: str = DEFAULT_MANAGED_GMAIL_LABEL_ROOT
    allowed_labels: list[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_LABELS))
    protected_archive_labels: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PROTECTED_ARCHIVE_LABELS)
    )
    fallback_label: str = DEFAULT_FALLBACK_LABEL
    reviewed_label: str = DEFAULT_REVIEWED_LABEL

    @model_validator(mode="after")
    def _normalize(self) -> "ManagedLabelConfig":
        self.managed_root = self.managed_root.strip() or DEFAULT_MANAGED_GMAIL_LABEL_ROOT
        self.allowed_labels = _dedupe_preserving_order(self.allowed_labels)
        self.protected_archive_labels = _dedupe_preserving_order(self.protected_archive_labels)
        self.fallback_label = self.fallback_label.strip() or DEFAULT_FALLBACK_LABEL
        self.reviewed_label = self.reviewed_label.strip() or DEFAULT_REVIEWED_LABEL

        if self.fallback_label.casefold() not in {
            label.casefold() for label in self.allowed_labels
        }:
            self.allowed_labels.append(self.fallback_label)

        return self

    @property
    def classification_labels(self) -> tuple[str, ...]:
        return tuple(self.allowed_labels)

    @property
    def sync_label_names(self) -> tuple[str, ...]:
        names = list(self.allowed_labels)
        if self.reviewed_label.casefold() not in {name.casefold() for name in names}:
            names.append(self.reviewed_label)
        return tuple(names)

    @property
    def legacy_to_managed_map(self) -> dict[str, str]:
        return {
            name: managed_gmail_label_name(name, self.managed_root)
            for name in self.sync_label_names
        }

    @property
    def managed_gmail_labels(self) -> tuple[str, ...]:
        return tuple(
            managed_gmail_label_name(name, self.managed_root) for name in self.sync_label_names
        )

    def add_label(self, label_name: str) -> bool:
        cleaned = label_name.strip()
        if not cleaned:
            raise ValueError("Label name cannot be empty.")
        if cleaned.casefold() in {label.casefold() for label in self.allowed_labels}:
            return False
        self.allowed_labels.append(cleaned)
        self.allowed_labels = _dedupe_preserving_order(self.allowed_labels)
        return True

    def remove_label(self, label_name: str) -> bool:
        cleaned = label_name.strip()
        if not cleaned:
            raise ValueError("Label name cannot be empty.")
        if cleaned.casefold() == self.fallback_label.casefold():
            raise ValueError("The fallback label cannot be removed.")
        if cleaned.casefold() == self.reviewed_label.casefold():
            raise ValueError("The reviewed label is managed separately and cannot be removed here.")

        remaining = [
            label for label in self.allowed_labels if label.casefold() != cleaned.casefold()
        ]
        if len(remaining) == len(self.allowed_labels):
            return False
        self.allowed_labels = remaining
        return True


class GmailLabelSnapshotEntry(BaseModel):
    id: str
    name: str
    type: str
    messages_total: int | None = None
    messages_unread: int | None = None
    threads_total: int | None = None
    threads_unread: int | None = None
    label_list_visibility: str | None = None
    message_list_visibility: str | None = None

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "GmailLabelSnapshotEntry":
        return cls(
            id=payload["id"],
            name=payload["name"],
            type=payload["type"],
            messages_total=payload.get("messagesTotal"),
            messages_unread=payload.get("messagesUnread"),
            threads_total=payload.get("threadsTotal"),
            threads_unread=payload.get("threadsUnread"),
            label_list_visibility=payload.get("labelListVisibility"),
            message_list_visibility=payload.get("messageListVisibility"),
        )


class GmailLabelSnapshot(BaseModel):
    fetched_at: datetime
    labels: list[GmailLabelSnapshotEntry]

    @classmethod
    def from_api_payloads(cls, payloads: list[dict[str, Any]]) -> "GmailLabelSnapshot":
        return cls(
            fetched_at=datetime.now(UTC),
            labels=[GmailLabelSnapshotEntry.from_api_payload(payload) for payload in payloads],
        )


def load_or_create_label_config(path: Path) -> ManagedLabelConfig:
    if not path.exists():
        config = ManagedLabelConfig()
        save_label_config(path, config)
        return config

    return ManagedLabelConfig.model_validate_json(path.read_text(encoding="utf-8"))


def save_label_config(path: Path, config: ManagedLabelConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")


def save_gmail_label_snapshot(path: Path, snapshot: GmailLabelSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
