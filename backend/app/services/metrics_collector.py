"""Background metrics collector for running instances."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone, timedelta

from .docker_utils import get_container_name, get_resource_usage, get_claude_info

logger = logging.getLogger("metrics_collector")

COLLECT_INTERVAL = 60  # seconds
RETENTION_DAYS = 7


def _collect_once(db_path: str) -> int:
    """Collect metrics for all running instances. Returns count collected."""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, product FROM instances WHERE install_state = 'running'"
        ).fetchall()

        now = datetime.now(timezone.utc).isoformat()
        count = 0

        for row in rows:
            instance_id = row["id"]
            product = row["product"]
            container = get_container_name(instance_id, product)

            usage = get_resource_usage(container)
            claude = get_claude_info(container)

            if usage["cpu_percent"] is None and not claude["running"]:
                continue  # container probably not running

            conn.execute(
                """INSERT INTO instance_metrics
                   (instance_id, cpu_percent, mem_used_mb, mem_total_mb,
                    claude_running, claude_mem_mb, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    instance_id,
                    usage.get("cpu_percent"),
                    usage.get("mem_used_mb"),
                    usage.get("mem_total_mb"),
                    1 if claude.get("running") else 0,
                    claude.get("memory_mb"),
                    now,
                ),
            )
            count += 1

        # Cleanup old data
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        conn.execute("DELETE FROM instance_metrics WHERE collected_at < ?", (cutoff,))

        conn.commit()
        return count
    except Exception as e:
        logger.error("Metrics collection failed: %s", e)
        return 0
    finally:
        conn.close()


async def collect_loop(db_path: str) -> None:
    """Main collection loop, runs forever."""
    logger.info("Metrics collector started (interval=%ds, retention=%dd)", COLLECT_INTERVAL, RETENTION_DAYS)
    while True:
        try:
            count = await asyncio.to_thread(_collect_once, db_path)
            if count > 0:
                logger.debug("Collected metrics for %d instances", count)
        except Exception as e:
            logger.error("Metrics collector error: %s", e)
        await asyncio.sleep(COLLECT_INTERVAL)
