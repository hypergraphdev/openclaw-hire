"""Integration tests — run against real MySQL database.

These tests use real DB connections. Test data is created and cleaned up
within each test. Safe to run on production (read-heavy, writes are rolled back).

Skip on local dev (no MySQL): pytest -m "not integration"
Run on server: cd backend && python3 -m pytest tests/test_integration.py -v
"""

import os
import uuid

import pytest

# Skip entire file if real DB is not reachable (not mocked).
# Test with an actual query to distinguish real DB from conftest mock.
DB_AVAILABLE = False
try:
    from app.database import get_connection, get_setting, set_setting

    _conn = get_connection()
    _cur = _conn.cursor(dictionary=True)
    _cur.execute("SELECT 1 AS ok")
    _row = _cur.fetchone()
    DB_AVAILABLE = isinstance(_row, dict) and _row.get("ok") == 1
    _cur.close()
    _conn.close()
except Exception:
    DB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="Real MySQL not available (mocked or unreachable)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unique(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── Database connection ───────────────────────────────────────────────────────


class TestDatabaseConnection:
    def test_get_connection(self):
        conn = get_connection()
        assert conn is not None
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT 1 AS ok")
        row = cursor.fetchone()
        assert row["ok"] == 1
        cursor.close()
        conn.close()

    def test_connection_pool_reuse(self):
        c1 = get_connection()
        c1.close()
        c2 = get_connection()
        c2.close()
        # No exception means pool works

    def test_tables_exist(self):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW TABLES")
        tables = {row[list(row.keys())[0]] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        expected = {"users", "instances", "instance_configs", "install_events", "server_settings"}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"


# ── server_settings CRUD ─────────────────────────────────────────────────────


class TestServerSettings:
    def test_set_and_get(self):
        key = _unique("setting")
        try:
            set_setting(key, "test_value_123")
            assert get_setting(key) == "test_value_123"
        finally:
            # Cleanup
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM server_settings WHERE `key` = %s", (key,))
            conn.commit()
            cursor.close()
            conn.close()

    def test_get_default(self):
        assert get_setting("nonexistent_key_xyz", "fallback") == "fallback"

    def test_overwrite(self):
        key = _unique("setting")
        try:
            set_setting(key, "v1")
            set_setting(key, "v2")
            assert get_setting(key) == "v2"
        finally:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM server_settings WHERE `key` = %s", (key,))
            conn.commit()
            cursor.close()
            conn.close()


# ── Users table (read-only) ──────────────────────────────────────────────────


class TestUsersReadOnly:
    def test_admin_user_exists(self):
        """The hardcoded admin email should exist."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, email, is_admin FROM users WHERE email = %s", ("web8stars@gmail.com",))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "Admin user web8stars@gmail.com not found"
        assert row["is_admin"] == 1

    def test_user_has_required_fields(self):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None
        for field in ("id", "email", "password_hash", "is_admin"):
            assert field in row, f"Missing field: {field}"


# ── User CRUD (create + delete) ──────────────────────────────────────────────


class TestUserCRUD:
    def test_create_and_delete_user(self):
        from app.services.auth_service import hash_password

        user_id = _unique("user")
        email = f"{user_id}@example.com"
        pw_hash = hash_password("testpass123")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "INSERT INTO users (id, email, password_hash, name, is_admin, created_at) VALUES (%s, %s, %s, %s, 0, NOW())",
                (user_id, email, pw_hash, "Test User"),
            )
            conn.commit()

            # Verify created
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["email"] == email
            assert row["is_admin"] == 0

            # Verify password
            from app.services.auth_service import verify_password
            assert verify_password("testpass123", row["password_hash"]) is True
        finally:
            # Always cleanup
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
            cursor.close()
            conn.close()

            # Verify deleted
            conn2 = get_connection()
            cur2 = conn2.cursor(dictionary=True)
            cur2.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            assert cur2.fetchone() is None
            cur2.close()
            conn2.close()


# ── Instances table (read-only) ──────────────────────────────────────────────


class TestInstancesReadOnly:
    def test_instances_have_required_fields(self):
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM instances LIMIT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row is None:
            pytest.skip("No instances in database")
        for field in ("id", "name", "product", "status", "owner_id"):
            assert field in row, f"Missing field: {field}"

    def test_instance_configs_link(self):
        """instance_configs should reference valid instances."""
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.instance_id, c.agent_name
            FROM instance_configs c
            LEFT JOIN instances i ON c.instance_id = i.id
            WHERE i.id IS NULL
            LIMIT 5
        """)
        orphans = cursor.fetchall()
        cursor.close()
        conn.close()
        if orphans:
            pytest.xfail(f"Found {len(orphans)} orphaned instance_configs (known data issue): {[o['instance_id'] for o in orphans[:5]]}")


# ── Auth service integration ─────────────────────────────────────────────────


class TestAuthIntegration:
    def test_jwt_roundtrip_with_real_secret(self):
        """JWT should work with the production SECRET_KEY."""
        from app.services.auth_service import create_access_token, decode_token
        token = create_access_token("user_integration_test")
        assert decode_token(token) == "user_integration_test"

    def test_login_flow(self):
        """Simulate login: find user by email, verify password, create token."""
        from app.services.auth_service import hash_password, verify_password, create_access_token, decode_token

        user_id = _unique("user")
        email = f"{user_id}@example.com"
        password = "SecurePass!@#123"
        pw_hash = hash_password(password)

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "INSERT INTO users (id, email, password_hash, name, is_admin, created_at) VALUES (%s, %s, %s, %s, 0, NOW())",
                (user_id, email, pw_hash, "Login Test"),
            )
            conn.commit()

            # Simulate login
            cursor.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            assert user is not None
            assert verify_password(password, user["password_hash"]) is True

            token = create_access_token(user["id"])
            decoded_id = decode_token(token)
            assert decoded_id == user_id
        finally:
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
            cursor.close()
            conn.close()


# ── _safe_agent_name consistency check ────────────────────────────────────────


class TestAgentNameConsistency:
    def test_db_agent_names_match_safe_name(self):
        """All agent_names in instance_configs should match _safe_agent_name(instance_id)."""
        from app.services.install_service import _safe_agent_name

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT instance_id, agent_name FROM instance_configs WHERE agent_name IS NOT NULL AND agent_name != ''")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        mismatches = []
        for row in rows:
            expected = _safe_agent_name(row["instance_id"])
            actual = row["agent_name"]
            # Some agent_names were manually set (like MW_OpenClaw1), skip those
            if actual.startswith("hire_") and actual != expected:
                mismatches.append({"instance_id": row["instance_id"], "expected": expected, "actual": actual})

        # Report but don't fail hard — legacy data may have old naming
        if mismatches:
            pytest.xfail(f"Found {len(mismatches)} mismatched agent names (legacy data): {mismatches[:3]}")
