"""SQLite schema and connection helpers.

All timestamps are stored as UTC ISO-8601 strings. Convert at the edges only.
The DB file is created on first connect; init_db() is idempotent.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    well_id TEXT NOT NULL,
    angle_title TEXT NOT NULL,
    angle_summary TEXT NOT NULL,
    supporting_facts TEXT NOT NULL,            -- JSON-encoded list[SupportingFact]
    suggested_format TEXT NOT NULL,
    suggested_list_count INTEGER,
    evergreen INTEGER NOT NULL,
    voice_compatibility_notes TEXT,
    status TEXT NOT NULL DEFAULT 'available',  -- available | used
    created_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_briefs_status_format
    ON research_briefs(status, suggested_format);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id INTEGER NOT NULL,
    format_type TEXT NOT NULL,
    generated_content TEXT NOT NULL,           -- JSON-encoded format payload
    image_path TEXT,
    scheduled_at TIMESTAMP NOT NULL,
    posted_at TIMESTAMP,
    fb_post_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',     -- pending | ready | posted | failed
    failure_reason TEXT,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (brief_id) REFERENCES research_briefs(id)
);
CREATE INDEX IF NOT EXISTS idx_posts_status_schedule
    ON posts(status, scheduled_at);

CREATE TABLE IF NOT EXISTS reels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_at TIMESTAMP NOT NULL,
    theme TEXT,
    hook TEXT,
    video_path TEXT,
    fb_video_id TEXT,
    status TEXT NOT NULL DEFAULT 'posted',
    created_at TIMESTAMP NOT NULL,
    posted_at TIMESTAMP,
    UNIQUE(scheduled_at)
);

CREATE TABLE IF NOT EXISTS performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    measurement_day INTEGER NOT NULL,          -- days since posting (1, 3, 7, ...)
    reach INTEGER,
    reactions INTEGER,
    comments INTEGER,
    shares INTEGER,
    saves INTEGER,
    fetched_at TIMESTAMP NOT NULL,
    FOREIGN KEY (post_id) REFERENCES posts(id),
    UNIQUE(post_id, measurement_day)
);
"""


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the canonical DB timestamp format)."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a connection with Row factory and foreign keys enforced.

    Commits on clean exit, rolls back on exception, always closes.
    """
    config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # No detect_types: timestamps are stored and compared as ISO-8601 strings.
    # PARSE_DECLTYPES would invoke sqlite's converter, which can't parse the
    # 'T'-separated, offset-aware ISO format we use.
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables and indexes if they do not already exist."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Migration: add reels.hook to already-created DBs.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(reels)")}
        if "hook" not in cols:
            conn.execute("ALTER TABLE reels ADD COLUMN hook TEXT")


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {config.SQLITE_PATH}")
