"""Data-access helpers over the SQLite schema in db.py.

Keeps SQL out of the orchestration code. All timestamps are UTC ISO strings.
"""
from __future__ import annotations

import json
from typing import Optional

from db import get_conn, utc_now_iso
from schemas import ResearchBrief


# --------------------------------------------------------------------------
# Briefs
# --------------------------------------------------------------------------
def seed_briefs(briefs: list[ResearchBrief]) -> int:
    """Insert briefs that aren't already present (dedup by angle_title). Returns count inserted."""
    inserted = 0
    with get_conn() as conn:
        existing = {r["angle_title"] for r in conn.execute("SELECT angle_title FROM research_briefs")}
        for b in briefs:
            if b.angle_title in existing:
                continue
            conn.execute(
                """INSERT INTO research_briefs
                   (well_id, angle_title, angle_summary, supporting_facts,
                    suggested_format, suggested_list_count, evergreen,
                    voice_compatibility_notes, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?, 'available', ?)""",
                (
                    b.well_id, b.angle_title, b.angle_summary,
                    json.dumps([f.model_dump() for f in b.supporting_facts]),
                    b.suggested_format, b.suggested_list_count, int(b.evergreen),
                    b.voice_compatibility_notes, utc_now_iso(),
                ),
            )
            inserted += 1
    return inserted


def recent_brief_titles(days: int = 30) -> list[str]:
    """Angle titles created within the last `days` — for de-duplication."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT angle_title FROM research_briefs WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
    return [r["angle_title"] for r in rows]


def count_available(format_type: Optional[str] = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM research_briefs WHERE status='available'"
    args: tuple = ()
    if format_type:
        sql += " AND suggested_format=?"
        args = (format_type,)
    with get_conn() as conn:
        return conn.execute(sql, args).fetchone()["n"]


def next_available_brief(format_type: str) -> Optional[ResearchBrief]:
    """Oldest available brief for a format, as a ResearchBrief. Carries its db id on ._row_id."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM research_briefs
               WHERE status='available' AND suggested_format=?
               ORDER BY created_at ASC, id ASC LIMIT 1""",
            (format_type,),
        ).fetchone()
    if row is None:
        return None
    brief = _row_to_brief(row)
    return brief


def _row_to_brief(row) -> ResearchBrief:
    facts = json.loads(row["supporting_facts"])
    brief = ResearchBrief(
        well_id=row["well_id"],
        angle_title=row["angle_title"],
        angle_summary=row["angle_summary"],
        supporting_facts=facts,
        suggested_format=row["suggested_format"],
        suggested_list_count=row["suggested_list_count"],
        evergreen=bool(row["evergreen"]),
        voice_compatibility_notes=row["voice_compatibility_notes"] or "",
    )
    # stash the db id for callers without polluting the schema
    object.__setattr__(brief, "_row_id", row["id"])
    return brief


def brief_row_id(brief: ResearchBrief) -> Optional[int]:
    return getattr(brief, "_row_id", None)


def mark_brief_used(brief_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE research_briefs SET status='used', used_at=? WHERE id=?",
            (utc_now_iso(), brief_id),
        )


# --------------------------------------------------------------------------
# Posts
# --------------------------------------------------------------------------
def slot_already_posted(scheduled_at_iso: str) -> bool:
    """True if a post for this exact slot timestamp has already been published."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM posts WHERE scheduled_at=? AND status='posted' LIMIT 1",
            (scheduled_at_iso,),
        ).fetchone()
    return row is not None


def insert_post(brief_id: int, format_type: str, content_json: str,
                image_path: str, scheduled_at_iso: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO posts
               (brief_id, format_type, generated_content, image_path,
                scheduled_at, status, created_at)
               VALUES (?,?,?,?,?, 'ready', ?)""",
            (brief_id, format_type, content_json, image_path, scheduled_at_iso, utc_now_iso()),
        )
        return cur.lastrowid


def mark_post_posted(post_id: int, fb_post_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE posts SET status='posted', fb_post_id=?, posted_at=? WHERE id=?",
            (fb_post_id, utc_now_iso(), post_id),
        )


def mark_post_failed(post_id: int, reason: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE posts SET status='failed', failure_reason=? WHERE id=?",
            (reason[:500], post_id),
        )


# --------------------------------------------------------------------------
# Reels (tracked separately — no brief FK)
# --------------------------------------------------------------------------
def reel_already_posted(scheduled_at_iso: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM reels WHERE scheduled_at=? AND status='posted' LIMIT 1",
            (scheduled_at_iso,),
        ).fetchone()
    return row is not None


def record_reel(scheduled_at_iso: str, theme: str, video_path: str, fb_video_id: str) -> None:
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO reels
               (scheduled_at, theme, video_path, fb_video_id, status, created_at, posted_at)
               VALUES (?,?,?,?, 'posted', ?, ?)""",
            (scheduled_at_iso, theme, video_path, fb_video_id, now, now),
        )
