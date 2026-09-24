"""
routers/users.py

Authentication and user-management endpoints.

Public (no token required)
  POST  /api/auth/login                  — obtain a JWT token

Authenticated (any role)
  GET   /api/auth/me                     — current user info
  POST  /api/auth/change-password        — change own password

Admin only
  GET   /api/admin/users                 — list all users
  POST  /api/admin/users                 — create a user
  PUT   /api/admin/users/{id}            — update role / active status
  POST  /api/admin/users/{id}/reset-password  — set new password for any user
  DELETE /api/admin/users/{id}           — delete a user (cannot delete self)
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from app.core.limiter import limiter as _limiter
from sqlalchemy.orm import Session

import secrets

from app.auth import (
    VALID_ROLES,
    create_access_token,
    get_current_user,
    require_admin,
    hash_password,
    verify_password,
)
from app.core.config import settings
from app.database import ActivityLog, OrgProfile, UploadLog, User, get_db
from app.services.audit_log import log_event

# ── Two separate routers so auth and admin have distinct prefixes ──
auth_router  = APIRouter(prefix="/api/auth",  tags=["Auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["Admin"])

# ── Schemas ───────────────────────────────────────────────────
class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    username:     str
    role:         str
    full_name:    Optional[str] = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password:     str

    @field_validator("new_password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("New password must be at least 8 characters.")
        return v


class UserOut(BaseModel):
    id:         int
    username:   str
    full_name:  Optional[str] = None
    role:       str
    is_active:  bool
    created_at: Optional[datetime]
    created_by: Optional[str]
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CreateUserIn(BaseModel):
    username:  str
    full_name: Optional[str] = None
    password:  str
    role:      str = "user"

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v

    @field_validator("password")
    @classmethod
    def _pw_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v

    @field_validator("username")
    @classmethod
    def _uname(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Username must be at least 2 characters.")
        return v


class UpdateUserIn(BaseModel):
    full_name: Optional[str] = None
    role:      Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return v


class ResetPasswordIn(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


# ══════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════

@auth_router.post("/login", response_model=TokenOut)
@_limiter.limit("10/minute")
def login(request: Request, payload: LoginIn, db: Session = Depends(get_db)):
    """
    Authenticate with username + password.
    Returns a JWT access token valid for 8 hours.
    Rate-limited to 10 attempts per minute per IP.
    """
    user = (
        db.query(User)
        .filter(User.username == payload.username)
        .first()
    )

    # Verify existence, password, and active status in one place —
    # identical error message prevents username enumeration.
    if (
        not user
        or not verify_password(payload.password, user.password_hash)
        or not user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    user.last_login = datetime.utcnow()
    db.commit()
    ip = request.client.host if request.client else None
    log_event(db, user.username, "login", f"Logged in as {user.role}", ip_address=ip)
    token = create_access_token(user.username, user.role, user.full_name)
    return TokenOut(
        access_token=token,
        username=user.username,
        role=user.role,
        full_name=user.full_name,
    )


@auth_router.post("/dev-preview-token", response_model=TokenOut)
def dev_preview_token(request: Request, db: Session = Depends(get_db)):
    """
    DEV-ONLY local preview login. Lets the headless preview/QA browser render
    authenticated pages WITHOUT anyone typing a password. Hard-gated:

      * Returns 404 when the app runs in production (SRWB_ENV=prod/production).
      * Accepts ONLY same-machine (loopback) requests — remote callers get 403.

    It authenticates a dedicated, clearly-named ``__preview__`` account so the
    activity is obvious in audit logs and the account is trivially removable.
    Do NOT run the app with a development env on a publicly reachable host while
    this route exists.
    """
    if settings.is_production:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    client = (request.client.host if request.client else "") or ""
    if client not in {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Local preview only.")

    user = db.query(User).filter(User.username == "__preview__").first()
    if not user:
        user = User(
            username="__preview__",
            password_hash=hash_password(secrets.token_urlsafe(24)),  # unusable / random
            role="admin",
            full_name="Preview (local QA)",
            created_by="dev-preview",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token(user.username, user.role, user.full_name)
    return TokenOut(access_token=token, username=user.username,
                    role=user.role, full_name=user.full_name)


@auth_router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user


@auth_router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change own password.  Requires the correct current password.
    Returns 204 No Content on success.
    """
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()


# ══════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS
# ══════════════════════════════════════════════════════════════

@admin_router.get("/users", response_model=List[UserOut])
def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all user accounts.  Admin only."""
    return db.query(User).order_by(User.username).all()


@admin_router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: CreateUserIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new user account.  Admin only."""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(409, f"Username '{payload.username}' is already taken.")

    user = User(
        username=payload.username,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        created_by=current_user.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, current_user.username, "user_created", f"Created user '{payload.username}' with role '{payload.role}'")
    return user


@admin_router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UpdateUserIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a user's role or active status.  Admin only."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, f"User {user_id} not found.")

    # Prevent an admin from demoting or deactivating themselves
    if user.id == current_user.id:
        if payload.role is not None and payload.role != "admin":
            raise HTTPException(400, "You cannot change your own role.")
        if payload.is_active is False:
            raise HTTPException(400, "You cannot deactivate your own account.")

    old_role   = user.role
    old_active = user.is_active
    if payload.full_name  is not None: user.full_name  = payload.full_name
    if payload.role      is not None: user.role      = payload.role
    if payload.is_active is not None: user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    if payload.role is not None and payload.role != old_role:
        log_event(db, current_user.username, "role_changed",
                  f"Changed '{user.username}' role: {old_role} → {payload.role}")
    if payload.is_active is not None and payload.is_active != old_active:
        action = "user_activated" if payload.is_active else "user_deactivated"
        log_event(db, current_user.username, action, f"User '{user.username}'")
    return user


@admin_router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: int,
    payload: ResetPasswordIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Set a new password for any user without knowing the current password.
    Admin only.  Returns 204 No Content.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, f"User {user_id} not found.")

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    log_event(db, current_user.username, "password_reset", f"Reset password for '{user.username}'")


@admin_router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a user account.  Admin only.
    An admin cannot delete their own account.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, f"User {user_id} not found.")
    if user.id == current_user.id:
        raise HTTPException(400, "You cannot delete your own account.")

    username_deleted = user.username
    db.delete(user)
    db.commit()
    log_event(db, current_user.username, "user_deleted", f"Deleted user '{username_deleted}'")


# ══════════════════════════════════════════════════════════════
# ADMIN — SYSTEM INFO, ACTIVITY LOG, ORG PROFILE
# ══════════════════════════════════════════════════════════════

import os as _os
from app.core.config import settings as _settings


@admin_router.get("/system")
def system_info(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """System diagnostics — DB stats, upload summary, session."""
    from sqlalchemy import func, text as sa_text
    from app.database import Record, engine as _engine

    # DB file size
    db_path = _settings.database_url.replace("sqlite:///", "")
    try:
        size_mb = round(_os.path.getsize(db_path) / (1024 * 1024), 2)
    except OSError:
        size_mb = 0

    record_count = db.query(func.count(Record.id)).scalar() or 0
    zones   = db.query(func.count(func.distinct(Record.zone))).scalar()   or 0
    schemes = db.query(func.count(func.distinct(Record.scheme))).scalar() or 0

    # Upload history summary
    total_uploads = db.query(func.count(UploadLog.id)).scalar() or 0
    last_upload   = (db.query(UploadLog)
                     .order_by(UploadLog.logged_at.desc())
                     .first())

    return {
        "database": {
            "size_mb":  size_mb,
            "records":  record_count,
            "zones":    zones,
            "schemes":  schemes,
            "last_backup": None,
        },
        "uploads": {
            "total_uploads": total_uploads,
            "last_upload": {
                "by": last_upload.uploaded_by,
                "at": last_upload.logged_at.isoformat() if last_upload.logged_at else None,
                "file": last_upload.filename,
            } if last_upload else None,
        },
    }


@admin_router.get("/activity")
def activity_log(
    limit: int = 100,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Most recent audit activity events."""
    rows = (db.query(ActivityLog)
            .order_by(ActivityLog.logged_at.desc())
            .limit(limit)
            .all())
    return [
        {
            "id":         r.id,
            "username":   r.username,
            "action":     r.action,
            "detail":     r.detail,
            "ip_address": r.ip_address,
            "logged_at":  r.logged_at.isoformat() if r.logged_at else None,
        }
        for r in rows
    ]


class OrgProfileIn(BaseModel):
    org_name:           Optional[str] = None
    short_name:         Optional[str] = None
    registration_no:    Optional[str] = None
    regulator:          Optional[str] = None
    country:            Optional[str] = None
    reporting_currency: Optional[str] = None
    service_area_km2:   Optional[float] = None
    population_served:  Optional[int]   = None
    contact_email:      Optional[str] = None
    contact_phone:      Optional[str] = None
    website:            Optional[str] = None


def _org_to_dict(o: OrgProfile) -> dict:
    return {
        "org_name":           o.org_name,
        "short_name":         o.short_name,
        "registration_no":    o.registration_no,
        "regulator":          o.regulator,
        "country":            o.country,
        "reporting_currency": o.reporting_currency,
        "service_area_km2":   o.service_area_km2,
        "population_served":  o.population_served,
        "contact_email":      o.contact_email,
        "contact_phone":      o.contact_phone,
        "website":            o.website,
        "updated_at":         o.updated_at.isoformat() if o.updated_at else None,
    }


@admin_router.get("/org-profile")
def get_org_profile(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the singleton organisation profile, creating defaults if absent."""
    profile = db.query(OrgProfile).filter(OrgProfile.id == 1).first()
    if not profile:
        profile = OrgProfile(id=1)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return _org_to_dict(profile)


@admin_router.put("/org-profile")
def update_org_profile(
    payload: OrgProfileIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update the organisation profile."""
    profile = db.query(OrgProfile).filter(OrgProfile.id == 1).first()
    if not profile:
        profile = OrgProfile(id=1)
        db.add(profile)

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(profile, field, value)
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    log_event(db, current_user.username, "org_profile_updated", "Updated organisation profile")
    return _org_to_dict(profile)