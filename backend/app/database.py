from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "openclaw_hire.db"
ADMIN_EMAIL = "web8stars@gmail.com"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                company_name TEXT,
                password_hash TEXT,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS instances (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                product TEXT NOT NULL DEFAULT 'openclaw',
                repo_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                install_state TEXT NOT NULL DEFAULT 'idle',
                compose_project TEXT,
                compose_file TEXT,
                runtime_dir TEXT,
                web_console_port INTEGER,
                web_console_url TEXT,
                http_port INTEGER,
                telegram_bot_token TEXT,
                org_token TEXT,
                agent_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (owner_id) REFERENCES users (id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS install_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT NOT NULL,
                state TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (instance_id) REFERENCES instances (id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS instance_configs (
                instance_id TEXT PRIMARY KEY,
                telegram_bot_token TEXT,
                plugin_name TEXT,
                hub_url TEXT,
                org_id TEXT,
                org_token TEXT,
                agent_name TEXT,
                allow_group INTEGER NOT NULL DEFAULT 1,
                allow_dm INTEGER NOT NULL DEFAULT 1,
                configured_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (instance_id) REFERENCES instances (id)
            )
        """)
        conn.commit()
    _migrate_existing_db()


def _migrate_existing_db() -> None:
    """Add new columns and tables to existing database without data loss."""
    with get_connection() as conn:
        # Add password_hash / is_admin to users if missing
        user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "password_hash" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        if "is_admin" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

        # Keep specific admin account promoted
        conn.execute("UPDATE users SET is_admin = 1 WHERE lower(email) = lower(?)", (ADMIN_EMAIL,))

        # Create instances table from employees if needed
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        if "instances" not in tables:
            conn.execute("""
                CREATE TABLE instances (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    product TEXT NOT NULL DEFAULT 'openclaw',
                    repo_url TEXT NOT NULL DEFAULT 'https://github.com/openclaw/openclaw',
                    status TEXT NOT NULL DEFAULT 'active',
                    install_state TEXT NOT NULL DEFAULT 'idle',
                    agent_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (owner_id) REFERENCES users (id)
                )
            """)
            # Migrate existing employees to instances
            if "employees" in tables:
                conn.execute("""
                    INSERT OR IGNORE INTO instances (id, owner_id, name, product, repo_url, status, install_state, created_at, updated_at)
                    SELECT
                        id,
                        owner_id,
                        name,
                        COALESCE(stack, 'openclaw'),
                        COALESCE(repo_url, 'https://github.com/openclaw/openclaw'),
                        CASE current_state WHEN 'failed' THEN 'failed' ELSE 'active' END,
                        'idle',
                        created_at,
                        updated_at
                    FROM employees
                """)
        else:
            inst_cols = {r[1] for r in conn.execute("PRAGMA table_info(instances)").fetchall()}
            if "install_state" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN install_state TEXT NOT NULL DEFAULT 'idle'")
            if "status" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            if "compose_project" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN compose_project TEXT")
            if "compose_file" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN compose_file TEXT")
            if "runtime_dir" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN runtime_dir TEXT")
            if "web_console_port" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN web_console_port INTEGER")
            if "http_port" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN http_port INTEGER")
            if "web_console_url" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN web_console_url TEXT")
            if "telegram_bot_token" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN telegram_bot_token TEXT")
            if "org_token" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN org_token TEXT")
            if "agent_name" not in inst_cols:
                conn.execute("ALTER TABLE instances ADD COLUMN agent_name TEXT")

        if "install_events" not in tables:
            conn.execute("""
                CREATE TABLE install_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (instance_id) REFERENCES instances (id)
                )
            """)

        if "instance_configs" not in tables:
            conn.execute("""
                CREATE TABLE instance_configs (
                    instance_id TEXT PRIMARY KEY,
                    telegram_bot_token TEXT,
                    plugin_name TEXT,
                    hub_url TEXT,
                    org_id TEXT,
                    org_token TEXT,
                    agent_name TEXT,
                    allow_group INTEGER NOT NULL DEFAULT 1,
                    allow_dm INTEGER NOT NULL DEFAULT 1,
                    configured_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (instance_id) REFERENCES instances (id)
                )
            """)
        else:
            cfg_cols = {r[1] for r in conn.execute("PRAGMA table_info(instance_configs)").fetchall()}
            if "agent_name" not in cfg_cols:
                conn.execute("ALTER TABLE instance_configs ADD COLUMN agent_name TEXT")

        conn.commit()
