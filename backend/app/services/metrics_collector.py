"""Background metrics collector for running instances."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import mysql.connector

from .docker_utils import get_container_name, get_resource_usage, get_claude_info

logger = logging.getLogger("metrics_collector")

COLLECT_INTERVAL = 60  # seconds
RETENTION_DAYS = 7


def _collect_once(db_config: dict) -> int:
    """Collect metrics for all running instances. Returns count collected."""
    conn = mysql.connector.connect(**db_config)
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, product FROM instances WHERE install_state = 'running'"
        )
        rows = cursor.fetchall()

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

            cursor.execute(
                """INSERT INTO instance_metrics
                   (instance_id, cpu_percent, mem_used_mb, mem_total_mb,
                    claude_running, claude_mem_mb, collected_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
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
        cursor.execute("DELETE FROM instance_metrics WHERE collected_at < %s", (cutoff,))

        cursor.close()
        return count
    except Exception as e:
        logger.error("Metrics collection failed: %s", e)
        return 0
    finally:
        conn.close()


async def collect_loop(db_config: dict) -> None:
    """Main collection loop, runs forever."""
    logger.info("Metrics collector started (interval=%ds, retention=%dd)", COLLECT_INTERVAL, RETENTION_DAYS)
    while True:
        try:
            count = await asyncio.to_thread(_collect_once, db_config)
            if count > 0:
                logger.debug("Collected metrics for %d instances", count)
        except Exception as e:
            logger.error("Metrics collector error: %s", e)
        await asyncio.sleep(COLLECT_INTERVAL)
