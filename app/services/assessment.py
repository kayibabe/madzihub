"""Assessment primitives for legacy returns: unknown is not a measured zero.

Coverage here means the selected records, not proof that every expected return
has arrived. Historical blanks already stored as zero cannot be reconstructed.
"""
from __future__ import annotations

import math
from decimal import Decimal


def present(row, field):
    if field in getattr(row, "_missing_metrics", ()):
        return False
    value = getattr(row, field, None)
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and math.isfinite(value)


def complete(rows, *fields):
    return bool(rows) and all(present(row, field) for row in rows for field in fields)


def ratio(rows, numerator, denominator, scale=100, digits=1):
    if not complete(rows, numerator, denominator):
        return None
    bottom = sum(getattr(row, denominator) for row in rows)
    if bottom <= 0:
        return None
    return round(sum(getattr(row, numerator) for row in rows) / bottom * scale, digits)


def divide(numerator, denominator, scale=100, digits=1):
    """Ratio of two already-aggregated totals; None when it cannot be assessed.

    For stock balances (connections, staff, meters) that are backfilled across
    months, where row-level completeness cannot be judged. A zero or missing
    denominator is Not assessed, never a measured 0.
    """
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator * scale, digits)


def flag(value, good, warning=None, *, lower=False):
    if value is None or not math.isfinite(value):
        return "NOT ASSESSED"
    if (value <= good if lower else value >= good):
        return "GOOD"
    if warning is not None and (value <= warning if lower else value >= warning):
        return "WATCH"
    return "HIGH"


def above(value, target):
    return None if value is None else value > target
