"""
Shared action tracker: owned, dated follow-up work raised by any module.

    open ──start──► in_progress ──complete──► completed ──close──► closed
      │                 │                         │
      └────cancel───────┴──cancel──► cancelled    └──reopen──► in_progress (reason)
                                     closed ──reopen──► in_progress (reason)

- Anyone with the contributor role on the unit may raise an action.
- The owner (or a reviewer) starts and completes it; completing needs a note.
- Closing verifies the work and must be done by a reviewer who is not the owner.
- Cancelling, reopening and moving an agreed due date need a reason. All of it is audited.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database import User
from app.platform import audit, entities
from app.platform.errors import Forbidden, Invalid, NotFound
from app.platform.models import ACTION_PRIORITIES, Action
from app.platform.notifications import notify
from app.platform.scope import Scope, check_unit, resolve_scope
from app.platform.workflow import Transition, Workflow

WORKFLOW = Workflow("action", ("open", "in_progress", "completed", "closed", "cancelled"), [
    Transition("start", ("open",), "in_progress", label="Start"),
    Transition("complete", ("open", "in_progress"), "completed", reason_required=True, label="Mark complete"),
    Transition("close", ("completed",), "closed", label="Verify and close"),
    Transition("reopen", ("completed", "closed"), "in_progress", reason_required=True, label="Reopen"),
    Transition("cancel", ("open", "in_progress"), "cancelled", reason_required=True, label="Cancel"),
])

EDITABLE = ("title", "description", "owner", "due_date", "priority", "progress_note")
AUDITED = EDITABLE + ("status", "org_unit_code")

entities.register(entities.EntityType(
    key="action", label="Action", model=Action, unit_of=lambda a: a.org_unit_code,
    title_of=lambda a: f"{a.ref} {a.title}", page="actions"))


def check_owner(db: Session, username: str, unit: str) -> str:
    """The owner must be an active user who can see the action's unit."""
    user = db.query(User).filter(User.username == (username or "").strip(), User.is_active.is_(True)).first()
    if user is None:
        raise Invalid(f"Unknown or inactive user '{username}'.")
    if not resolve_scope(db, user).can_see(unit):
        raise Invalid(f"{user.username} has no access to this unit, so cannot own the action.")
    return user.username


def create(db: Session, scope: Scope, *, title: str, owner: str, org_unit_code: str,
           description: str | None = None, due_date: date | None = None, priority: str = "medium",
           source_type: str | None = None, source_id: Any = None, check_role: bool = True) -> Action:
    unit = check_unit(db, org_unit_code)
    if check_role:
        scope.require(unit, "contributor", "actions")
    title = (title or "").strip()
    if not title:
        raise Invalid("An action needs a title.")
    if priority not in ACTION_PRIORITIES:
        raise Invalid(f"Priority must be one of {', '.join(ACTION_PRIORITIES)}.")
    owner = check_owner(db, owner, unit)
    a = Action(ref=f"tmp-{datetime.utcnow().timestamp()}", title=title[:200], description=description,
               owner=owner, org_unit_code=unit, due_date=due_date, priority=priority, status="open",
               source_type=source_type, source_id=None if source_id is None else str(source_id),
               created_by=scope.username)
    db.add(a)
    db.flush()
    a.ref = f"ACT-{a.id:04d}"
    audit.record(db, scope.username, "action.create", "action", a.id, after=audit.snapshot(a, AUDITED + ("ref",)),
                 org_unit_code=unit)
    if source_type in entities.REGISTRY:
        from app.platform import links
        links.add_link(db, scope, "action", a.id, source_type, source_id, relation="responds_to", role="viewer")
    if owner != scope.username:
        notify(db, owner, "action_assigned", f"New action for you: {a.ref} {a.title}",
               body=f"Due {due_date.isoformat()}." if due_date else None, entity_type="action", entity_id=a.id)
    return a


def get(db: Session, scope: Scope, action_id: int) -> Action:
    a, _ = entities.load(db, scope, "action", action_id)
    return a


def _is_reviewer(scope: Scope, a: Action) -> bool:
    return scope.can(a.org_unit_code, "reviewer")


def update(db: Session, scope: Scope, action_id: int, changes: dict, reason: str | None = None) -> Action:
    a = get(db, scope, action_id)
    if a.status in ("closed", "cancelled"):
        raise Invalid(f"{a.ref} is {a.status}; reopen it before editing.")
    is_owner = a.owner == scope.username and not scope.read_only
    if not (_is_reviewer(scope, a) or a.created_by == scope.username or is_owner):
        raise Forbidden("Only the owner, the person who raised it, or a reviewer can edit this action.")
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise Invalid(f"Cannot edit {', '.join(sorted(unknown))}.")
    if is_owner and not _is_reviewer(scope, a) and a.created_by != scope.username:
        # Owners report progress; they do not re-assign or re-date their own work.
        if set(changes) - {"progress_note", "description"}:
            raise Forbidden("As owner you can update progress; ask a reviewer to change owner, due date or priority.")
    if "priority" in changes and changes["priority"] not in ACTION_PRIORITIES:
        raise Invalid(f"Priority must be one of {', '.join(ACTION_PRIORITIES)}.")
    if "owner" in changes:
        changes["owner"] = check_owner(db, changes["owner"], a.org_unit_code)
    if "title" in changes and not (changes["title"] or "").strip():
        raise Invalid("An action needs a title.")
    if "due_date" in changes and a.due_date and changes["due_date"] != a.due_date and not (reason or "").strip():
        raise Invalid("Changing an agreed due date needs a reason.")
    before = audit.snapshot(a, EDITABLE)
    for k, v in changes.items():
        setattr(a, k, v)
    b, after = audit.changed(before, audit.snapshot(a, EDITABLE))
    if after:
        audit.record(db, scope.username, "action.update", "action", a.id, before=b, after=after,
                     reason=reason, org_unit_code=a.org_unit_code)
        if "owner" in after:
            notify(db, a.owner, "action_assigned", f"Action re-assigned to you: {a.ref} {a.title}",
                   entity_type="action", entity_id=a.id)
    return a


def transition(db: Session, scope: Scope, action_id: int, name: str, note: str | None = None) -> Action:
    a = get(db, scope, action_id)
    t = WORKFLOW.check(a, name, note)
    is_owner = a.owner == scope.username and not scope.read_only
    reviewer = _is_reviewer(scope, a)
    if name in ("start", "complete") and not (is_owner or reviewer):
        raise Forbidden("Only the owner or a reviewer can progress this action.")
    if name in ("close", "cancel") and not reviewer:
        raise Forbidden(f"Only a reviewer on this unit can {name} an action.")
    if name == "close" and a.owner == scope.username:
        raise Forbidden("The owner cannot verify and close their own action; another reviewer must.")
    if name == "reopen" and not (reviewer or (is_owner and a.status == "completed")):
        raise Forbidden("Only a reviewer can reopen a closed action.")
    extra = {}
    if name == "complete":
        a.completion_note, a.completed_at = note.strip(), datetime.utcnow()
        extra = {"completion_note": a.completion_note}
    if name == "close":
        a.closed_by = scope.username
    if name == "reopen":
        a.completed_at, a.closed_by = None, None
    WORKFLOW.apply(db, a, t.name, scope.username, reason=note, org_unit_code=a.org_unit_code, extra_after=extra)
    if name == "complete" and a.created_by != scope.username:
        notify(db, a.created_by, "action_completed", f"Completed, awaiting verification: {a.ref} {a.title}",
               entity_type="action", entity_id=a.id)
    if name in ("reopen", "close", "cancel") and a.owner != scope.username:
        notify(db, a.owner, f"action_{a.status}", f"{a.ref} {a.title} is now {a.status.replace('_', ' ')}",
               body=note, entity_type="action", entity_id=a.id)
    return a


def query(db: Session, scope: Scope, *, status: str | None = None, owner: str | None = None,
          org_unit_code: str | None = None, source_type: str | None = None, source_id: str | None = None,
          overdue: bool = False, open_only: bool = False):
    q = scope.filter(db.query(Action), Action.org_unit_code)
    if status:
        q = q.filter(Action.status == status)
    if open_only or overdue:
        q = q.filter(Action.status.in_(("open", "in_progress")))
    if overdue:
        q = q.filter(Action.due_date.isnot(None), Action.due_date < datetime.utcnow().date())
    if owner:
        q = q.filter(Action.owner == owner)
    if org_unit_code:
        q = q.filter(Action.org_unit_code == org_unit_code)
    if source_type:
        q = q.filter(Action.source_type == source_type)
    if source_id is not None:
        q = q.filter(Action.source_id == str(source_id))
    return q.order_by(Action.due_date.is_(None), Action.due_date, Action.id)


def action_dict(a: Action, scope: Scope | None = None) -> dict:
    today = datetime.utcnow().date()
    d = {"id": a.id, "ref": a.ref, "title": a.title, "description": a.description, "owner": a.owner,
         "org_unit_code": a.org_unit_code, "due_date": a.due_date.isoformat() if a.due_date else None,
         "priority": a.priority, "status": a.status, "source_type": a.source_type, "source_id": a.source_id,
         "progress_note": a.progress_note, "completion_note": a.completion_note,
         "completed_at": a.completed_at.isoformat() if a.completed_at else None, "closed_by": a.closed_by,
         "created_by": a.created_by, "created_at": a.created_at.isoformat() if a.created_at else None,
         "overdue": bool(a.due_date and a.due_date < today and a.status in ("open", "in_progress"))}
    if scope is not None:
        d["allowed"] = [t for t in WORKFLOW.allowed(a.status) if _may(scope, a, t)]
        d["can_edit"] = a.status not in ("closed", "cancelled") and not scope.read_only and (
            _is_reviewer(scope, a) or a.created_by == scope.username or a.owner == scope.username)
    return d


def _may(scope: Scope, a: Action, name: str) -> bool:
    if scope.read_only:
        return False
    is_owner = a.owner == scope.username
    reviewer = _is_reviewer(scope, a)
    if name in ("start", "complete"):
        return is_owner or reviewer
    if name == "close":
        return reviewer and not is_owner
    if name == "cancel":
        return reviewer
    if name == "reopen":
        return reviewer or (is_owner and a.status == "completed")
    return False


def require(db: Session, action_id: int) -> Action:
    a = db.get(Action, action_id)
    if a is None:
        raise NotFound("Action not found.")
    return a
