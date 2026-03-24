from __future__ import annotations

import os
import mysql.connector
from mysql.connector import pooling

ADMIN_EMAIL = "web8stars@gmail.com"

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "openclaw_hire"),
    "user": os.getenv("DB_USER", "openclaw"),
    "password": os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
    "autocommit": True,
}

# Connection pool for thread safety
_pool = pooling.MySQLConnectionPool(pool_name="hire_pool", pool_size=10, **DB_CONFIG)


def get_connection():
    """Get a connection from the pool with dict cursor support."""
    conn = _pool.get_connection()
    return conn


def execute_query(conn, sql, params=None):
    """Execute a query and return the cursor. Caller must close cursor after use."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params or ())
    return cursor


def get_setting(key: str, default: str = "") -> str:
    """Read a value from server_settings table."""
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT value FROM server_settings WHERE `key` = %s", (key,))
        row = cursor.fetchone()
        cursor.close()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    """Upsert a value in server_settings table."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO server_settings (`key`, value, updated_at) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value), updated_at = VALUES(updated_at)",
            (key, value, now),
        )
        cursor.close()
    finally:
        conn.close()


def init_db() -> None:
    """No-op for MySQL — tables are already created in MySQL.
    Keep the function so main.py startup doesn't break."""
    pass
