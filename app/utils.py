"""
app/utils.py
────────────
Shared utility functions and constants used across routers.

Centralises:
  • fy_label()        — human-readable FY label (e.g. "FY2025/26")
  • apply_fy_filter() — SQLAlchemy OR-span filter for April-March FY
  • csv_list()        — whitespace-safe comma-split (fixes bare .split(",") bugs)
  • MONTHS_ORDER      — full month names in FY order (April → March)
  • MONTHS_LBL        — abbreviated month names in FY order (Apr → Mar)
  • FY_MONTH_NOS      — calendar month numbers in FY order (4 → 3)
"""
from __future__ import annotations

from typing import Optional


# ── Month sequences (FY order: April → March) ─────────────────────────────────

MONTHS_ORDER: list[str] = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March",
]

MONTHS_LBL: list[str] = [
    "Apr", "May", "Jun", "Jul", "Aug", "Sep",
    "Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
]

FY_MONTH_NOS: list[int] = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]


# ── Fiscal year helpers ────────────────────────────────────────────────────────

def fy_label(year: int) -> str:
    """Return a human-readable FY label for the given FY-end year.

    Examples
    --------
    >>> fy_label(2026)
    'FY2025/26'
    >>> fy_label(2025)
    'FY2024/25'
    """
    return f"FY{year - 1}/{str(year)[-2:]}"


def apply_fy_filter(query, year: int):
    """Apply the April-March fiscal-year span filter to a SQLAlchemy query.

    SRWB's fiscal year runs April-March, so FY-end year 2026 spans:
        April 2025 (month_no=4, year=2025) → March 2026 (month_no=3, year=2026)

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

    return query.filter(
        or_(
            and_(Record.year == year - 1, Record.month_no >= 4),
            and_(Record.year == year,     Record.month_no <= 3),
        )
    )


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
