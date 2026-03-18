from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from ..database import get_connection

INSTALL_STEPS: dict[str, list[tuple[str, str]]] = {
    "openclaw": [
        ("pulling", "Cloning openclaw/openclaw from GitHub and pulling Docker images..."),
        ("configuring", "Writing Docker Compose configuration and environment files..."),
        ("starting", "Starting OpenClaw containers and initializing runtime..."),
        ("running", "OpenClaw is running. All services healthy."),
    ],
    "zylos": [
        ("pulling", "Cloning zylos-ai/zylos-core from GitHub and pulling Docker images..."),
        ("configuring", "Writing Docker environment configuration and plugin manifests..."),
        ("starting", "Starting Zylos Core services and agent pipeline..."),
        ("running", "Zylos Core is running. Pipeline ready to receive tasks."),
    ],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add_install_event(conn, instance_id: str, state: str, message: str) -> None:
    conn.execute(
        "INSERT INTO install_events (instance_id, state, message, created_at) VALUES (?, ?, ?, ?)",
        (instance_id, state, message, _utc_now()),
    )
    conn.commit()


def _run_install(instance_id: str, product: str) -> None:
    steps = INSTALL_STEPS.get(product, INSTALL_STEPS["openclaw"])

    for state, message in steps:
        with get_connection() as conn:
            row = conn.execute("SELECT install_state FROM instances WHERE id = ?", (instance_id,)).fetchone()
            if row is None or row["install_state"] == "failed":
                return
            conn.execute(
                "UPDATE instances SET install_state = ?, updated_at = ? WHERE id = ?",
                (state, _utc_now(), instance_id),
            )
            _add_install_event(conn, instance_id, state, message)

        # Simulate realistic install timing
        delay = 3 if state == "pulling" else 2
        time.sleep(delay)


def trigger_install(instance_id: str, product: str) -> None:
    """Kick off the install in a background daemon thread."""
    threading.Thread(
        target=_run_install,
        args=(instance_id, product),
        daemon=True,
    ).start()
