"""Background alert checker for running instances."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import mysql.connector

from .docker_utils import get_container_name, get_resource_usage

logger = logging.getLogger("alert_checker")

CHECK_INTERVAL = 60  # seconds
DEDUP_MINUTES = 10  # don't create duplicate alerts within this window

CPU_THRESHOLD = 90.0  # percent
MEMORY_THRESHOLD_PCT = 90.0  # percent of limit


def _has_recent_alert(cursor, instance_id: str, alert_type: str) -> bool:
    """Check if an unresolved alert of this type exists within the dedup window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=DEDUP_MINUTES)).isoformat()
    cursor.execute(
        "SELECT 1 FROM alerts WHERE instance_id = %s AND alert_type = %s "
        "AND created_at > %s AND resolved_at IS NULL LIMIT 1",
        (instance_id, alert_type, cutoff),
    )
    row = cursor.fetchone()
    return row is not None


def _create_alert(
    cursor,
    instance_id: str | None,
    alert_type: str,
    severity: str,
    message: str,
) -> None:
    """Insert a new alert if no recent duplicate exists."""
    if instance_id and _has_recent_alert(cursor, instance_id, alert_type):
        return
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO alerts (id, instance_id, alert_type, severity, message, is_read, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 0, %s)",
        (uuid4().hex[:16], instance_id, alert_type, severity, message, now),
    )


def _check_once(db_config: dict) -> int:
    """Run all alert checks. Returns number of alerts created."""
    conn = mysql.connector.connect(**db_config)
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, product, install_state FROM instances WHERE install_state = 'running'"
        )
        rows = cursor.fetchall()

        alert_count = 0

        for row in rows:
            instance_id = row["id"]
            name = row["name"]
            product = row["product"]
            container = get_container_name(instance_id, product)

            usage = get_resource_usage(container)

            # Check: container down (install_state=running but no stats)
            if usage["cpu_percent"] is None and usage["mem_used_mb"] is None:
                if not _has_recent_alert(cursor, instance_id, "container_down"):
                    _create_alert(
                        cursor, instance_id, "container_down", "critical",
                        f"Container for '{name}' is not responding but instance state is 'running'.",
                    )
                    alert_count += 1
                continue  # skip other checks if container is down

            # Check: high CPU
            cpu = usage.get("cpu_percent")
            if cpu is not None and cpu > CPU_THRESHOLD:
                if not _has_recent_alert(cursor, instance_id, "cpu_high"):
                    _create_alert(
                        cursor, instance_id, "cpu_high", "warning",
                        f"'{name}' CPU usage is {cpu:.1f}% (threshold: {CPU_THRESHOLD}%).",
                    )
                    alert_count += 1

            # Check: high memory
            mem_used = usage.get("mem_used_mb")
            mem_total = usage.get("mem_total_mb")
            if mem_used is not None and mem_total is not None and mem_total > 0:
                mem_pct = (mem_used / mem_total) * 100
                if mem_pct > MEMORY_THRESHOLD_PCT:
                    if not _has_recent_alert(cursor, instance_id, "memory_high"):
                        _create_alert(
                            cursor, instance_id, "memory_high", "warning",
                            f"'{name}' memory usage is {mem_pct:.0f}% ({mem_used}MB / {mem_total}MB).",
                        )
                        alert_count += 1

        cursor.close()
        return alert_count
    except Exception as e:
        logger.error("Alert check failed: %s", e)
        return 0
    finally:
        conn.close()


async def alert_check_loop(db_config: dict) -> None:
    """Main alert check loop, runs forever."""
    logger.info("Alert checker started (interval=%ds, dedup=%dmin)", CHECK_INTERVAL, DEDUP_MINUTES)
    while True:
        try:
            count = await asyncio.to_thread(_check_once, db_config)
            if count > 0:
                logger.info("Created %d new alert(s)", count)
        except Exception as e:
            logger.error("Alert checker error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)
