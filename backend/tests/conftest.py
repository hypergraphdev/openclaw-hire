"""Global test fixtures — mock MySQL connection pool at import time."""

import sys
from unittest.mock import MagicMock, patch

# Mock the MySQL connection pool before any app module is imported.
# This prevents install_service and other modules from failing
# when MySQL is not available (local dev / CI environment).

_mock_pool = MagicMock()
_mock_conn = MagicMock()
_mock_cursor = MagicMock()
_mock_conn.cursor.return_value = _mock_cursor
_mock_pool.get_connection.return_value = _mock_conn


def _mock_get_connection():
    return _mock_conn


# Patch at module level before imports
patch("mysql.connector.pooling.MySQLConnectionPool", return_value=_mock_pool).start()

# Also need to handle the case where database.py is already imported
# Force re-creation by patching the module-level pool
if "app.database" in sys.modules:
    sys.modules["app.database"]._pool = _mock_pool
    sys.modules["app.database"].get_connection = _mock_get_connection
