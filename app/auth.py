"""
auth.py — JWT-based authentication and role-based access control.

Roles
-----
  admin   Full access: view, export CSV, upload Excel, manage users.
  user    View + export CSV.  No upload, no user management.
  viewer  Read-only.  No export, no upload, no user management.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt as _bcrypt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import User, get_db

ALGORITHM = "HS256"
TOKEN_HOURS = 8
VALID_ROLES = {"admin", "user", "viewer"}


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _load_or_generate_secret() -> str:
    if settings.secret_key:
        return settings.secret_key

    if settings.allow_local_secret_file and settings.secret_file_path.exists():
        stored = settings.secret_file_path.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    if settings.is_production:
        raise RuntimeError(
            "SRWB auth secret is missing. Set SRWB_SECRET_KEY or provide a secure secret file before starting production."
        )

    key = secrets.token_urlsafe(48)
    if settings.allow_local_secret_file:
        settings.secret_file_path.parent.mkdir(parents=True, exist_ok=True)
        settings.secret_file_path.write_text(key, encoding="utf-8")
    return key


SECRET_KEY: str = _load_or_generate_secret()


def create_access_token(username: str, role: str, full_name: str | None = None) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_HOURS)
    payload = {
        "sub": username,
        "role": role,
        "full_name": full_name or "",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


_bearer = HTTPBearer(auto_error=False)

_AUTH_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated — please log in.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise _AUTH_EXC
    try:
        payload = _decode_token(credentials.credentials)
        username = payload.get("sub")
        if not username:
            raise _AUTH_EXC
    except JWTError:
        raise _AUTH_EXC

    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise _AUTH_EXC
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user


async def require_export(user: User = Depends(get_current_user)) -> User:
    if user.role == "viewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Export access requires User or Admin role.",
        )
    return user


def ensure_default_admin(db: Session) -> None:
    if db.query(User).count() == 0:
        password = secrets.token_urlsafe(12)
        admin = User(
            username="admin",
            password_hash=hash_password(password),
            role="admin",
            created_by="system",
        )
        db.add(admin)
        db.commit()
        print(
            "\n"
            "╔══════════════════════════════════════════════════════════╗\n"
            "║          SRWB Dashboard — First-Run Setup                ║\n"
            "╠══════════════════════════════════════════════════════════╣\n"
            "║  A default admin account has been created.               ║\n"
            "║                                                          ║\n"
            f"║  Username : admin                                        ║\n"
            f"║  Password : {password:<46} ║\n"
            "║                                                          ║\n"
            "║  *** CHANGE THIS PASSWORD IMMEDIATELY AFTER LOGIN ***    ║\n"
            "║  This message will NOT appear again.                     ║\n"
            "╚══════════════════════════════════════════════════════════╝\n"
        )
