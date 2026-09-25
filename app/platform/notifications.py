"""
In-app notifications and the due/overdue reminder job.

Nothing is sent outside the application: external distribution (e-mail, SMS) needs
an explicitly configured action and is not part of this release.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.database import User
from app.platform.models import Action, Notification


def notify(db: Session, username: str | None, kind: str, title: str, *, body: str | None = None,
           entity_type: str | None = None, entity_id=None, dedupe_key: str | None = None) -> bool:
    """Queue a notice; returns False when the user is unknown/inactive or it was already sent."""
    if not username:
        return False
    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if user is None:
        return False
    if dedupe_key and db.query(Notification.id).filter_by(username=username, dedupe_key=dedupe_key).first():
        return False
    db.add(Notification(username=username, kind=kind, title=title[:200], body=body,
                        entity_type=entity_type, entity_id=None if entity_id is None else str(entity_id),
                        dedupe_key=dedupe_key))
    return True


def resolve(db: Session, entity_type: str, entity_id, kinds: tuple[str, ...]) -> int:
    """Mark unread notices about a record as read once the work they asked for is done."""
    return (db.query(Notification)
            .filter(Notification.entity_type == entity_type, Notification.entity_id == str(entity_id),
                    Notification.kind.in_(kinds), Notification.read_at.is_(None))
            .update({Notification.read_at: datetime.utcnow()}, synchronize_session=False))


def notification_dict(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "entity_type": n.entity_type,
            "entity_id": n.entity_id, "created_at": n.created_at.isoformat() if n.created_at else None,
            "read": n.read_at is not None}


# Other modules add reminder producers here: fn(db, today) -> number of notices created.
REMINDER_PRODUCERS: list = []


def _action_reminders(db: Session, today: date) -> int:
    sent = 0
    soon = today + timedelta(days=7)
    for a in db.query(Action).filter(Action.status.in_(("open", "in_progress")), Action.due_date.isnot(None)):
        if a.due_date < today:
            sent += notify(db, a.owner, "action_overdue", f"Overdue: {a.ref} {a.title}",
                           body=f"Due {a.due_date.isoformat()}.", entity_type="action", entity_id=a.id,
                           dedupe_key=f"action:{a.id}:overdue:{today.isoformat()}")
        elif a.due_date <= soon:
            sent += notify(db, a.owner, "action_due_soon", f"Due soon: {a.ref} {a.title}",
                           body=f"Due {a.due_date.isoformat()}.", entity_type="action", entity_id=a.id,
                           dedupe_key=f"action:{a.id}:due:{a.due_date.isoformat()}")
    return sent


REMINDER_PRODUCERS.append(_action_reminders)


def run_reminders(db: Session, today: date | None = None) -> int:
    """Create due/overdue notices once per item per day. Safe to run repeatedly."""
    today = today or datetime.utcnow().date()
    total = sum(producer(db, today) for producer in REMINDER_PRODUCERS)
    db.commit()
    return total
