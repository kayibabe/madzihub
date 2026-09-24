"""
routers/strategic.py — Strategic Plan KPI Scorecard
===================================================
Tracks the utility's strategic-plan Key Performance Indicators against actuals
computed from the captured monthly returns.

The target matrix comes from the tenant configuration (for SRWB: transcribed
verbatim from the approved Strategic Plan 2023-2028). Targets are keyed by FY
*end* year (2024 = FY2023/24 … 2028 = FY2027/28). KPIs whose data the system does not yet capture are
returned as "target only" with actual = null and status = "no_data", so the
board can see exactly which strategic measures still need a data feed.

    GET /api/strategic/scorecard?year=2026
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.tenant import tenant as _tenant
from app.database import Record, get_db
from app.utils import fy_label

router = APIRouter(prefix="/api/strategic", tags=["Strategic Plan"])

# The plan's KPI matrix (focus area, name, unit, baseline, per-year targets,
# actual key, direction, capture) is utility-specific and lives in the tenant
# configuration: tenants/<name>/tenant.yaml → strategic_plan.
#
# direction: "high" = higher is better; "low" = lower is better.
# capture:
#   "live"        → actual computed from captured data and reconciled to the SP definition
#   "operational" → the metric is captured on an operational page but its raw aggregation
#                   does not yet match the SP's exact definition (needs reconciliation)
#   "gap"         → no data feed for this measure yet
_PLAN = _tenant.strategic_plan
SP_YEARS = list(_PLAN.years)
SP_DEFAULT_YEAR = _PLAN.default_year or (SP_YEARS[-1] if SP_YEARS else 2026)

KPIS = [
    (k.focus_area, k.name, k.unit, k.baseline, dict(k.targets), k.actual_key, k.direction, k.capture)
    for k in _PLAN.kpis
]


def _actuals(rows) -> dict:
    """Compute the capturable KPI actuals from the FY's monthly returns."""
    def s(attr):
        return sum(float(getattr(r, attr, 0) or 0) for r in rows)

    def avgnz(attr):
        vals = [float(getattr(r, attr, 0) or 0) for r in rows if (getattr(r, attr, 0) or 0) != 0]
        return sum(vals) / len(vals) if vals else None

    # Stock metrics: use the latest month present in the FY
    latest = []
    if rows:
        lk = max((r.year, r.month_no) for r in rows)
        latest = [r for r in rows if (r.year, r.month_no) == lk]

    def slatest(attr):
        return sum(float(getattr(r, attr, 0) or 0) for r in latest)

    prod = s("vol_produced")
    sold = s("total_vol_billed_pp") + s("total_vol_billed_prepaid")
    nrwv = s("nrw")
    cust = slatest("active_customers")
    staff = slatest("perm_staff") + slatest("temp_staff")
    debt = slatest("total_debtors")
    billed = s("amt_billed")
    area = slatest("pop_supply_area")
    supplied = slatest("pop_supplied")
    cwp = slatest("active_post_cwp") + slatest("active_prep_cwp")

    wq_fields = (("wq_cl_samples", "wq_cl_compliant"), ("wq_turbidity_samples", "wq_turbidity_compliant"),
                 ("wq_bact_samples", "wq_bact_compliant"), ("wq_ph_samples", "wq_ph_compliant"))
    wq_s = sum(int(getattr(r, sf, 0) or 0) for r in rows for sf, _ in wq_fields)
    wq_c = sum(int(getattr(r, cf, 0) or 0) for r in rows for _, cf in wq_fields)

    return {
        "production":         prod or None,
        "water_sold":         sold or None,
        "nrw_pct":            (nrwv / prod * 100) if prod else None,
        "coverage_pct":       (supplied / area * 100) if area else None,
        "new_connections":    s("new_connections") or None,
        "customer_base":      cust or None,
        "cwp_customers":      cwp or None,
        "revenue_bn":         (s("total_sales") / 1e9) or None,
        "conn_days":          avgnz("connection_days") or avgnz("days_to_connect"),
        "connectivity":       avgnz("connectivity_rate"),
        "query_days":         avgnz("time_to_resolve") or avgnz("response_time_avg"),
        "supply_hours":       avgnz("supply_hours"),
        "staff_per_1000m3":   avgnz("staff_per_1000m3_12h") or ((staff / (prod / 1000)) if prod else None),
        "staff_per_1000conn": (staff / cust * 1000) if cust else None,
        "debtor_days":        (debt / billed * 365) if billed else None,
        "wq_compliance":      (wq_c / wq_s * 100) if wq_s else None,
    }


def _status(actual, target, direction):
    if actual is None or target in (None, 0):
        return "no_data" if actual is None else "on_track"
    ratio = actual / target
    if direction == "high":
        return "on_track" if ratio >= 0.95 else ("watch" if ratio >= 0.85 else "behind")
    # lower is better
    return "on_track" if ratio <= 1.05 else ("watch" if ratio <= 1.15 else "behind")


@router.get("/scorecard", summary="Strategic plan KPI scorecard")
def scorecard(year: int = Query(default=SP_DEFAULT_YEAR, description="FY end-year, e.g. 2026 = FY2025/26"),
              db: Session = Depends(get_db)):
    rows = db.query(Record).filter(Record.fiscal_year == fy_label(year)).all()
    act = _actuals(rows)

    items = []
    counts = {"live": 0, "operational": 0, "gap": 0}
    on_track = watch = behind = 0
    for focus, name, unit, baseline, targets, key, direction, capture in KPIS:
        target = targets.get(year)
        actual = act.get(key) if (key and capture == "live") else None
        st = _status(actual, target, direction) if capture == "live" else "no_data"
        counts[capture] = counts.get(capture, 0) + 1
        if st == "on_track":
            on_track += 1
        elif st == "watch":
            watch += 1
        elif st == "behind":
            behind += 1
        items.append({
            "focus_area": focus, "name": name, "unit": unit,
            "baseline": baseline, "target": target,
            "actual": round(actual, 2) if isinstance(actual, (int, float)) else None,
            "direction": direction, "status": st, "capture": capture,
            "target_series": {str(y): targets.get(y) for y in SP_YEARS},
        })

    return {
        "fy": fy_label(year), "year": year,
        "plan": _PLAN.title,
        "summary": {
            "total": len(KPIS),
            "live": counts["live"], "operational": counts["operational"], "gap": counts["gap"],
            "on_track": on_track, "watch": watch, "behind": behind,
        },
        "items": items,
    }
