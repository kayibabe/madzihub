"""
routers/strategic.py — SRWB Strategic Plan 2023-2028 Scorecard
==============================================================
Tracks the official Key Performance Indicators from the SRWB 2023-2028
Strategic Plan (Section 5.5/5.6) against actuals computed from the captured
monthly returns.

The target matrix below is transcribed verbatim from the approved Strategic
Plan. Targets are keyed by FY *end* year (2024 = FY2023/24 … 2028 = FY2027/28),
with the 2022/23 baseline. KPIs whose data the system does not yet capture are
returned as "target only" with actual = null and status = "no_data", so the
board can see exactly which strategic measures still need a data feed.

    GET /api/strategic/scorecard?year=2026
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import Record, get_db
from app.utils import fy_label

router = APIRouter(prefix="/api/strategic", tags=["Strategic Plan"])

SP_YEARS = [2024, 2025, 2026, 2027, 2028]   # FY end-years 23/24 … 27/28


def _t(*vals) -> dict:
    """Build a {end_year: target} map from the five SP target columns."""
    return {y: v for y, v in zip(SP_YEARS, vals)}


# (focus_area, name, unit, baseline_22_23, targets, actual_key, direction, capture)
# direction: "high" = higher is better; "low" = lower is better.
# capture:
#   "live"        → actual computed from captured data and reconciled to the SP definition
#   "operational" → the metric is captured on an operational page but its raw aggregation
#                   does not yet match the SP's exact definition (needs reconciliation)
#   "gap"         → no data feed for this measure yet
KPIS = [
    # ── Focus Area 1: Operations & Infrastructure Development ──────────────
    ("Operations & Infrastructure", "Water Production", "m³/year", 15_200_060,
     _t(15_400_000, 18_000_000, 22_000_000, 24_500_000, 27_000_000), "production", "high", "live"),
    ("Operations & Infrastructure", "Water Sold", "m³/year", 11_000_005,
     _t(11_200_000, 13_230_000, 16_280_000, 18_252_500, 20_250_000), "water_sold", "high", "live"),
    ("Operations & Infrastructure", "Non-Revenue Water", "%", 30,
     _t(27, 26.5, 26, 25.5, 25), "nrw_pct", "low", "live"),
    ("Operations & Infrastructure", "Service Coverage", "%", 84,
     _t(85, 86, 87, 88, 89), "coverage_pct", "high", "live"),
    ("Operations & Infrastructure", "Centres Upgraded/Rehabilitated", "No.", 3,
     _t(1, 2, 2, 2, 2), None, "high", "gap"),
    ("Operations & Infrastructure", "New Water Supply Centres", "No.", 3,
     _t(5, 5, 5, 5, 4), None, "high", "gap"),
    ("Operations & Infrastructure", "Boreholes Drilled", "No.", 10,
     _t(3, 4, 2, 2, 2), None, "high", "gap"),
    ("Operations & Infrastructure", "Centres Digitised", "No.", 1,
     _t(1, 2, 2, 1, 1), None, "high", "gap"),
    ("Operations & Infrastructure", "Communal Water Points", "No.", 748,
     _t(800, 820, 850, 870, 900), None, "high", "gap"),
    ("Operations & Infrastructure", "Communal Water Point Customers", "No.", 200_000,
     _t(220_000, 230_000, 250_000, 270_000, 300_000), None, "high", "operational"),
    # ── Focus Area 2: Business Growth ──────────────────────────────────────
    ("Business Growth", "Debtor Days", "Days", 200,
     _t(150, 60, 60, 60, 60), "debtor_days", "low", "live"),
    ("Business Growth", "New Water Connections", "No./year", 7_000,
     _t(8_000, 7_000, 6_000, 7_000, 7_000), "new_connections", "high", "live"),
    ("Business Growth", "Customer Base", "No.", 75_000,
     _t(83_000, 90_000, 96_000, 103_000, 110_000), "customer_base", "high", "live"),
    ("Business Growth", "Return on Capital Employed", "%", 6,
     _t(6, 6, 6, 6, 6), None, "high", "gap"),
    ("Business Growth", "Creditors Days", "Days", 300,
     _t(150, 90, 60, 60, 60), None, "low", "gap"),
    ("Business Growth", "Current Ratio", "ratio", 2.0,
     _t(2.0, 2.0, 2.0, 2.0, 2.0), None, "high", "gap"),
    ("Business Growth", "Revenue", "MK bn", 11.9,
     _t(18.01, 21.2, 26.1, 29.2, 32.5), "revenue_bn", "high", "live"),
    # ── Focus Area 3: Customer & Stakeholder Satisfaction ──────────────────
    ("Customer & Stakeholder Satisfaction", "Job Satisfaction Level", "%", 90,
     _t(90, 90, 90, 90, 90), None, "high", "gap"),
    ("Customer & Stakeholder Satisfaction", "Water Samples Complying with WHO/MBS", "%", 95,
     _t(96, 97, 98, 99, 100), None, "high", "gap"),
    ("Customer & Stakeholder Satisfaction", "Service Connection Time", "Days", 60,
     _t(45, 30, 28, 28, 28), None, "low", "operational"),
    ("Customer & Stakeholder Satisfaction", "Connectivity Rate", "%", 75,
     _t(80, 80, 85, 90, 95), None, "high", "operational"),
    ("Customer & Stakeholder Satisfaction", "Response Time to Customer Queries", "Days", 30,
     _t(20, 10, 7, 3, 3), None, "low", "operational"),
    ("Customer & Stakeholder Satisfaction", "Continuity of Supply", "Hours", 19,
     _t(20, 20, 21, 21, 22), None, "high", "operational"),
    ("Customer & Stakeholder Satisfaction", "Customer Satisfaction Rating", "%", 60,
     _t(70, 75, 80, 85, 85), None, "high", "gap"),
    ("Customer & Stakeholder Satisfaction", "Response Time to Breakdown", "Hours", 6,
     _t(4, 3, 3, 3, 3), None, "low", "gap"),
    # ── Focus Area 4: Innovation & Productivity ────────────────────────────
    ("Innovation & Productivity", "Staff per 1,000 Connections", "No.", 13,
     _t(13, 13, 13, 13, 13), "staff_per_1000conn", "low", "live"),
    ("Innovation & Productivity", "Staff per 1,000 m³ Produced", "No.", 8,
     _t(8, 8, 8, 8, 8), "staff_per_1000m3", "low", "live"),
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


@router.get("/scorecard", summary="Strategic Plan 2023-2028 KPI scorecard")
def scorecard(year: int = Query(default=2026, description="FY end-year, e.g. 2026 = FY2025/26"),
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
        "plan": "SRWB Strategic Plan 2023-2028",
        "summary": {
            "total": len(KPIS),
            "live": counts["live"], "operational": counts["operational"], "gap": counts["gap"],
            "on_track": on_track, "watch": watch, "behind": behind,
        },
        "items": items,
    }
