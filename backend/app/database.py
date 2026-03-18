from __future__ import annotations

import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "openclaw_hire.db"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                company_name TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS employees (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                template_id TEXT DEFAULT 'audit-codex-base',
                stack TEXT NOT NULL DEFAULT 'openclaw',
                repo_url TEXT NOT NULL DEFAULT 'https://github.com/openclaw/openclaw',
                brief TEXT,
                telegram_handle TEXT,
                model_config TEXT NOT NULL,
                current_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                telegram_bot_token_placeholder TEXT,
                FOREIGN KEY (owner_id) REFERENCES users (id)
            );

            CREATE TABLE IF NOT EXISTS employee_status_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                state TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees (id)
            );
            """
        )
