"""Global test fixtures — mock MySQL connection pool when DB is unavailable."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Load .env file if it exists (same dir as app expects)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Try real DB first. Only mock if connection fails.
_REAL_DB = False
try:
    import mysql.connector
    _test_conn = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "openclaw"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "openclaw_hire"),
        connect_timeout=3,
    )
    _test_conn.close()
    _REAL_DB = True
except Exception:
    _REAL_DB = False

if not _REAL_DB:
    # No real DB — mock the connection pool so unit tests can import app modules.
    _mock_pool = MagicMock()
    _mock_conn = MagicMock()
    _mock_cursor = MagicMock()
    _mock_conn.cursor.return_value = _mock_cursor
    _mock_pool.get_connection.return_value = _mock_conn
    patch("mysql.connector.pooling.MySQLConnectionPool", return_value=_mock_pool).start()
