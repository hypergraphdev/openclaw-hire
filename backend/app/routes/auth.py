from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from ..database import get_connection
from ..deps import get_current_user, get_db
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from ..services.auth_service import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ADMIN_EMAIL = "web8stars@gmail.com"


def _row_to_user(row) -> UserResponse:
    return UserResponse(**{k: row[k] for k in ("id", "name", "email", "company_name", "is_admin", "created_at")})


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: sqlite3.Connection = Depends(get_db)) -> TokenResponse:
    user_id = f"user_{uuid4().hex[:12]}"
    now = _utc_now()
    pw_hash = hash_password(payload.password)
    is_admin = 1 if payload.email.lower() == ADMIN_EMAIL else 0
    try:
        db.execute(
            "INSERT INTO users (id, name, email, company_name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, payload.name.strip(), payload.email.lower(), payload.company_name, pw_hash, is_admin, now),
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    token = create_access_token(user_id)
    return TokenResponse(access_token=token, user=_row_to_user(row))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: sqlite3.Connection = Depends(get_db)) -> TokenResponse:
    row = db.execute("SELECT * FROM users WHERE email = ?", (payload.email.lower(),)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    pw_hash = row["password_hash"]
    if not pw_hash or not verify_password(payload.password, pw_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    # Keep admin flag in sync for designated admin email
    if payload.email.lower() == ADMIN_EMAIL and not row["is_admin"]:
        db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row["id"],))
        db.commit()
        row = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()

    token = create_access_token(row["id"])
    return TokenResponse(access_token=token, user=_row_to_user(row))


@router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    return UserResponse(**{k: current_user[k] for k in ("id", "name", "email", "company_name", "is_admin", "created_at")})
