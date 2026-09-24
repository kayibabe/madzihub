"""
Mapping: turn raw source rows into catalogue values, or explain why not.

A source's ``mapping`` (JSON) describes its layout:

    {
      "layout": "wide",                       # one row carries several measures
      "metrics": {"vol_produced": "Production (m3)", "cash_collected": {"column": "Cash", "scale": 1}},
      "period": {"field": "Date", "format": "%d/%m/%Y"},     # or {"year_field": "Year", "month_field": "Month"}
      "period_type": "month",                 # grain stored; finer rows are aggregated up
      "org_unit": {"field": "Cost Centre", "default": null}, # or {"fields": ["Zone", "Scheme"], "join": "/"}
      "filters": {"Status": ["Posted", "Final"]}
    }

    {
      "layout": "long",                       # one row per measure (SCADA tags, KPI exports)
      "metric_field": "TagName", "value_field": "Value",
      "ignore_unmapped_metrics": true,        # skip tags we do not track instead of rejecting
      "period": {"field": "Timestamp"}, "period_type": "day",
      "org_unit": {"field": "Site"}
    }

External keys (cost centres, sites, tags) are translated through ``key_mappings``;
a key that already equals a catalogue code is accepted as is.
Blank cells are skipped, never stored as zero: a missing return is not a zero return.
"""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.utils import FY_START_MONTH

MAX_REJECTS = 200
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})


@dataclass
class MappedValue:
    metric_code: str
    org_unit_code: str
    period_type: str
    period_start: date
    value: float
    source_ref: str | None


@dataclass
class MappingResult:
    values: list[MappedValue] = field(default_factory=list)
    rows_rejected: int = 0
    rejects: list[dict] = field(default_factory=list)

    def reject(self, index: int, row: dict, reason: str) -> None:
        self.rows_rejected += 1
        if len(self.rejects) < MAX_REJECTS:
            excerpt = {k: (str(v)[:60] if v is not None else None) for k, v in list(row.items())[:8]}
            self.rejects.append({"row": index, "ref": row.get("_source_ref"), "reason": reason, "data": excerpt})


def period_start(d: date, period_type: str) -> date:
    """Start of the period containing ``d``. Quarters and years follow the tenant fiscal calendar."""
    if period_type == "day":
        return d
    if period_type == "month":
        return date(d.year, d.month, 1)
    offset = (d.month - FY_START_MONTH) % 12
    if period_type == "quarter":
        offset = offset % 3
    elif period_type != "year":
        raise ValueError(f"unknown period_type {period_type}")
    y, m = d.year, d.month - offset
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1)


def shift_period(start: date, period_type: str, n: int) -> date:
    """The period ``n`` steps after (or before, if negative) the one starting at ``start``."""
    if period_type == "day":
        from datetime import timedelta
        return start + timedelta(days=n)
    months = {"month": 1, "quarter": 3, "year": 12}[period_type] * n
    idx = start.year * 12 + (start.month - 1) + months
    return date(idx // 12, idx % 12 + 1, 1)


def period_label(start: date, period_type: str) -> str:
    """Human label using the tenant fiscal calendar: 'FY2025/26', 'Q2 FY2025/26', 'Apr 2026'."""
    from app.utils import fy_end_year, fy_label, fy_quarter
    if period_type == "year":
        return fy_label(fy_end_year(start.year, start.month))
    if period_type == "quarter":
        return f"{fy_quarter(start.month)} {fy_label(fy_end_year(start.year, start.month))}"
    if period_type == "month":
        return f"{calendar.month_abbr[start.month]} {start.year}"
    return start.isoformat()


def parse_number(raw: Any) -> float | None:
    """Number or None for blank; raises ValueError for text that is not a number."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError("boolean is not a number")
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if text in ("", "-", "—", "n/a", "N/A", "NA"):
        return None
    neg = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[,\s]", "", text.strip("()"))
    return -float(text) if neg else float(text)


def _parse_month(raw: Any) -> int:
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip().lower()
    if text.isdigit():
        return int(text)
    if text in _MONTHS:
        return _MONTHS[text]
    raise ValueError(f"unrecognised month '{raw}'")


def parse_period(row: dict, spec: dict) -> date:
    if spec.get("field"):
        raw = row.get(spec["field"])
        if raw in (None, ""):
            raise ValueError(f"period field '{spec['field']}' is empty")
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        text = str(raw).strip()
        if spec.get("format"):
            return datetime.strptime(text, spec["format"]).date()
        # OData v2 dates: /Date(1735689600000)/
        m = re.match(r"/Date\((-?\d+)", text)
        if m:
            return datetime.utcfromtimestamp(int(m.group(1)) / 1000).date()
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    if spec.get("year_field"):
        year = int(parse_number(row.get(spec["year_field"])) or 0)
        month = _parse_month(row.get(spec["month_field"])) if spec.get("month_field") else 1
        day = int(parse_number(row.get(spec["day_field"])) or 1) if spec.get("day_field") else 1
        return date(year, month, day)
    if spec.get("fixed"):
        return date.fromisoformat(spec["fixed"])
    raise ValueError("mapping.period needs field, year_field or fixed")


class Resolver:
    """Translates external keys to catalogue codes for one source, with caching."""

    def __init__(self, org_codes: set[str], metric_codes: set[str], key_map: dict[tuple[str, str], str]):
        self.org_codes = org_codes
        self.metric_codes = metric_codes
        self.key_map = key_map

    def org(self, key: str | None) -> str | None:
        if key is None:
            return None
        code = self.key_map.get(("org_unit", key), key)
        return code if code in self.org_codes else None

    def metric(self, key: str | None) -> str | None:
        if key is None:
            return None
        code = self.key_map.get(("metric", key), key)
        return code if code in self.metric_codes else None


def _org_key(row: dict, spec: dict) -> str | None:
    if spec.get("fields"):
        parts = [row.get(f) for f in spec["fields"]]
        if any(p in (None, "") for p in parts):
            return None
        return str(spec.get("join", "/")).join(str(p).strip() for p in parts)
    raw = row.get(spec.get("field")) if spec.get("field") else None
    return str(raw).strip() if raw not in (None, "") else None


def _passes(row: dict, filters: dict) -> bool:
    for key, allowed in (filters or {}).items():
        allowed = allowed if isinstance(allowed, list) else [allowed]
        if row.get(key) not in allowed:
            return False
    return True


def map_rows(rows: list[dict], mapping: dict, resolver: Resolver, aggregations: dict[str, str]) -> MappingResult:
    result = MappingResult()
    layout = mapping.get("layout", "wide")
    period_type = mapping.get("period_type", "month")
    period_spec = mapping.get("period") or {}
    org_spec = mapping.get("org_unit") or {}
    # (metric, org, period) -> list of (sort_key, value, ref)
    buckets: dict[tuple[str, str, date], list[tuple[Any, float, str | None]]] = defaultdict(list)

    if layout not in ("wide", "long"):
        raise ValueError("mapping.layout must be 'wide' or 'long'")
    if layout == "wide" and not mapping.get("metrics"):
        raise ValueError("wide mapping needs a 'metrics' object: {metric_code: column}")
    if layout == "long" and not (mapping.get("metric_field") and mapping.get("value_field")):
        raise ValueError("long mapping needs metric_field and value_field")

    for idx, row in enumerate(rows, start=1):
        if not _passes(row, mapping.get("filters")):
            continue
        try:
            when = parse_period(row, period_spec)
        except (ValueError, TypeError) as exc:
            result.reject(idx, row, f"period: {exc}")
            continue
        org_key = _org_key(row, org_spec) or org_spec.get("default")
        org = resolver.org(org_key)
        if org is None:
            result.reject(idx, row, f"unknown org unit '{org_key}' (add it or a key mapping)")
            continue
        start = period_start(when, period_type)
        ref = row.get("_source_ref")

        if layout == "wide":
            pairs = []
            for code, col in mapping["metrics"].items():
                spec = col if isinstance(col, dict) else {"column": col}
                pairs.append((code, row.get(spec["column"]), float(spec.get("scale", 1))))
        else:
            ext = row.get(mapping["metric_field"])
            code = resolver.metric(str(ext).strip() if ext is not None else None)
            if code is None:
                if not mapping.get("ignore_unmapped_metrics"):
                    result.reject(idx, row, f"unknown metric '{ext}' (add it or a key mapping)")
                continue
            scale = float((mapping.get("scale") or {}).get(code, 1))
            pairs = [(code, row.get(mapping["value_field"]), scale)]

        bad = False
        for code, raw, scale in pairs:
            if code not in resolver.metric_codes:
                result.reject(idx, row, f"metric '{code}' is not in the catalogue")
                bad = True
                break
            try:
                num = parse_number(raw)
            except ValueError:
                result.reject(idx, row, f"{code}: '{raw}' is not a number")
                bad = True
                break
            if num is None:
                continue  # blank: missing, not zero
            buckets[(code, org, start)].append((when, num * scale, ref))
        if bad:
            continue

    for (code, org, start), items in buckets.items():
        agg = aggregations.get(code, "sum")
        nums = [v for _, v, _ in items]
        if agg == "sum":
            value = sum(nums)
        elif agg == "avg":
            value = sum(nums) / len(nums)
        elif agg == "max":
            value = max(nums)
        elif agg == "min":
            value = min(nums)
        else:  # last
            value = sorted(items, key=lambda t: t[0])[-1][1]
        refs = [r for _, _, r in items if r]
        ref = refs[0] if len(refs) == 1 else (f"{refs[0]} (+{len(refs) - 1} rows)" if refs else None)
        result.values.append(MappedValue(code, org, period_type, start, value, ref))
    return result
