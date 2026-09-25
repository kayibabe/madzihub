"""
Reporting periods on the tenant fiscal calendar.

Periods are created per fiscal year (12 months, 4 quarters, the year). A locked
period rejects writes from every module; the only way back is ``reopen`` with a
reason, which is audited. Nothing is ever unlocked silently.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.integration.mapping import period_label, shift_period
from app.platform import audit
from app.platform.errors import Conflict, Invalid, NotFound, PeriodLocked
from app.platform.models import PERIOD_TYPES, Period


def _end_of(start: date, period_type: str) -> date:
    months = {"month": 1, "quarter": 3, "year": 12}[period_type]
    last = shift_period(start, "month", months - 1)
    return date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])


def fiscal_year_start(fy_end_year: int) -> date:
    from app.utils import FY_START_MONTH, fy_calendar_year
    return date(fy_calendar_year(fy_end_year, FY_START_MONTH), FY_START_MONTH, 1)


def ensure_fiscal_year(db: Session, fy_end_year: int) -> list[Period]:
    """Create the year, its quarters and months if missing (idempotent)."""
    if not 1990 <= fy_end_year <= 2100:
        raise Invalid("Fiscal year out of range.")
    start = fiscal_year_start(fy_end_year)
    wanted = [("year", start)]
    wanted += [("quarter", shift_period(start, "month", 3 * q)) for q in range(4)]
    wanted += [("month", shift_period(start, "month", m)) for m in range(12)]
    existing = {(p.period_type, p.start_date): p
                for p in db.query(Period).filter(Period.fiscal_year == fy_end_year)}
    out = []
    for ptype, pstart in wanted:
        p = existing.get((ptype, pstart))
        if p is None:
            p = Period(period_type=ptype, start_date=pstart, end_date=_end_of(pstart, ptype),
                       label=period_label(pstart, ptype), fiscal_year=fy_end_year, status="open")
            db.add(p)
        out.append(p)
    db.flush()
    return out


def get(db: Session, period_id: int) -> Period:
    p = db.get(Period, period_id)
    if p is None:
        raise NotFound("Period not found.")
    return p


def find(db: Session, period_type: str, start: date) -> Period | None:
    return db.query(Period).filter_by(period_type=period_type, start_date=start).first()


def containing(db: Session, period: Period) -> list[Period]:
    """The period itself and every longer period that contains it (month -> quarter -> year)."""
    out = [period]
    for ptype in PERIOD_TYPES:
        if ptype == period.period_type:
            continue
        p = (db.query(Period).filter(Period.period_type == ptype, Period.start_date <= period.start_date,
                                     Period.end_date >= period.end_date).first())
        if p and (p.end_date - p.start_date) > (period.end_date - period.start_date):
            out.append(p)
    return out


def assert_open(db: Session, period: Period | int) -> Period:
    """Refuse writes to a locked period, or to a month/quarter inside a locked quarter/year."""
    p = get(db, period) if isinstance(period, int) else period
    for q in containing(db, p):
        if q.status == "locked":
            raise PeriodLocked(f"{q.label} is locked. Ask an administrator to reopen it, with a reason, "
                               "before making a correction.")
    return p


def lock(db: Session, period: Period, actor: str, note: str | None = None) -> Period:
    if period.status == "locked":
        raise Conflict(f"{period.label} is already locked.")
    before = audit.snapshot(period, ("status", "locked_at", "locked_by"))
    period.status, period.locked_at, period.locked_by = "locked", datetime.utcnow(), actor
    audit.record(db, actor, "period.lock", "period", period.id, before=before,
                 after=audit.snapshot(period, ("status", "locked_at", "locked_by")), reason=note)
    return period


def reopen(db: Session, period: Period, actor: str, reason: str) -> Period:
    if period.status != "locked":
        raise Conflict(f"{period.label} is not locked.")
    if not (reason or "").strip():
        raise Invalid("A reason is required to reopen a locked period.")
    before = audit.snapshot(period, ("status", "locked_at", "locked_by"))
    period.status, period.locked_at, period.locked_by = "open", None, None
    audit.record(db, actor, "period.reopen", "period", period.id, before=before,
                 after={"status": "open"}, reason=reason.strip())
    return period


def period_dict(p: Period) -> dict:
    return {"id": p.id, "period_type": p.period_type, "start_date": p.start_date.isoformat(),
            "end_date": p.end_date.isoformat(), "label": p.label, "fiscal_year": p.fiscal_year,
            "status": p.status, "locked_at": p.locked_at.isoformat() if p.locked_at else None,
            "locked_by": p.locked_by}
