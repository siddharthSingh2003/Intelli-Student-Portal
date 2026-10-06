"""Password check and access tokens (JWT, HS256). No database access here."""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from shared.config import settings

ALGORITHM = "HS256"
ROLES = ("student", "admin")


def verify_password(password: str, stored: Optional[str]) -> bool:
    # constant-time comparison; an unknown user (stored=None) never matches
    return stored is not None and hmac.compare_digest(password.encode(), stored.encode())


def create_token(subject: str, role: str = "student") -> tuple[str, int]:
    """Returns (token, lifetime in seconds). `sub` is the student_id or admin username."""
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=settings.jwt_expire_minutes)
    token = jwt.encode({"sub": subject, "role": role, "iat": now, "exp": now + ttl}, settings.jwt_secret,
                       algorithm=ALGORITHM)
    return token, int(ttl.total_seconds())


def decode_token(token: str) -> Optional[dict]:
    """{"sub", "role"} of a valid token, or None if it is invalid or expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM],
                             options={"require": ["sub", "role", "exp"]})
    except jwt.PyJWTError:
        return None
    return {"sub": payload["sub"], "role": payload["role"]} if payload["role"] in ROLES else None
