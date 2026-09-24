"""
app/utils.py
────────────
Shared utility functions and constants used across routers.

Centralises:
  • fy_label()        — human-readable FY label (e.g. "FY2025/26")
  • apply_fy_filter() — SQLAlchemy span filter for the configured fiscal year
  • fy_end_year(), fy_quarter(), fy_dates(), fy_label_for() — calendar helpers
  • csv_list()        — whitespace-safe comma-split (fixes bare .split(",") bugs)
  • MONTHS_ORDER      — full month names in FY order (e.g. April → March)
  • MONTHS_LBL        — abbreviated month names in FY order
  • FY_MONTH_NOS      — calendar month numbers in FY order

The fiscal-year start month comes from the tenant configuration.
"""
from __future__ import annotations

from typing import Optional


# ── Fiscal calendar (from the tenant configuration) ───────────────────────────
# The fiscal year starts in ``FY_START_MONTH`` (e.g. 4 = April). A fiscal year is
# identified by the calendar year in which it ENDS ("FY-end year"), e.g. for an
# April start, 2026 = April 2025 → March 2026. For a January start the FY-end
# year is simply the calendar year.

import calendar as _calendar

from app.core.tenant import tenant as _tenant

FY_START_MONTH: int = _tenant.fiscal_year.start_month

FY_MONTH_NOS: list[int] = [((FY_START_MONTH - 1 + i) % 12) + 1 for i in range(12)]
MONTHS_ORDER: list[str] = [_calendar.month_name[m] for m in FY_MONTH_NOS]
MONTHS_LBL: list[str] = [_calendar.month_abbr[m] for m in FY_MONTH_NOS]


def fy_end_year(year: int, month_no: int) -> int:
    """FY-end year that calendar (year, month_no) falls in."""
    if FY_START_MONTH == 1:
        return year
    return year + 1 if month_no >= FY_START_MONTH else year


def fy_calendar_year(fy_year: int, month_no: int) -> int:
    """Calendar year in which fiscal month ``month_no`` of FY-end ``fy_year`` falls."""
    if FY_START_MONTH != 1 and month_no >= FY_START_MONTH:
        return fy_year - 1
    return fy_year


def fy_month_index(month_no: int) -> int:
    """0-based position of a calendar month within the fiscal year."""
    return (month_no - FY_START_MONTH) % 12


def fy_quarter(month_no: int) -> str:
    """Fiscal quarter label ("Q1".."Q4") for a calendar month."""
    return f"Q{fy_month_index(month_no) // 3 + 1}"


def fy_dates(year: int) -> tuple[str, str]:
    """ISO start and end dates of the fiscal year ending in ``year``."""
    start_year = year if FY_START_MONTH == 1 else year - 1
    end_month = 12 if FY_START_MONTH == 1 else FY_START_MONTH - 1
    last_day = _calendar.monthrange(year, end_month)[1]
    return (f"{start_year}-{FY_START_MONTH:02d}-01", f"{year}-{end_month:02d}-{last_day:02d}")


def fy_label(year: int) -> str:
    """Return a human-readable FY label for the given FY-end year.

    Examples (April start)
    --------
    >>> fy_label(2026)
    'FY2025/26'
    """
    if FY_START_MONTH == 1:
        return f"FY{year}"
    return f"FY{year - 1}/{str(year)[-2:]}"


def fy_label_for(year: int, month_no: int) -> str:
    """FY label for a calendar (year, month_no)."""
    return fy_label(fy_end_year(year, month_no))


def fy_span_expr(year: int, model=None):
    """SQLAlchemy boolean expression selecting all months of FY-end ``year``.

    Uses a composite-index-friendly OR construction, e.g. for an April start:
        (year == FY-1 AND month_no >= 4) OR (year == FY AND month_no <= 3)
    """
    from sqlalchemy import and_, or_
    if model is None:
        from app.database import Record as model

    if FY_START_MONTH == 1:
        return model.year == year
    return or_(
        and_(model.year == year - 1, model.month_no >= FY_START_MONTH),
        and_(model.year == year,     model.month_no <= FY_START_MONTH - 1),
    )


def apply_fy_filter(query, year: int):
    """Filter a SQLAlchemy Record query to the fiscal year ending in ``year``."""
    return query.filter(fy_span_expr(year))


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
