"""API endpoint tests for auth routes using FastAPI TestClient."""

import uuid

import pytest
from fastapi.testclient import TestClient

# Import conditionally — needs real DB or proper mock
try:
    from app.main import app
    from app.database import get_connection
    _conn = get_connection()
    _cur = _conn.cursor(dictionary=True)
    _cur.execute("SELECT 1 AS ok")
    _row = _cur.fetchone()
    _cur.close()
    _conn.close()
    HAS_DB = isinstance(_row, dict) and _row.get("ok") == 1
except Exception:
    HAS_DB = False

pytestmark = pytest.mark.skipif(not HAS_DB, reason="Real MySQL not available")


@pytest.fixture
def client():
    return TestClient(app)


def _unique_email():
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


def _unique_name():
    return f"TestUser_{uuid.uuid4().hex[:6]}"


class TestRegister:
    def test_register_success(self, client):
        email = _unique_email()
        name = _unique_name()
        r = client.post("/api/auth/register", json={
            "name": name, "email": email, "password": "testpass123"
        })
        assert r.status_code == 201
        data = r.json()
        assert "access_token" in data
        assert data["user"]["email"] == email
        assert data["user"]["is_admin"] is False

        # Cleanup
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        cur.close()
        conn.close()

    def test_register_duplicate_email(self, client):
        email = _unique_email()
        name1 = _unique_name()
        name2 = _unique_name()
        r1 = client.post("/api/auth/register", json={
            "name": name1, "email": email, "password": "testpass123"
        })
        assert r1.status_code == 201

        r2 = client.post("/api/auth/register", json={
            "name": name2, "email": email, "password": "testpass123"
        })
        assert r2.status_code == 409

        # Cleanup
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        cur.close()
        conn.close()

    def test_register_short_password(self, client):
        r = client.post("/api/auth/register", json={
            "name": _unique_name(), "email": _unique_email(), "password": "short"
        })
        assert r.status_code == 422  # validation error

    def test_register_empty_name(self, client):
        r = client.post("/api/auth/register", json={
            "name": "  ", "email": _unique_email(), "password": "testpass123"
        })
        assert r.status_code == 422

    def test_register_invalid_email(self, client):
        r = client.post("/api/auth/register", json={
            "name": _unique_name(), "email": "not-an-email", "password": "testpass123"
        })
        assert r.status_code == 422


class TestLogin:
    def test_login_success(self, client):
        email = _unique_email()
        name = _unique_name()
        # Register first
        client.post("/api/auth/register", json={
            "name": name, "email": email, "password": "mypassword123"
        })

        r = client.post("/api/auth/login", json={
            "email": email, "password": "mypassword123"
        })
        assert r.status_code == 200
        assert "access_token" in r.json()

        # Cleanup
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        cur.close()
        conn.close()

    def test_login_wrong_password(self, client):
        email = _unique_email()
        name = _unique_name()
        client.post("/api/auth/register", json={
            "name": name, "email": email, "password": "correct123"
        })

        r = client.post("/api/auth/login", json={
            "email": email, "password": "wrong123"
        })
        assert r.status_code == 401

        # Cleanup
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        cur.close()
        conn.close()

    def test_login_nonexistent_user(self, client):
        r = client.post("/api/auth/login", json={
            "email": "nobody@example.com", "password": "anything123"
        })
        assert r.status_code == 401


class TestMe:
    def test_me_with_valid_token(self, client):
        email = _unique_email()
        name = _unique_name()
        reg = client.post("/api/auth/register", json={
            "name": name, "email": email, "password": "testpass123"
        })
        token = reg.json()["access_token"]

        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["email"] == email

        # Cleanup
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE email = %s", (email,))
        conn.commit()
        cur.close()
        conn.close()

    def test_me_without_token(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_with_bad_token(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer fake.token.here"})
        assert r.status_code == 401


class TestHealthAndCatalog:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_catalog(self, client):
        # Catalog doesn't require auth
        r = client.get("/api/catalog")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        ids = {p["id"] for p in data}
        assert "openclaw" in ids
        assert "zylos" in ids
