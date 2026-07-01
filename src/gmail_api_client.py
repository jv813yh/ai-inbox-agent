#!/usr/bin/env python3
"""Gmail API client for server-local ai-inbox-agent runs.

Uses an existing Hermes-managed OAuth token file. This avoids storing Gmail app
passwords in the project and works with the `learning` account token.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    subject: str
    from_addr: str
    date: str
    body: str
    snippet: str = ""

    @property
    def email_meta(self) -> dict[str, str]:
        return {
            "message_id": self.id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "from": self.from_addr,
            "date": self.date,
        }


class GmailApiClient:
    """Small Gmail API wrapper for unread-message polling and mark-read."""

    def __init__(self, token_path: str | Path):
        self.token_path = Path(token_path).expanduser()
        self.service = self._build_service()

    def _build_service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not self.token_path.is_file():
            raise FileNotFoundError(f"Google token file not found: {self.token_path}")
        creds = Credentials.from_authorized_user_file(
            str(self.token_path),
            scopes=["https://www.googleapis.com/auth/gmail.modify"],
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def search_unread(self, query: str, *, max_results: int = 5) -> list[GmailMessage]:
        response = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = response.get("messages", []) or []
        return [self.get_message(m["id"]) for m in messages]

    def get_message(self, message_id: str) -> GmailMessage:
        raw = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h.get("name", "").lower(): h.get("value", "") for h in raw.get("payload", {}).get("headers", [])}
        date = headers.get("date", "")
        if date:
            try:
                date = parsedate_to_datetime(date).isoformat()
            except Exception:
                pass
        return GmailMessage(
            id=raw.get("id", message_id),
            thread_id=raw.get("threadId", ""),
            subject=headers.get("subject", ""),
            from_addr=headers.get("from", ""),
            date=date,
            body=self._extract_body(raw.get("payload", {})),
            snippet=raw.get("snippet", ""),
        )

    def mark_read(self, message_ids: Iterable[str]) -> None:
        for message_id in message_ids:
            (
                self.service.users()
                .messages()
                .modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]})
                .execute()
            )

    def add_label(self, message_ids: Iterable[str], label_id: str) -> None:
        for message_id in message_ids:
            (
                self.service.users()
                .messages()
                .modify(userId="me", id=message_id, body={"addLabelIds": [label_id]})
                .execute()
            )

    @classmethod
    def _extract_body(cls, payload: dict[str, Any]) -> str:
        plain_parts: list[str] = []
        html_parts: list[str] = []

        def walk(part: dict[str, Any]) -> None:
            mime_type = part.get("mimeType", "")
            body_data = part.get("body", {}).get("data")
            if body_data:
                decoded = cls._decode_body(body_data)
                if mime_type == "text/plain":
                    plain_parts.append(decoded)
                elif mime_type == "text/html":
                    html_parts.append(decoded)
            for child in part.get("parts", []) or []:
                walk(child)

        walk(payload)
        if plain_parts:
            return "\n".join(plain_parts).strip()
        if html_parts:
            return cls._html_to_text("\n".join(html_parts))
        return ""

    @staticmethod
    def _decode_body(data: str) -> str:
        padding = "=" * (-len(data) % 4)
        raw = base64.urlsafe_b64decode((data + padding).encode("ascii"))
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _html_to_text(value: str) -> str:
        # Lightweight fallback to avoid requiring BeautifulSoup in unit tests.
        value = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', r' \1 ', value, flags=re.I)
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        return " ".join(value.split())


# Imported late to keep module import cheap, but needed by _html_to_text.
import re
