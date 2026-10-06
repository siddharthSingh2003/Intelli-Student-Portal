"""Authentication and authorisation (M3): password login that issues a JWT carrying a
role, and the dependencies that turn a request into the logged-in user. Nothing else
decides identity (R7). Students see their own records; only admins add documents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from data import credentials
from data.db import one
from shared.config import settings
from shared.security import create_token, decode_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@dataclass
class User:
    id: str                 # student_id or admin username
    role: str               # student | admin

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def student_id(self) -> Optional[str]:
        return self.id if self.role == "student" else None


class LoginRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=32)      # student ID or admin username
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    name: str
    student: Optional[dict] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def token_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[User]:
    """The user of the bearer token; None without one; 401 if it is invalid or expired."""
    if creds is None:
        return None
    claims = decode_token(creds.credentials)
    if claims is None:
        raise _unauthorised("Invalid or expired token. Please log in again.")
    return User(claims["sub"], claims["role"])


def current_user(user: Optional[User] = Depends(token_user),
                 x_student_id: Optional[str] = Header(default=None, alias="X-Student-Id")) -> User:
    if user is not None:
        return user
    if settings.auth_required:
        raise _unauthorised("Not logged in. POST /auth/login first.")
    return User(x_student_id or "", "student")       # legacy contract: identity from the header


def require_admin(user: Optional[User] = Depends(token_user)) -> User:
    if user is None:
        if not settings.auth_required:               # legacy contract: no roles
            return User("legacy", "admin")
        raise _unauthorised("Not logged in. POST /auth/login first.")
    if not user.is_admin:
        raise HTTPException(403, "Only an admin can do this.")
    return user


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    name = req.student_id.strip()
    admin_pw = credentials.get_admin_password(name.lower())
    if admin_pw is not None:
        if not verify_password(req.password, admin_pw):
            raise _unauthorised("Incorrect ID or password.")
        token, expires_in = create_token(name.lower(), "admin")
        return LoginResponse(access_token=token, expires_in=expires_in, role="admin", name=name.lower())
    sid = name.upper()
    if not verify_password(req.password, credentials.get_password(sid)):
        raise _unauthorised("Incorrect ID or password.")
    token, expires_in = create_token(sid, "student")
    student = one("SELECT * FROM students WHERE student_id = ?", (sid,))
    return LoginResponse(access_token=token, expires_in=expires_in, role="student",
                         name=student["full_name"], student=student)


@router.get("/me")
def me(user: User = Depends(current_user)):
    if user.is_admin:
        return {"role": "admin", "name": user.id}
    student = one("SELECT * FROM students WHERE student_id = ?", (user.id.strip().upper(),))
    if student is None:
        raise _unauthorised("The logged-in student no longer exists.")
    return {"role": "student", "name": student["full_name"], "student": student}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, user: Optional[User] = Depends(token_user)):
    if user is None:
        raise _unauthorised("Not logged in.")
    stored = credentials.get_admin_password(user.id) if user.is_admin else credentials.get_password(user.id)
    if not verify_password(req.current_password, stored):
        raise HTTPException(403, "Current password is incorrect.")
    (credentials.set_admin_password if user.is_admin else credentials.set_password)(user.id, req.new_password)
    return {"status": "password_changed"}
