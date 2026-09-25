"""Test helpers for users and scope grants (access is deny-by-default since revision 0002)."""
from __future__ import annotations


def add_user(database, auth, username: str, role: str = "user", grants: dict | None = None,
             functions: tuple = (), full_name: str | None = None) -> dict:
    """Create a user with unit grants ({unit_code: role}) and duties; return auth headers."""
    from app.platform.models import UserFunction, UserOrgRole

    db = database.SessionLocal()
    try:
        u = database.User(username=username, password_hash=auth.hash_password("x"), role=role,
                          full_name=full_name)
        db.add(u)
        db.flush()
        for unit, scope_role in (grants or {}).items():
            db.add(UserOrgRole(user_id=u.id, org_unit_code=unit, role=scope_role, granted_by="test"))
        for f in functions:
            db.add(UserFunction(user_id=u.id, function=f, granted_by="test"))
        db.commit()
    finally:
        db.close()
    return {"Authorization": f"Bearer {auth.create_access_token(username, role)}"}


def grant(database, username: str, unit: str = "org", role: str = "viewer") -> None:
    from app.platform.models import UserOrgRole

    db = database.SessionLocal()
    try:
        u = db.query(database.User).filter_by(username=username).one()
        db.add(UserOrgRole(user_id=u.id, org_unit_code=unit, role=role, granted_by="test"))
        db.commit()
    finally:
        db.close()
