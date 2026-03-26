"""Tests for auth_service: password hashing and JWT tokens."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services.auth_service import (
    _b64url_dec,
    _b64url_enc,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


# ── Password hashing ──────────────────────────────────────────────────────────


class TestHashPassword:
    def test_format(self):
        h = hash_password("secret")
        parts = h.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert parts[1] == "260000"

    def test_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # different salt each time

    def test_verify_correct(self):
        h = hash_password("mypass")
        assert verify_password("mypass", h) is True

    def test_verify_wrong(self):
        h = hash_password("mypass")
        assert verify_password("wrong", h) is False

    def test_verify_empty(self):
        h = hash_password("test")
        assert verify_password("", h) is False

    def test_verify_malformed_hash(self):
        assert verify_password("any", "not-a-valid-hash") is False
        assert verify_password("any", "") is False

    def test_unicode_password(self):
        h = hash_password("密码测试123")
        assert verify_password("密码测试123", h) is True
        assert verify_password("密码测试124", h) is False


# ── Base64URL ─────────────────────────────────────────────────────────────────


class TestBase64Url:
    def test_roundtrip(self):
        data = b"hello world"
        assert _b64url_dec(_b64url_enc(data)) == data

    def test_no_padding(self):
        encoded = _b64url_enc(b"test")
        assert "=" not in encoded

    def test_url_safe(self):
        # bytes that produce + and / in standard base64
        data = bytes(range(256))
        encoded = _b64url_enc(data)
        assert "+" not in encoded
        assert "/" not in encoded


# ── JWT ───────────────────────────────────────────────────────────────────────


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token("user_123")
        assert decode_token(token) == "user_123"

    def test_token_format(self):
        token = create_access_token("user_abc")
        parts = token.split(".")
        assert len(parts) == 3
        # header should be valid JSON
        header = json.loads(_b64url_dec(parts[0]))
        assert header == {"alg": "HS256", "typ": "JWT"}

    def test_payload_contains_sub_and_exp(self):
        token = create_access_token("user_xyz")
        payload = json.loads(_b64url_dec(token.split(".")[1]))
        assert payload["sub"] == "user_xyz"
        assert "exp" in payload

    def test_tampered_payload_rejected(self):
        token = create_access_token("user_real")
        parts = token.split(".")
        # tamper with payload
        fake_payload = _b64url_enc(json.dumps({"sub": "user_hacker", "exp": "2099-01-01T00:00:00+00:00"}).encode())
        tampered = f"{parts[0]}.{fake_payload}.{parts[2]}"
        assert decode_token(tampered) is None

    def test_expired_token_rejected(self):
        # Create a token that expired 1 second ago
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        header = _b64url_enc(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = _b64url_enc(json.dumps({"sub": "user_old", "exp": past}).encode())
        from app.services.auth_service import _sign
        sig = _sign(header, payload)
        expired_token = f"{header}.{payload}.{sig}"
        assert decode_token(expired_token) is None

    def test_malformed_tokens(self):
        assert decode_token("") is None
        assert decode_token("not.a.jwt.token") is None
        assert decode_token("one_part_only") is None
        assert decode_token("two.parts") is None

    def test_wrong_secret_rejected(self):
        token = create_access_token("user_ok")
        # Modify signature
        parts = token.split(".")
        bad_token = f"{parts[0]}.{parts[1]}.BADSIGNATURE"
        assert decode_token(bad_token) is None
