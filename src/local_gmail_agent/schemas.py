from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field


class EmailMessage(BaseModel):
    message_id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    label_ids: list[str] = Field(default_factory=list, repr=False)
    plain_text_body: str = Field(default="", repr=False)

    def llm_payload(self, allowed_labels: Sequence[str]) -> dict[str, Any]:
        return ClassificationPromptPayload.from_email(
            self,
            allowed_labels=allowed_labels,
        ).model_dump(mode="json")

    def to_log_context(self) -> "EmailLogContext":
        return EmailLogContext(
            message_id=self.message_id,
            thread_id=self.thread_id,
            sender=self.sender,
            subject=self.subject,
            date=self.date,
            snippet=self.snippet,
        )


class EmailLogContext(BaseModel):
    message_id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str


class LLMRawDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    archive: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=800)


class DecisionOutcome(BaseModel):
    label: str
    archive: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    review_required: bool = False
    fallback_reason: str | None = None


class DecisionLogEntry(BaseModel):
    timestamp: datetime
    email: EmailLogContext
    raw_decision: LLMRawDecision
    final_decision: DecisionOutcome
    labels_to_apply: list[str]
    dry_run: bool
    applied: bool
    error: str | None = None


class PromptOutputField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    description: str


class ClassificationPromptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_labels: tuple[str, ...]
    output_fields: tuple[PromptOutputField, ...]
    guidance: tuple[str, ...]
    email: EmailMessage

    @classmethod
    def from_email(
        cls,
        email: EmailMessage,
        allowed_labels: Sequence[str],
    ) -> "ClassificationPromptPayload":
        return cls(
            allowed_labels=tuple(allowed_labels),
            output_fields=(
                PromptOutputField(
                    name="label",
                    type="string",
                    description="Choose exactly one value from allowed_labels.",
                ),
                PromptOutputField(
                    name="archive",
                    type="boolean",
                    description="True only when the message can leave the inbox safely.",
                ),
                PromptOutputField(
                    name="confidence",
                    type="number",
                    description="A confidence score between 0 and 1.",
                ),
                PromptOutputField(
                    name="reason",
                    type="string",
                    description="A short explanation grounded in the email content.",
                ),
            ),
            guidance=(
                "Use Action/To Reply for emails that likely need a response.",
                "Use Action/Important for high-priority human action.",
                "Use Notifications/GitHub for GitHub notifications.",
                "Use Notifications/Tools for SaaS or developer-tool notifications.",
                "Use Newsletters for marketing or subscription content.",
                "Use LLM/To Review when the content is ambiguous.",
            ),
            email=email,
        )


def classification_json_schema(allowed_labels: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["label", "archive", "confidence", "reason"],
        "properties": {
            "label": {
                "type": "string",
                "enum": list(allowed_labels),
            },
            "archive": {"type": "boolean"},
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": 800,
            },
        },
    }
