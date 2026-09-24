"""
routers for the shared governance foundation — /api/platform/*

Any signed-in user (results limited to their scope):
  GET  /api/platform/me                         account, resolved scope, duties, unread notices
  GET  /api/platform/org-units                  units the user can see
  GET  /api/platform/assignable-users?unit=     people who can own work on a unit (contributor+)
  GET  /api/platform/periods                    reporting periods
  GET  /api/platform/my-work                    my open actions, overdue items and notices
  GET/POST /api/platform/actions                action register / raise an action
  GET/PUT  /api/platform/actions/{id}           detail (history, comments, links) / edit
  POST /api/platform/actions/{id}/transition    start | complete | close | reopen | cancel
  GET/POST /api/platform/links, DELETE /api/platform/links/{id}
  GET/POST /api/platform/comments
  GET  /api/platform/history?type=&id=          audit trail of one record
  GET  /api/platform/notifications, POST .../{id}/read, POST .../read-all

Administrators:
  POST /api/platform/periods/fiscal-year        create a fiscal year's periods
  POST /api/platform/periods/{id}/lock          lock a period
  POST /api/platform/periods/{id}/reopen        reopen with a reason (audited)
  GET  /api/platform/access/users               grants and duties per user
  PUT  /api/platform/access/users/{id}          replace a user's grants and duties (audited)

Administrators and auditors:
  GET  /api/platform/audit                      the audit trail
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import User, get_db
from app.integration.models import OrgUnit
from app.platform import actions as act
from app.platform import audit, entities, links, periods
from app.platform.errors import Forbidden, Invalid, NotFound
from app.platform.models import (
    FUNCTIONS, SCOPE_ROLES, AuditEvent, Notification, Period, UserFunction, UserOrgRole,
)
from app.platform.notifications import notification_dict
from app.platform.scope import ROOT_ORG, Scope, check_unit, get_scope, resolve_scope, unit_names

router = APIRouter(prefix="/api/platform", tags=["Platform"])

# Modules add "my work" sections: fn(db, scope) -> dict merged into /my-work.
MY_WORK_PROVIDERS: list = []


def _admin(scope: Scope) -> None:
    if not scope.is_admin:
        raise Forbidden("Administrator access required.")


# ── me, units, people ───────────────────────────────────────────────────────

@router.get("/me")
def me(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    unread = db.query(Notification).filter(Notification.username == scope.username,
                                           Notification.read_at.is_(None)).count()
    return {**scope.as_dict(), "unread_notifications": unread, "roles": list(SCOPE_ROLES)}


@router.get("/org-units")
def org_units(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    units = db.query(OrgUnit).filter(OrgUnit.is_active.is_(True)).order_by(OrgUnit.code).all()
    by_id = {u.id: u.code for u in units}
    out = [{"code": u.code, "name": u.name, "unit_type": u.unit_type, "parent_code": by_id.get(u.parent_id),
            "role": scope.role_on(u.code)} for u in units if scope.can_see(u.code)]
    if scope.org_wide and not any(u["code"] == ROOT_ORG for u in out):
        out.insert(0, {"code": ROOT_ORG, "name": "Whole organisation", "unit_type": "organisation",
                       "parent_code": None, "role": scope.role_on(ROOT_ORG)})
    return out


@router.post("/org-units/sync")
def sync_org_units(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Add the root and the configured top-level units (zones/regions) if missing."""
    from app.platform.bootstrap import ensure_org_tree
    _admin(scope)
    created = ensure_org_tree(db)
    if created:
        audit.record(db, scope.username, "org_units.sync", "org_unit", ROOT_ORG, after={"created": created})
    db.commit()
    return {"created": created}


@router.get("/assignable-users")
def assignable_users(unit: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require(unit, "contributor", "work on this unit")
    out = []
    for u in db.query(User).filter(User.is_active.is_(True)).order_by(User.username):
        s = resolve_scope(db, u)
        if s.can_see(unit):
            out.append({"username": u.username, "full_name": u.full_name, "role": s.role_on(unit)})
    return out


# ── periods ─────────────────────────────────────────────────────────────────

class FiscalYearIn(BaseModel):
    fiscal_year: int = Field(ge=1990, le=2100)


class ReasonIn(BaseModel):
    reason: Optional[str] = None


@router.get("/periods")
def list_periods(fiscal_year: Optional[int] = None, period_type: Optional[str] = None,
                 scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    q = db.query(Period)
    if fiscal_year:
        q = q.filter(Period.fiscal_year == fiscal_year)
    if period_type:
        q = q.filter(Period.period_type == period_type)
    order = {"year": 0, "quarter": 1, "month": 2}
    rows = sorted(q.all(), key=lambda p: (-p.fiscal_year, order[p.period_type], p.start_date))
    return [periods.period_dict(p) for p in rows]


@router.post("/periods/fiscal-year", status_code=201)
def create_fiscal_year(body: FiscalYearIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not (scope.is_admin or scope.has_function("strategy_manager")):
        raise Forbidden("Administrator or strategy manager access required.")
    created = periods.ensure_fiscal_year(db, body.fiscal_year)
    audit.record(db, scope.username, "period.create_fiscal_year", "fiscal_year", body.fiscal_year,
                 after={"periods": len(created)})
    db.commit()
    return [periods.period_dict(p) for p in created]


@router.post("/periods/{period_id}/lock")
def lock_period(period_id: int, body: ReasonIn = ReasonIn(), scope: Scope = Depends(get_scope),
                db: Session = Depends(get_db)):
    _admin(scope)
    p = periods.lock(db, periods.get(db, period_id), scope.username, body.reason)
    db.commit()
    return periods.period_dict(p)


@router.post("/periods/{period_id}/reopen")
def reopen_period(period_id: int, body: ReasonIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _admin(scope)
    p = periods.reopen(db, periods.get(db, period_id), scope.username, body.reason or "")
    db.commit()
    return periods.period_dict(p)


# ── actions ─────────────────────────────────────────────────────────────────

class ActionIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    owner: str
    org_unit_code: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: str = "medium"
    source_type: Optional[str] = None
    source_id: Optional[str] = None


class ActionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[date] = None
    priority: Optional[str] = None
    progress_note: Optional[str] = None
    reason: Optional[str] = None


class TransitionIn(BaseModel):
    name: str
    note: Optional[str] = None


@router.get("/actions")
def list_actions(status: Optional[str] = None, mine: bool = False, overdue: bool = False, open_only: bool = False,
                 org_unit_code: Optional[str] = None, source_type: Optional[str] = None,
                 source_id: Optional[str] = None, limit: int = Query(500, le=2000),
                 scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    q = act.query(db, scope, status=status, owner=scope.username if mine else None, org_unit_code=org_unit_code,
                  source_type=source_type, source_id=source_id, overdue=overdue, open_only=open_only)
    return [act.action_dict(a, scope) for a in q.limit(limit)]


@router.post("/actions", status_code=201)
def create_action(body: ActionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if body.source_type:
        # Raising an action "from" a record needs sight of that record.
        entities.load(db, scope, body.source_type, body.source_id)
    a = act.create(db, scope, **body.model_dump())
    if body.source_type:
        links.add_link(db, scope, "action", a.id, body.source_type, body.source_id, relation="responds_to",
                       role="viewer")
    db.commit()
    return act.action_dict(a, scope)


@router.get("/actions/{action_id}")
def get_action(action_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = act.get(db, scope, action_id)
    return {**act.action_dict(a, scope), "history": _history(db, "action", a.id),
            "comments": links.comments_for(db, scope, "action", a.id), **links.links_for(db, scope, "action", a.id)}


@router.put("/actions/{action_id}")
def update_action(action_id: int, body: ActionUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    a = act.update(db, scope, action_id, data, reason)
    db.commit()
    return act.action_dict(a, scope)


@router.post("/actions/{action_id}/transition")
def transition_action(action_id: int, body: TransitionIn, scope: Scope = Depends(get_scope),
                      db: Session = Depends(get_db)):
    a = act.transition(db, scope, action_id, body.name, body.note)
    db.commit()
    return act.action_dict(a, scope)


# ── links, comments, history ────────────────────────────────────────────────

class LinkIn(BaseModel):
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relation: str = "related"
    to_version: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=300)


class CommentIn(BaseModel):
    entity_type: str
    entity_id: str
    body: str


@router.get("/links")
def get_links(type: str, id: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return links.links_for(db, scope, type, id)


@router.post("/links", status_code=201)
def create_link(body: LinkIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    link = links.add_link(db, scope, body.from_type, body.from_id, body.to_type, body.to_id,
                          relation=body.relation, to_version=body.to_version, note=body.note)
    db.commit()
    return {"id": link.id}


@router.delete("/links/{link_id}")
def delete_link(link_id: int, reason: Optional[str] = None, scope: Scope = Depends(get_scope),
                db: Session = Depends(get_db)):
    links.remove_link(db, scope, link_id, reason)
    db.commit()
    return {"deleted": link_id}


@router.get("/comments")
def get_comments(type: str, id: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return links.comments_for(db, scope, type, id)


@router.post("/comments", status_code=201)
def create_comment(body: CommentIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = links.add_comment(db, scope, body.entity_type, body.entity_id, body.body)
    db.commit()
    return {"id": c.id}


def _history(db: Session, entity_type: str, entity_id) -> list[dict]:
    rows = (db.query(AuditEvent).filter_by(entity_type=entity_type, entity_id=str(entity_id))
            .order_by(AuditEvent.at, AuditEvent.id))
    return [audit.event_dict(e) for e in rows]


@router.get("/history")
def history(type: str, id: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    entities.load(db, scope, type, id)
    return _history(db, type, id)


@router.get("/audit")
def audit_trail(entity_type: Optional[str] = None, actor: Optional[str] = None, action: Optional[str] = None,
                since: Optional[date] = None, limit: int = Query(200, le=2000),
                scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not (scope.is_admin or scope.has_function("auditor")):
        raise Forbidden("The audit trail is available to administrators and auditors.")
    q = db.query(AuditEvent)
    if entity_type:
        q = q.filter(AuditEvent.entity_type == entity_type)
    if actor:
        q = q.filter(AuditEvent.actor == actor)
    if action:
        q = q.filter(AuditEvent.action.like(f"{action}%"))
    if since:
        q = q.filter(AuditEvent.at >= datetime.combine(since, datetime.min.time()))
    # Private HR records stay out of the general trail; HR officers read them on the records themselves.
    q = q.filter(~AuditEvent.entity_type.in_(PRIVATE_ENTITY_TYPES))
    return [audit.event_dict(e) for e in q.order_by(AuditEvent.id.desc()).limit(limit)]


PRIVATE_ENTITY_TYPES: set[str] = set()


# ── notifications and my work ───────────────────────────────────────────────

@router.get("/notifications")
def list_notifications(unread_only: bool = False, limit: int = Query(100, le=500),
                       scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    q = db.query(Notification).filter(Notification.username == scope.username)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    return [notification_dict(n) for n in q.order_by(Notification.id.desc()).limit(limit)]


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.username != scope.username:
        raise NotFound("Notification not found.")
    n.read_at = n.read_at or datetime.utcnow()
    db.commit()
    return notification_dict(n)


@router.post("/notifications/read-all")
def read_all(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    n = (db.query(Notification).filter(Notification.username == scope.username, Notification.read_at.is_(None))
         .update({Notification.read_at: datetime.utcnow()}))
    db.commit()
    return {"marked": n}


@router.get("/my-work")
def my_work(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    mine = [act.action_dict(a, scope) for a in act.query(db, scope, owner=scope.username, open_only=True)]
    to_verify = [act.action_dict(a, scope) for a in act.query(db, scope, status="completed")
                 if a.owner != scope.username and scope.can(a.org_unit_code, "reviewer")]
    out = {"actions": mine, "actions_to_verify": to_verify,
           "overdue_actions": sum(1 for a in mine if a["overdue"]),
           "notifications": [notification_dict(n) for n in db.query(Notification)
                             .filter(Notification.username == scope.username, Notification.read_at.is_(None))
                             .order_by(Notification.id.desc()).limit(20)]}
    for provider in MY_WORK_PROVIDERS:
        out.update(provider(db, scope))
    return out


# ── access administration ───────────────────────────────────────────────────

class GrantIn(BaseModel):
    org_unit_code: str
    role: str = "viewer"


class AccessIn(BaseModel):
    grants: list[GrantIn] = []
    functions: list[str] = []
    reason: Optional[str] = None


def _access_dict(db: Session, u: User, names: dict[str, str]) -> dict:
    grants = db.query(UserOrgRole).filter(UserOrgRole.user_id == u.id).order_by(UserOrgRole.org_unit_code).all()
    funcs = sorted(f for (f,) in db.query(UserFunction.function).filter(UserFunction.user_id == u.id))
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "account_role": u.role,
            "is_active": u.is_active,
            "grants": [{"org_unit_code": g.org_unit_code, "unit_name": names.get(g.org_unit_code, g.org_unit_code),
                        "role": g.role} for g in grants],
            "functions": funcs}


@router.get("/access/users")
def access_users(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _admin(scope)
    names = unit_names(db)
    return {"users": [_access_dict(db, u, names) for u in db.query(User).order_by(User.username)],
            "roles": list(SCOPE_ROLES), "functions": list(FUNCTIONS)}


@router.put("/access/users/{user_id}")
def set_access(user_id: int, body: AccessIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _admin(scope)
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("User not found.")
    seen = set()
    for g in body.grants:
        if g.role not in SCOPE_ROLES:
            raise Invalid(f"Role must be one of {', '.join(SCOPE_ROLES)}.")
        check_unit(db, g.org_unit_code)
        if g.org_unit_code in seen:
            raise Invalid(f"Unit '{g.org_unit_code}' is listed twice.")
        seen.add(g.org_unit_code)
    bad = set(body.functions) - set(FUNCTIONS)
    if bad:
        raise Invalid(f"Unknown duties: {', '.join(sorted(bad))}.")
    names = unit_names(db)
    before = _access_dict(db, u, names)
    db.query(UserOrgRole).filter(UserOrgRole.user_id == u.id).delete()
    db.query(UserFunction).filter(UserFunction.user_id == u.id).delete()
    for g in body.grants:
        db.add(UserOrgRole(user_id=u.id, org_unit_code=g.org_unit_code, role=g.role, granted_by=scope.username))
    for f in sorted(set(body.functions)):
        db.add(UserFunction(user_id=u.id, function=f, granted_by=scope.username))
    db.flush()
    after = _access_dict(db, u, names)
    audit.record(db, scope.username, "access.update", "user", u.id,
                 before={"grants": before["grants"], "functions": before["functions"]},
                 after={"grants": after["grants"], "functions": after["functions"]}, reason=body.reason)
    db.commit()
    return after
