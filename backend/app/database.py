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
    """Read a value from server_settings table. Returns default if table doesn't exist yet."""
    try:
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT value FROM server_settings WHERE `key` = %s", (key,))
            row = cursor.fetchone()
            cursor.close()
            return row["value"] if row else default
        finally:
            conn.close()
    except Exception:
        return default


def get_user_setting(user_id: str, key: str, default: str = "") -> str:
    """Read a user-level setting. Falls back to global server_settings, then default."""
    try:
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT value FROM user_settings WHERE user_id = %s AND `key` = %s", (user_id, key))
            row = cursor.fetchone()
            cursor.close()
            if row and row["value"]:
                return row["value"]
        finally:
            conn.close()
    except Exception:
        pass
    return get_setting(key, default)


def set_user_setting(user_id: str, key: str, value: str) -> None:
    """Upsert a user-level setting."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_settings (user_id, `key`, value, updated_at) VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value), updated_at = VALUES(updated_at)",
            (user_id, key, value, now),
        )
        cursor.close()
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
    """Return runtime directory path. In Docker, set RUNTIME_ROOT=/app/runtime."""
    if "runtime_root" not in _config_cache:
        explicit = os.getenv("RUNTIME_ROOT", "")
        if explicit:
            _config_cache["runtime_root"] = explicit
        else:
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
    """Create all tables if they don't exist (idempotent). Safe for fresh installs."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) NOT NULL DEFAULT '',
                email VARCHAR(255) NOT NULL UNIQUE,
                company_name VARCHAR(255) DEFAULT NULL,
                password_hash VARCHAR(512) DEFAULT NULL,
                is_admin TINYINT NOT NULL DEFAULT 0,
                last_login_at VARCHAR(64) DEFAULT NULL,
                created_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS instances (
                id VARCHAR(64) PRIMARY KEY,
                owner_id VARCHAR(64) NOT NULL,
                name VARCHAR(255) NOT NULL DEFAULT '',
                product VARCHAR(64) NOT NULL DEFAULT 'openclaw',
                repo_url VARCHAR(512) DEFAULT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                install_state VARCHAR(32) NOT NULL DEFAULT 'pending',
                compose_project VARCHAR(128) DEFAULT NULL,
                compose_file VARCHAR(512) DEFAULT NULL,
                runtime_dir VARCHAR(512) DEFAULT NULL,
                web_console_url VARCHAR(512) DEFAULT NULL,
                web_console_port INT DEFAULT NULL,
                http_port INT DEFAULT NULL,
                telegram_bot_token VARCHAR(512) DEFAULT NULL,
                agent_name VARCHAR(255) DEFAULT NULL,
                org_id VARCHAR(128) DEFAULT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS install_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                instance_id VARCHAR(64) NOT NULL,
                state VARCHAR(32) NOT NULL,
                message TEXT,
                created_at VARCHAR(64) NOT NULL,
                INDEX idx_instance (instance_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS instance_configs (
                instance_id VARCHAR(64) PRIMARY KEY,
                telegram_bot_token VARCHAR(512) DEFAULT NULL,
                plugin_name VARCHAR(128) DEFAULT NULL,
                hub_url VARCHAR(512) DEFAULT NULL,
                org_id VARCHAR(128) DEFAULT NULL,
                org_token VARCHAR(512) DEFAULT NULL,
                allow_group TINYINT DEFAULT 1,
                allow_dm TINYINT DEFAULT 1,
                agent_name VARCHAR(255) DEFAULT NULL,
                configured_at VARCHAR(64) DEFAULT NULL,
                updated_at VARCHAR(64) DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_settings (
                `key` VARCHAR(128) PRIMARY KEY,
                value TEXT,
                updated_at VARCHAR(64) DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS org_secrets (
                org_id VARCHAR(128) PRIMARY KEY,
                org_secret VARCHAR(512) DEFAULT NULL,
                org_name VARCHAR(255) DEFAULT NULL,
                created_at VARCHAR(64) DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id VARCHAR(64) PRIMARY KEY,
                instance_id VARCHAR(64) NOT NULL,
                alert_type VARCHAR(64) NOT NULL,
                severity VARCHAR(32) NOT NULL DEFAULT 'warning',
                message TEXT,
                is_read TINYINT NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL,
                INDEX idx_instance (instance_id),
                INDEX idx_unread (is_read, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS instance_metrics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                instance_id VARCHAR(64) NOT NULL,
                cpu_percent FLOAT DEFAULT 0,
                mem_used_mb FLOAT DEFAULT 0,
                mem_total_mb FLOAT DEFAULT 0,
                claude_running TINYINT DEFAULT 0,
                claude_mem_mb FLOAT DEFAULT 0,
                collected_at VARCHAR(64) NOT NULL,
                INDEX idx_instance_time (instance_id, collected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(255) NOT NULL DEFAULT '',
                role VARCHAR(128) DEFAULT NULL,
                user_id VARCHAR(64) DEFAULT NULL,
                stack VARCHAR(64) DEFAULT NULL,
                repo_url VARCHAR(512) DEFAULT NULL,
                current_state VARCHAR(32) NOT NULL DEFAULT 'pending',
                template_id VARCHAR(64) DEFAULT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_status_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                employee_id VARCHAR(64) NOT NULL,
                state VARCHAR(32) NOT NULL,
                message TEXT,
                created_at VARCHAR(64) NOT NULL,
                INDEX idx_employee (employee_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # ── Thread Quality Control ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thread_tasks (
                id VARCHAR(64) PRIMARY KEY,
                thread_id VARCHAR(255) NOT NULL,
                org_id VARCHAR(255) NOT NULL,
                assigned_to VARCHAR(255) DEFAULT NULL,
                assigned_by VARCHAR(255) DEFAULT NULL,
                title VARCHAR(512) NOT NULL,
                description TEXT,
                acceptance_criteria TEXT,
                depth VARCHAR(32) DEFAULT 'thorough',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                quality_score FLOAT DEFAULT NULL,
                quality_feedback TEXT,
                revision_count INT DEFAULT 0,
                max_revisions INT DEFAULT 2,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                INDEX idx_thread (thread_id),
                INDEX idx_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thread_qc_config (
                thread_id VARCHAR(255) PRIMARY KEY,
                org_id VARCHAR(255) NOT NULL,
                enabled TINYINT NOT NULL DEFAULT 1,
                min_quality_score FLOAT DEFAULT 0.6,
                auto_revision TINYINT DEFAULT 1,
                max_revisions INT DEFAULT 2,
                evaluator_api_key VARCHAR(512) DEFAULT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # ── User Settings (per-user API keys etc.) ──
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id VARCHAR(64) NOT NULL,
                `key` VARCHAR(128) NOT NULL,
                value TEXT,
                updated_at VARCHAR(64) DEFAULT NULL,
                PRIMARY KEY (user_id, `key`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Migrations
        _safe_add_column(cursor, "users", "last_login_at", "VARCHAR(64) DEFAULT NULL")

        cursor.close()
    finally:
        conn.close()
