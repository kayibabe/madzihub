from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("opsapp.audit")


def log_event(
    db: Any,
    user: str,
    action: str,
    detail: str,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Write an audit event to the application log and, when db is provided, to the DB."""
    log.info(
        "audit_event",
        extra={
            "username": user,
            "action": action,
            "detail": detail,
            "request_id": request_id,
        },
    )
    if db is not None:
        try:
            from app.database import ActivityLog
            db.add(ActivityLog(username=user, action=action, detail=detail, ip_address=ip_address))
            db.commit()
        except Exception:
            log.warning("audit_log_db_write_failed", exc_info=True)
