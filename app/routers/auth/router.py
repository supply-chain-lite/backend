import hashlib
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.database import get_db
from app.routers.auth.schemas import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter()


def _hash_password(password: str) -> str:
    return hashlib.sha256((password + settings.secret_key).encode()).hexdigest()


@router.post("/register", response_model=MessageResponse)
def register(
    body: RegisterRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    password_hash = _hash_password(body.password)
    try:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (body.username, password_hash),
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")
    return MessageResponse(message="User registered successfully")


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: sqlite3.Connection = Depends(get_db),
):
    password_hash = _hash_password(body.password)
    row = db.execute(
        "SELECT id FROM users WHERE username = ? AND password_hash = ?",
        (body.username, password_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Placeholder token — replace with real JWT in production
    token = hashlib.sha256(f"{row['id']}:{settings.secret_key}".encode()).hexdigest()
    return TokenResponse(access_token=token)
