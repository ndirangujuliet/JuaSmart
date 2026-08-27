"""SQLite storage for outgoing SMS attempts."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _database_path():
    return Path(os.getenv("SMS_DB_PATH", "sms_logs.db"))


def _connect():
    path = _database_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    except (OSError, sqlite3.OperationalError):
        # Keep SMS delivery working when a configured Render disk is absent.
        path = Path("sms_logs.db")
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL,
            provider_response TEXT,
            error TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def record_sms(recipient, message, status, provider_response=None, error=None, direction="outgoing"):
    """Persist one SMS event and return its database ID."""
    response_text = (
        json.dumps(provider_response, default=str)
        if provider_response is not None
        else None
    )
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sms_logs
                (direction, recipient, message, status, provider_response, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            ,
            (
                direction,
                recipient,
                message,
                status,
                response_text,
                error,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return cursor.lastrowid


def record_outgoing(recipient, message, status, provider_response=None, error=None):
    return record_sms(recipient, message, status, provider_response, error)


def get_logs(limit=100, direction=None):
    """Return the newest SMS logs first, optionally by direction."""
    with _connect() as connection:
        if direction in {"incoming", "outgoing"}:
            rows = connection.execute(
                "SELECT * FROM sms_logs WHERE direction = ? ORDER BY id DESC LIMIT ?",
                (direction, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM sms_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(row) for row in rows]
