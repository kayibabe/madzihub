"""Append-only audit events.

Every governed change is recorded with its actor, the record, the state before and
after, and the reason where one is required. Events are written in the caller's
transaction, so a change and its audit record commit (or roll back) together.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.logging import REQUEST_ID_CTX
from app.platform.models import AuditEvent


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def snapshot(obj: Any, fields: Iterable[str]) -> dict:
    """JSON-safe copy of selected attributes, for before/after state."""
    return {f: _plain(getattr(obj, f, None)) for f in fields}


def changed(before: dict, after: dict) -> tuple[dict, dict]:
    """Only the keys whose values differ, so events stay readable."""
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after[k] for k in keys}


def record(db: Session, actor: str, action: str, entity_type: str, entity_id: Any, *,
           before: dict | None = None, after: dict | None = None, reason: str | None = None,
           org_unit_code: str | None = None) -> AuditEvent:
    try:
        request_id = REQUEST_ID_CTX.get()
    except LookupError:
        request_id = None
    event = AuditEvent(actor=actor, action=action, entity_type=entity_type, entity_id=str(entity_id),
                       org_unit_code=org_unit_code, before=_plain(before), after=_plain(after),
                       reason=(reason or None), request_id=request_id if request_id not in ("", "-") else None)
    db.add(event)
    return event


def event_dict(e: AuditEvent) -> dict:
    return {"id": e.id, "at": e.at.isoformat() if e.at else None, "actor": e.actor, "action": e.action,
            "entity_type": e.entity_type, "entity_id": e.entity_id, "org_unit_code": e.org_unit_code,
            "before": e.before, "after": e.after, "reason": e.reason, "request_id": e.request_id}
