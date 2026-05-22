from __future__ import annotations

import base64
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from local_gmail_agent.config import Settings
from local_gmail_agent.schemas import EmailMessage


class GmailClient:
    def __init__(self, settings: Settings, modify_enabled: bool = False) -> None:
        self.settings = settings
        self.modify_enabled = modify_enabled
        self.scopes = (
            settings.modify_scopes if modify_enabled else settings.readonly_scopes
        )
        self._credentials: Credentials | None = None
        self._service: Resource | None = None

    def authenticate(self) -> Credentials:
        credentials = self._load_credentials()
        self._credentials = credentials
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return credentials

    def fetch_messages(self, query: str, limit: int) -> list[EmailMessage]:
        message_ids, _ = self.list_message_ids(query=query, limit=limit)
        return [self.get_message(message_id) for message_id in message_ids]

    def list_message_ids(
        self,
        query: str,
        limit: int,
        page_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        response = (
            self.service.users()
            .messages()
            .list(
                userId=self.settings.gmail_user_id,
                q=query,
                maxResults=limit,
                pageToken=page_token,
            )
            .execute()
        )
        messages = response.get("messages", [])
        return [message["id"] for message in messages], response.get("nextPageToken")

    def get_message(self, message_id: str) -> EmailMessage:
        payload = (
            self.service.users()
            .messages()
            .get(
                userId=self.settings.gmail_user_id,
                id=message_id,
                format="full",
            )
            .execute()
        )
        return self._parse_message(payload)

    def list_labels(self, include_system: bool = False) -> list[dict[str, Any]]:
        labels = (
            self.service.users()
            .labels()
            .list(userId=self.settings.gmail_user_id)
            .execute()
            .get("labels", [])
        )
        if include_system:
            return labels
        return [label for label in labels if label.get("type") != "system"]

    def sync_labels(
        self,
        label_names: Sequence[str],
        legacy_name_map: dict[str, str] | None = None,
    ) -> dict[str, str]:
        if not self.modify_enabled:
            raise RuntimeError("Label sync requires modify mode. Run auth --modify first.")

        labels = (
            self.service.users()
            .labels()
            .list(userId=self.settings.gmail_user_id)
            .execute()
            .get("labels", [])
        )
        label_map = {label["name"]: label["id"] for label in labels}

        if legacy_name_map:
            for legacy_name, target_name in legacy_name_map.items():
                if target_name in label_map or legacy_name not in label_map:
                    continue
                updated = (
                    self.service.users()
                    .labels()
                    .patch(
                        userId=self.settings.gmail_user_id,
                        id=label_map[legacy_name],
                        body={
                            "name": target_name,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    )
                    .execute()
                )
                del label_map[legacy_name]
                label_map[target_name] = updated["id"]

        for name in label_names:
            if name in label_map:
                continue
            created = (
                self.service.users()
                .labels()
                .create(
                    userId=self.settings.gmail_user_id,
                    body={
                        "name": name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            label_map[name] = created["id"]

        return {name: label_map[name] for name in label_names}

    def apply_labels_and_archive(
        self,
        message_id: str,
        label_names: Sequence[str],
        archive: bool,
        legacy_name_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.modify_enabled:
            raise RuntimeError("Message mutation requires modify mode.")

        label_map = self.sync_labels(label_names, legacy_name_map=legacy_name_map)
        body: dict[str, list[str]] = {
            "addLabelIds": [label_map[name] for name in label_names],
            "removeLabelIds": ["INBOX"] if archive else [],
        }
        return (
            self.service.users()
            .messages()
            .modify(
                userId=self.settings.gmail_user_id,
                id=message_id,
                body=body,
            )
            .execute()
        )

    @property
    def service(self) -> Resource:
        if self._service is None:
            self.authenticate()
        assert self._service is not None
        return self._service

    def _load_credentials(self) -> Credentials:
        credentials_path = self.settings.gmail_credentials_path
        token_path = self.settings.gmail_token_path

        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Missing OAuth client file: {credentials_path}. "
                "Download credentials.json from Google Cloud first."
            )

        credentials: Credentials | None = None
        stored_scopes = self._stored_token_scopes(token_path)
        token_scopes_are_usable = self._requested_scopes_are_covered(stored_scopes)

        if token_path.exists() and token_scopes_are_usable:
            credentials = Credentials.from_authorized_user_file(
                str(token_path),
                scopes=list(self.scopes),
            )

        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())

        if not credentials or not credentials.valid or not credentials.has_scopes(list(self.scopes)):
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                scopes=list(self.scopes),
            )
            credentials = flow.run_local_server(port=0)

        token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    def _parse_message(self, payload: dict[str, Any]) -> EmailMessage:
        message_payload = payload.get("payload", {})
        headers = {
            header.get("name", "").lower(): header.get("value", "")
            for header in message_payload.get("headers", [])
        }

        plain_text_parts = self._collect_parts(message_payload, "text/plain")
        html_parts = self._collect_parts(message_payload, "text/html")
        body = "\n\n".join(part for part in plain_text_parts if part.strip()).strip()

        if not body and html_parts:
            body = self._strip_html("\n\n".join(html_parts))

        if not body:
            body = payload.get("snippet", "")

        return EmailMessage(
            message_id=payload["id"],
            thread_id=payload["threadId"],
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            date=headers.get("date", self._internal_date_to_iso(payload.get("internalDate"))),
            snippet=payload.get("snippet", ""),
            label_ids=payload.get("labelIds", []),
            plain_text_body=self._truncate_text(self._normalize_text(body)),
        )

    def _collect_parts(self, part: dict[str, Any], mime_type: str) -> list[str]:
        results: list[str] = []
        if part.get("mimeType") == mime_type:
            data = part.get("body", {}).get("data")
            if data:
                results.append(self._decode_message_part(data))

        for child in part.get("parts", []):
            results.extend(self._collect_parts(child, mime_type))

        return results

    def _decode_message_part(self, data: str) -> str:
        padded = data + ("=" * (-len(data) % 4))
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return decoded.decode("utf-8", errors="replace")

    def _strip_html(self, html_body: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", html_body)
        return self._normalize_text(html.unescape(without_tags))

    def _normalize_text(self, text: str) -> str:
        squashed = re.sub(r"\r\n?", "\n", text)
        squashed = re.sub(r"[ \t]+", " ", squashed)
        squashed = re.sub(r"\n{3,}", "\n\n", squashed)
        return squashed.strip()

    def _truncate_text(self, text: str) -> str:
        if len(text) <= self.settings.max_body_chars:
            return text
        truncated = text[: self.settings.max_body_chars].rsplit(" ", maxsplit=1)[0]
        return f"{truncated}\n\n[truncated]"

    def _internal_date_to_iso(self, internal_date: str | None) -> str:
        if not internal_date:
            return ""
        timestamp = int(internal_date) / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()

    def _stored_token_scopes(self, token_path: Path) -> set[str]:
        if not token_path.exists():
            return set()

        try:
            payload = json.loads(token_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return set()

        scopes = payload.get("scopes", [])
        if isinstance(scopes, str):
            return {scope for scope in scopes.split() if scope}
        if isinstance(scopes, list):
            return {scope for scope in scopes if isinstance(scope, str)}
        return set()

    def _requested_scopes_are_covered(self, stored_scopes: set[str]) -> bool:
        if not stored_scopes:
            return False
        return set(self.scopes).issubset(stored_scopes)
