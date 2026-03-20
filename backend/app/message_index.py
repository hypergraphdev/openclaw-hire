"""Message indexing for full-text search across DM and thread messages."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path

from .database import get_connection, get_setting, set_setting


def _ensure_tables() -> None:
    """Create message_index and FTS tables if they don't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_index (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                channel_name TEXT,
                sender_id TEXT,
                sender_name TEXT,
                content TEXT,
                mentions TEXT,
                created_at INTEGER
            )
        """)
        # Check if FTS table exists
        fts_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='message_fts'"
        ).fetchone()
        if not fts_exists:
            conn.execute("""
                CREATE VIRTUAL TABLE message_fts USING fts5(
                    content, sender_name, channel_name, mentions,
                    content='message_index', content_rowid='rowid'
                )
            """)
            # Populate FTS from existing data (if any)
            conn.execute("""
                INSERT INTO message_fts(message_fts) VALUES('rebuild')
            """)
        conn.commit()


def _hub_get(hub_url: str, token: str, path: str) -> dict | list:
    """Simple Hub GET request."""
    req = urllib.request.Request(
        f"{hub_url}{path}",
        headers={"Authorization": f"Bearer {token}", "Origin": "https://www.ucai.net"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _extract_mentions(content: str) -> list[str]:
    """Extract @mentions from message content."""
    return re.findall(r'@([\w\-\u4e00-\u9fff]+)', content or "")


def sync_messages(user_id: str, org_id: str, tokens: list[tuple[str, str]], hub_url: str) -> int:
    """Sync messages from Hub into local index.

    Args:
        user_id: User ID
        org_id: Organization ID
        tokens: List of (token, bot_name) tuples for all user's bots + admin bot
        hub_url: Hub URL

    Returns:
        Number of new messages indexed
    """
    _ensure_tables()

    setting_key = f"msg_sync_ts_{user_id}_{org_id[:8]}"
    last_sync = int(get_setting(setting_key, "0") or "0")
    now = int(time.time() * 1000)
    new_count = 0

    with get_connection() as conn:
        for token, bot_name in tokens:
            try:
                # Use inbox API for incremental sync
                since = last_sync if last_sync > 0 else (now - 30 * 24 * 3600 * 1000)  # 30 days back
                messages = _hub_get(hub_url, token, f"/api/inbox?since={since}")
                if not isinstance(messages, list):
                    messages = messages.get("messages", messages.get("items", []))

                for msg in messages:
                    msg_id = msg.get("id", "")
                    if not msg_id:
                        continue
                    # Check if already indexed
                    if conn.execute("SELECT 1 FROM message_index WHERE id = ?", (msg_id,)).fetchone():
                        continue

                    content = msg.get("content", "")
                    sender_name = msg.get("sender_name", "")
                    sender_id = msg.get("sender_id", "")
                    channel_id = msg.get("channel_id", "")
                    created_at = msg.get("created_at", 0)
                    mentions = json.dumps(_extract_mentions(content))

                    # Determine channel name (the other party's name for DM)
                    channel_name = ""
                    if sender_name and sender_name != bot_name:
                        channel_name = sender_name
                    else:
                        # Try to get recipient from message
                        channel_name = msg.get("recipient_name", bot_name)

                    conn.execute("""
                        INSERT OR IGNORE INTO message_index
                        (id, org_id, channel_type, channel_id, channel_name, sender_id, sender_name, content, mentions, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (msg_id, org_id, "dm", channel_id, channel_name, sender_id, sender_name, content, mentions, created_at))
                    new_count += 1

            except Exception:
                continue  # Skip failed tokens

            # Also sync thread messages
            try:
                threads_result = _hub_get(hub_url, token, "/api/threads?status=active&limit=50")
                thread_list = threads_result if isinstance(threads_result, list) else threads_result.get("threads", threads_result.get("items", []))

                for thread in thread_list:
                    thread_id = thread.get("id", "")
                    topic = thread.get("topic", "")
                    if not thread_id:
                        continue

                    try:
                        msgs_result = _hub_get(hub_url, token, f"/api/threads/{thread_id}/messages?limit=100")
                        thread_msgs = msgs_result if isinstance(msgs_result, list) else msgs_result.get("messages", msgs_result.get("items", []))

                        for msg in thread_msgs:
                            msg_id = msg.get("id", "")
                            if not msg_id:
                                continue
                            if conn.execute("SELECT 1 FROM message_index WHERE id = ?", (msg_id,)).fetchone():
                                continue

                            content = msg.get("content", "")
                            sender_id = msg.get("sender_id", "")
                            sender_name = msg.get("sender_name", "")
                            created_at = msg.get("created_at", 0)
                            mentions = json.dumps(_extract_mentions(content))

                            conn.execute("""
                                INSERT OR IGNORE INTO message_index
                                (id, org_id, channel_type, channel_id, channel_name, sender_id, sender_name, content, mentions, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (msg_id, org_id, "thread", thread_id, topic, sender_id, sender_name, content, mentions, created_at))
                            new_count += 1
                    except Exception:
                        continue
            except Exception:
                continue

        # Rebuild FTS index
        if new_count > 0:
            try:
                conn.execute("INSERT INTO message_fts(message_fts) VALUES('rebuild')")
            except Exception:
                pass

        conn.commit()

    # Update sync timestamp
    set_setting(setting_key, str(now))
    return new_count


def search_messages(
    org_id: str,
    query: str = "",
    in_channel: str = "",
    from_sender: str = "",
    to_name: str = "",
    limit: int = 50,
) -> list[dict]:
    """Search indexed messages using FTS5.

    Args:
        org_id: Organization ID
        query: Full-text search query
        in_channel: Filter by channel_name (DM partner or thread topic)
        from_sender: Filter by sender_name
        to_name: Filter by recipient (channel_name) or @mention

    Returns:
        List of matching messages with context
    """
    _ensure_tables()

    conditions = ["m.org_id = ?"]
    params: list = [org_id]

    # Build FTS match expression
    fts_parts = []
    if query:
        # Escape special FTS characters
        safe_q = query.replace('"', '""')
        fts_parts.append(f'content: "{safe_q}"')

    if in_channel:
        conditions.append("m.channel_name = ?")
        params.append(in_channel)

    if from_sender:
        conditions.append("m.sender_name = ?")
        params.append(from_sender)

    if to_name:
        # Search in channel_name (DM recipient) or mentions
        conditions.append("(m.channel_name = ? OR m.mentions LIKE ?)")
        params.append(to_name)
        params.append(f'%"{to_name}"%')

    where = " AND ".join(conditions)

    with get_connection() as conn:
        if fts_parts:
            fts_match = " AND ".join(fts_parts)
            sql = f"""
                SELECT m.* FROM message_index m
                JOIN message_fts f ON m.rowid = f.rowid
                WHERE {where} AND message_fts MATCH ?
                ORDER BY m.created_at DESC
                LIMIT ?
            """
            params.append(fts_match)
            params.append(limit)
        else:
            sql = f"""
                SELECT m.* FROM message_index m
                WHERE {where}
                ORDER BY m.created_at DESC
                LIMIT ?
            """
            params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
