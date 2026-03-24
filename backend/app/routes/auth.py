from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import mysql.connector

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
def register(payload: RegisterRequest, db=Depends(get_db)) -> TokenResponse:
    user_id = f"user_{uuid4().hex[:12]}"
    now = _utc_now()
    pw_hash = hash_password(payload.password)
    is_admin = 1 if payload.email.lower() == ADMIN_EMAIL else 0
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空。")

    # Check name uniqueness
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE name = %s", (name,))
    existing = cursor.fetchone()
    cursor.close()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该用户名已被使用，请换一个。建议使用企业邮箱用户名。",
        )

    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "INSERT INTO users (id, name, email, company_name, password_hash, is_admin, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, name, payload.email.lower(), payload.company_name, pw_hash, is_admin, now),
        )
        cursor.close()
    except mysql.connector.IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    token = create_access_token(user_id)
    return TokenResponse(access_token=token, user=_row_to_user(row))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db=Depends(get_db)) -> TokenResponse:
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (payload.email.lower(),))
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    pw_hash = row["password_hash"]
    if not pw_hash or not verify_password(payload.password, pw_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    # Keep admin flag in sync for designated admin email
    if payload.email.lower() == ADMIN_EMAIL and not row["is_admin"]:
        cursor = db.cursor()
        cursor.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (row["id"],))
        cursor.close()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (row["id"],))
        row = cursor.fetchone()
        cursor.close()

    token = create_access_token(row["id"])
    return TokenResponse(access_token=token, user=_row_to_user(row))


@router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    return UserResponse(**{k: current_user[k] for k in ("id", "name", "email", "company_name", "is_admin", "created_at")})
