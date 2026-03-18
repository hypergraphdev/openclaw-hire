from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

SECRET_KEY = os.getenv("SECRET_KEY", "openclaw-hire-dev-secret-key-change-in-production")
_ITERATIONS = 260_000  # PBKDF2-SHA256, same count as Django default


# ── Password hashing (PBKDF2-SHA256, stdlib only) ────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${base64.b64encode(dk).decode()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        _algo, iters_str, salt, hash_b64 = stored.split("$")
        expected = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), int(iters_str))
        actual = base64.b64decode(hash_b64)
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


# ── JWT (HS256, stdlib only) ──────────────────────────────────────────────────

def _b64url_enc(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_dec(s: str) -> bytes:
    pad = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def _sign(header_b64: str, payload_b64: str) -> str:
    msg = f"{header_b64}.{payload_b64}".encode()
    digest = hmac.new(SECRET_KEY.encode(), msg, hashlib.sha256).digest()
    return _b64url_enc(digest)


def create_access_token(user_id: str) -> str:
    expire = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    header = _b64url_enc(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_enc(json.dumps({"sub": user_id, "exp": expire}).encode())
    sig = _sign(header, payload)
    return f"{header}.{payload}.{sig}"


def decode_token(token: str) -> str | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        if not hmac.compare_digest(sig, _sign(header, payload)):
            return None
        data = json.loads(_b64url_dec(payload))
        if datetime.fromisoformat(data["exp"]) < datetime.now(timezone.utc):
            return None
        return data.get("sub")
    except Exception:
        return None
