#!/usr/bin/env python3
"""SQLite deduplication/state store for server-local ai-inbox-agent runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class StateStore:
    """Persistent idempotency store for Gmail messages and extracted sources."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_messages (
                    gmail_account TEXT NOT NULL,
                    gmail_message_id TEXT NOT NULL,
                    thread_id TEXT,
                    subject TEXT,
                    from_addr TEXT,
                    processed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (gmail_account, gmail_message_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_sources (
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    note_path TEXT NOT NULL,
                    first_seen_message_id TEXT,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (source_type, source_id)
                )
                """
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def is_message_processed(self, gmail_account: str, gmail_message_id: str) -> bool:
        return self.get_message_status(gmail_account, gmail_message_id) == "processed"

    def get_message_status(self, gmail_account: str, gmail_message_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT status FROM processed_messages
                WHERE gmail_account = ? AND gmail_message_id = ?
                """,
                (gmail_account, gmail_message_id),
            ).fetchone()
        return row[0] if row else None

    def record_message(
        self,
        *,
        gmail_account: str,
        gmail_message_id: str,
        thread_id: str = "",
        subject: str = "",
        from_addr: str = "",
        status: str = "processed",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO processed_messages (
                    gmail_account, gmail_message_id, thread_id, subject,
                    from_addr, processed_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gmail_account, gmail_message_id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    subject = excluded.subject,
                    from_addr = excluded.from_addr,
                    processed_at = excluded.processed_at,
                    status = excluded.status
                """,
                (
                    gmail_account,
                    gmail_message_id,
                    thread_id,
                    subject,
                    from_addr,
                    self._now_iso(),
                    status,
                ),
            )

    def is_source_processed(self, source_type: str, source_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM processed_sources
                WHERE source_type = ? AND source_id = ?
                """,
                (source_type, source_id),
            ).fetchone()
        return row is not None

    def record_source(
        self,
        *,
        source_type: str,
        source_id: str,
        source_url: str,
        note_path: str,
        first_seen_message_id: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO processed_sources (
                    source_type, source_id, source_url, note_path,
                    first_seen_message_id, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, source_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    note_path = excluded.note_path,
                    first_seen_message_id = excluded.first_seen_message_id,
                    processed_at = excluded.processed_at
                """,
                (
                    source_type,
                    source_id,
                    source_url,
                    note_path,
                    first_seen_message_id,
                    self._now_iso(),
                ),
            )

    def get_source_note_path(self, source_type: str, source_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT note_path FROM processed_sources
                WHERE source_type = ? AND source_id = ?
                """,
                (source_type, source_id),
            ).fetchone()
        return row[0] if row else None

    def count_messages(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM processed_messages").fetchone()[0])

    def count_sources(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM processed_sources").fetchone()[0])
