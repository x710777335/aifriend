"""Small SQLite persistence layer for text messages."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class ChatRepository:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS messages (
               id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL,
               created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        )
        # Migration keeps existing desktop history in an explicit local conversation.
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(messages)")}
        if "conversation_id" not in columns:
            self._connection.execute(
                "ALTER TABLE messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'desktop-local'"
            )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_id ON messages(conversation_id, id)"
        )
        self._connection.commit()

    def add_message(self, role: str, content: str, conversation_id: str = "desktop-local") -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        self._connection.execute(
            "INSERT INTO messages(role, content, conversation_id) VALUES(?, ?, ?)",
            (role, content, conversation_id),
        )
        self._connection.commit()

    def recent_messages(self, limit: int, conversation_id: str = "desktop-local") -> list[dict[str, str]]:
        rows = self._connection.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def close(self) -> None:
        self._connection.close()
