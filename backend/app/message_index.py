"""Message indexing for full-text search across DM and thread messages."""
from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

from .database import get_connection, get_setting, set_setting


def _ensure_tables() -> None:
    """Create message_index table with FULLTEXT index if it doesn't exist."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_index (
                id VARCHAR(255) PRIMARY KEY,
                org_id VARCHAR(255) NOT NULL,
                channel_type VARCHAR(50) NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                channel_name VARCHAR(255),
                sender_id VARCHAR(255),
                sender_name VARCHAR(255),
                content TEXT,
                mentions TEXT,
                created_at BIGINT,
                FULLTEXT idx_msg_ft (content, sender_name, channel_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.close()
    finally:
        conn.close()


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

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
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
                    cursor.execute("SELECT 1 FROM message_index WHERE id = %s", (msg_id,))
                    if cursor.fetchone():
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

                    cursor.execute("""
                        INSERT IGNORE INTO message_index
                        (id, org_id, channel_type, channel_id, channel_name, sender_id, sender_name, content, mentions, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            cursor.execute("SELECT 1 FROM message_index WHERE id = %s", (msg_id,))
                            if cursor.fetchone():
                                continue

                            content = msg.get("content", "")
                            sender_id = msg.get("sender_id", "")
                            sender_name = msg.get("sender_name", "")
                            created_at = msg.get("created_at", 0)
                            mentions = json.dumps(_extract_mentions(content))

                            cursor.execute("""
                                INSERT IGNORE INTO message_index
                                (id, org_id, channel_type, channel_id, channel_name, sender_id, sender_name, content, mentions, created_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (msg_id, org_id, "thread", thread_id, topic, sender_id, sender_name, content, mentions, created_at))
                            new_count += 1
                    except Exception:
                        continue
            except Exception:
                continue

        cursor.close()
    finally:
        conn.close()

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
    """Search indexed messages using MySQL FULLTEXT or LIKE.

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

    conditions = ["m.org_id = %s"]
    params: list = [org_id]

    if query:
        # Use FULLTEXT MATCH for content search
        conditions.append("MATCH(m.content, m.sender_name, m.channel_name) AGAINST(%s IN BOOLEAN MODE)")
        params.append(query)

    if in_channel:
        conditions.append("m.channel_name = %s")
        params.append(in_channel)

    if from_sender:
        conditions.append("m.sender_name = %s")
        params.append(from_sender)

    if to_name:
        # Search in channel_name (DM recipient) or mentions
        conditions.append("(m.channel_name = %s OR m.mentions LIKE %s)")
        params.append(to_name)
        params.append(f'%"{to_name}"%')

    where = " AND ".join(conditions)

    sql = f"""
        SELECT m.* FROM message_index m
        WHERE {where}
        ORDER BY m.created_at DESC
        LIMIT %s
    """
    params.append(limit)

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        return [dict(r) for r in rows]
    finally:
        conn.close()
