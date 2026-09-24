"""
app/utils.py
────────────
Shared utility functions and constants used across routers.

Centralises:
  • fy_label()        — human-readable FY label (e.g. "FY2025/26")
  • apply_fy_filter() — SQLAlchemy filter for the configured fiscal year
  • csv_list()        — whitespace-safe comma-split (fixes bare .split(",") bugs)
  • fiscal_month_names() — month names ordered by configured fiscal year
"""
from __future__ import annotations

from typing import Optional
import calendar


def get_fiscal_start_month(db=None) -> int:
    """Read the installation fiscal calendar, opening a short lived session if needed."""
    from app.database import OrgProfile, SessionLocal
    own_session = db is None
    session = db or SessionLocal()
    try:
        profile = session.query(OrgProfile).filter(OrgProfile.id == 1).first()
        return profile.fiscal_year_start_month if profile else 1
    finally:
        if own_session:
            session.close()


# ── Month sequences ───────────────────────────────────────────────────────────

def fiscal_month_numbers(start_month: int = 1) -> list[int]:
    """Calendar month numbers in configured fiscal-year order."""
    start_month = max(1, min(12, int(start_month)))
    return list(range(start_month, 13)) + list(range(1, start_month))


def fiscal_month_names(start_month: int = 1) -> list[str]:
    return [calendar.month_name[number] for number in fiscal_month_numbers(start_month)]


def fiscal_month_labels(start_month: int = 1) -> list[str]:
    return [calendar.month_abbr[number] for number in fiscal_month_numbers(start_month)]


# Compatibility defaults are calendar-year based. New request paths should pass
# the installation's configured fiscal year start month explicitly.
MONTHS_ORDER: list[str] = fiscal_month_names()
MONTHS_LBL: list[str] = fiscal_month_labels()
FY_MONTH_NOS: list[int] = fiscal_month_numbers()


# ── Fiscal year helpers ────────────────────────────────────────────────────────

def fy_label(year: int, start_month: int = 1) -> str:
    """Return a human-readable fiscal-year label for the given end year.

    Examples
    --------
    >>> fy_label(2026)
    'FY2025/26'
    >>> fy_label(2025)
    'FY2024/25'
    """
    start_month = max(1, min(12, int(start_month)))
    start_year = year - 1 if start_month > 1 else year
    return f"FY{start_year}/{str(year)[-2:]}" if start_month > 1 else f"FY{year}"


def apply_fy_filter(query, year: int, start_month: int = 1):
    """Apply the April-March fiscal-year span filter to a SQLAlchemy query.

    For a configured fiscal year starting in July, end-year 2027 spans
    July 2026 through June 2027.

    Uses a composite-index-friendly OR construction:
        (year == FY-1 AND month_no >= 4) OR (year == FY AND month_no <= 3)

    Parameters
    ----------
    query : SQLAlchemy Query
        The base query to filter.
    year : int
        The FY-end year (e.g. 2026 for FY2025/26).

    Returns
    -------
    SQLAlchemy Query
        The filtered query.
    """
    from sqlalchemy import and_, or_
    from app.database import Record

    start_month = max(1, min(12, int(start_month)))
    if start_month == 1:
        return query.filter(Record.year == year)
    return query.filter(or_(
        and_(Record.year == year - 1, Record.month_no >= start_month),
        and_(Record.year == year, Record.month_no < start_month),
    ))


# ── Filter helpers ─────────────────────────────────────────────────────────────

def csv_list(v: Optional[str]) -> Optional[list[str]]:
    """Split a comma-separated query-parameter string into a clean list.

    Unlike a bare ``v.split(",")``, this:
      - Returns ``None`` (not an empty list) when the input is falsy.
      - Strips whitespace from each token.
      - Drops empty tokens produced by trailing/doubled commas.

    Examples
    --------
    >>> csv_list("Zone A, Zone B,  Zone C")
    ['Zone A', 'Zone B', 'Zone C']
    >>> csv_list("")
    >>> csv_list(None)
    """
    if not v:
        return None
    items = [item.strip() for item in v.split(",") if item.strip()]
    return items if items else None
