"""Seed the fictional demo tenant with people, access and governance records.

    python -m app.demo_seed            add demo users, grants and sample records (idempotent)

Only runs when MADZI_TENANT is ``demo``: it must never touch a real utility's data.
Demo accounts get random passwords, printed once; nothing here is a real person.
Each module adds its own seeding step to ``STEPS``.
"""
from __future__ import annotations

import secrets
import sys
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import model_registry as _models  # noqa: F401
from app.database import SessionLocal, User

DEMO_USERS = [
    # username, full name, account role, {unit: role}, duties
    ("planner", "Pat Planner (demo)", "user", {"org": "approver"}, ("strategy_manager", "report_manager")),
    ("north.ops", "Nia North (demo)", "user", {"north": "contributor"}, ()),
    ("north.mgr", "Noah North (demo)", "user", {"north": "reviewer"}, ()),
    ("south.mgr", "Sade South (demo)", "user", {"south": "approver"}, ()),
    ("auditor", "Ada Auditor (demo)", "viewer", {"org": "viewer"}, ("auditor",)),
    ("board", "Ben Board (demo)", "viewer", {"org": "viewer"}, ()),
]

STEPS: list = []


def _users(db: Session) -> dict[str, str]:
    from app.auth import hash_password
    from app.platform.models import UserFunction, UserOrgRole

    created = {}
    for username, full_name, role, grants, duties in DEMO_USERS:
        if db.query(User).filter_by(username=username).first():
            continue
        password = secrets.token_urlsafe(9)
        u = User(username=username, full_name=full_name, role=role, password_hash=hash_password(password),
                 created_by="demo_seed", must_change_password=False)
        db.add(u)
        db.flush()
        for unit, scope_role in grants.items():
            db.add(UserOrgRole(user_id=u.id, org_unit_code=unit, role=scope_role, granted_by="demo_seed"))
        for duty in duties:
            db.add(UserFunction(user_id=u.id, function=duty, granted_by="demo_seed"))
        created[username] = password
    return created


def _tree(db: Session) -> None:
    from app.integration.models import OrgUnit
    from app.platform.bootstrap import ensure_org_tree

    ensure_org_tree(db)
    db.flush()
    by_code = {u.code: u for u in db.query(OrgUnit)}
    for parent, code, name in (("north", "north.hilltop", "Hilltop"), ("north", "north.riverside", "Riverside"),
                               ("central", "central.market", "Market Town"), ("south", "south.bay", "Bay Area")):
        if code not in by_code and parent in by_code:
            db.add(OrgUnit(code=code, name=name, unit_type="service area", parent_id=by_code[parent].id))
    db.flush()


def _actions(db: Session) -> None:
    from app.platform import actions
    from app.platform.models import Action
    from app.platform.scope import resolve_scope

    if db.query(Action).count():
        return
    admin = db.query(User).filter_by(role="admin").order_by(User.id).first()
    scope = resolve_scope(db, admin)
    today = date.today()
    for title, owner, unit, due, priority in (
        ("Replace faulty bulk meter at Hilltop reservoir", "north.ops", "north.hilltop", today + timedelta(days=21), "high"),
        ("Clear backlog of new-connection quotations", "north.ops", "north", today - timedelta(days=5), "medium"),
        ("Publish the customer service charter", "south.mgr", "south", today + timedelta(days=45), "low"),
    ):
        actions.create(db, scope, title=title, owner=owner, org_unit_code=unit, due_date=due, priority=priority)


STEPS += [_tree, _users, _actions]


def run(db: Session) -> dict[str, str]:
    passwords: dict[str, str] = {}
    for step in STEPS:
        out = step(db)
        if isinstance(out, dict):
            passwords.update(out)
        db.flush()
    db.commit()
    return passwords


def main() -> int:
    from app.core.tenant import tenant
    from app.database import create_tables

    if tenant.key != "demo":
        print(f"Refusing to seed: tenant is '{tenant.key}', not 'demo'.", file=sys.stderr)
        return 1
    create_tables()
    db = SessionLocal()
    try:
        from app.auth import ensure_default_admin
        from app.platform.bootstrap import at_startup
        ensure_default_admin(db)
        at_startup(db)
        passwords = run(db)
    finally:
        db.close()
    if passwords:
        print("Demo accounts created (fictional people; passwords shown once):")
        for user, pw in passwords.items():
            print(f"  {user:<12} {pw}")
    else:
        print("Demo data already present; nothing added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
