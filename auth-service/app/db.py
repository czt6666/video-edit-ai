"""SQLite connection + schema management.

One tiny table (`users`). Connections are opened per-request; SQLite handles
that fine for this low-traffic admin service. WAL mode keeps concurrent reads
from blocking on the occasional write.
"""
from __future__ import annotations

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with row access by column name + FK enforcement."""
    if db_path != ":memory:":
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they do not exist."""
    conn.executescript(SCHEMA)
    # WAL is a no-op for :memory: but harmless.
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    conn.commit()
