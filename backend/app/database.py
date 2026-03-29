from __future__ import annotations

import os
from pathlib import Path

import mysql.connector
from mysql.connector import pooling

# Load .env file if present (server-side only, never committed to git)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

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


def get_config(key: str, default: str = "") -> str:
    """Read a config value: DB setting > env var > default."""
    db_val = get_setting(key, "")
    if db_val:
        return db_val
    env_val = os.getenv(key.upper().replace(".", "_"), "")
    return env_val or default


# Common config accessors (cached at module level after first call)
_config_cache: dict[str, str] = {}


def site_base_url() -> str:
    if "site_base_url" not in _config_cache:
        _config_cache["site_base_url"] = get_config("site_base_url", "https://www.ucai.net").rstrip("/")
    return _config_cache["site_base_url"]


def hxa_hub_url() -> str:
    if "hxa_hub_url" not in _config_cache:
        _config_cache["hxa_hub_url"] = get_config("hxa_hub_url", "https://www.ucai.net/connect").rstrip("/")
    return _config_cache["hxa_hub_url"]


def runtime_root() -> str:
    if "runtime_root" not in _config_cache:
        home = os.getenv("OPENCLAW_HOME", str(Path(__file__).resolve().parent.parent.parent))
        _config_cache["runtime_root"] = os.path.join(home, "runtime")
    return _config_cache["runtime_root"]


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
        # Migrations
        _safe_add_column(cursor, "users", "last_login_at", "VARCHAR(64) DEFAULT NULL")
        cursor.close()
    finally:
        conn.close()


def _safe_add_column(cursor, table: str, column: str, definition: str) -> None:
    """Add a column if it doesn't exist (idempotent)."""
    cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
    if not cursor.fetchone():
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def init_db() -> None:
    """Ensure new tables exist (idempotent)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS marketplace_installs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                instance_id VARCHAR(64) NOT NULL,
                item_id VARCHAR(64) NOT NULL,
                item_type ENUM('plugin','skill') NOT NULL,
                status ENUM('installing','installed','failed') DEFAULT 'installing',
                install_log MEDIUMTEXT,
                installed_at VARCHAR(64),
                UNIQUE KEY uq_inst_item (instance_id, item_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.close()
    finally:
        conn.close()
