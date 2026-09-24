"""
routers/catalogue.py

Lightweight metadata endpoints — the frontend calls these on startup
to build its slicer state without having to parse the full records list.

GET /api/catalogue/zones          — ordered list of zones
GET /api/catalogue/zone-schemes   — {zone: [scheme, ...]} mapping
GET /api/catalogue/months         — available months in the DB (ordered)
GET /api/catalogue/years          — available fiscal years
GET /api/catalogue/data-quality   — anomaly scan results (cached 5 min)
"""
from __future__ import annotations

import time
from typing import List, Dict, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import BudgetLine, FiscalYear, Record, get_db
from app.utils import MONTHS_ORDER, fy_label

router = APIRouter(prefix="/api/catalogue", tags=["Catalogue"])


# ── Simple in-process cache for the data-quality scan ────────────────────
# The scan loads every record into Python memory — fine for small datasets,
# but expensive if called repeatedly.  Cache for DQ_CACHE_TTL seconds.
# This is a single-process cache; if you run multiple workers, each will
# maintain its own copy (acceptable — the data doesn't change often).
_DQ_CACHE: Dict = {}
DQ_CACHE_TTL = 300   # 5 minutes


@router.get("/zones", response_model=List[str])
def list_zones(db: Session = Depends(get_db)):
    rows = db.query(Record.zone).distinct().order_by(Record.zone).all()
    return [r.zone for r in rows]


@router.get("/zone-schemes")
def zone_schemes(db: Session = Depends(get_db)) -> Dict[str, List[str]]:
    rows = (
        db.query(Record.zone, Record.scheme)
        .distinct()
        .order_by(Record.zone, Record.scheme)
        .all()
    )
    result: Dict[str, List[str]] = {}
    for zone, scheme in rows:
        result.setdefault(zone, []).append(scheme)
    return result


@router.get("/summary")
def catalogue_summary(db: Session = Depends(get_db)) -> Dict:
    """Quick stats for the status bar and dashboard header."""
    from sqlalchemy import func
    total   = db.query(func.count(Record.id)).scalar()
    zones   = db.query(Record.zone).distinct().count()
    schemes = db.query(Record.scheme).distinct().count()
    months  = db.query(Record.month).distinct().count()
    fy      = db.query(Record.fiscal_year).distinct().order_by(Record.fiscal_year.desc()).first()
    return {
        "total_records": total,
        "zones":   zones,
        "schemes": schemes,
        "months":  months,
        "fiscal_year": fy[0] if fy else None,
    }


@router.get("/months")
def available_months(db: Session = Depends(get_db)) -> List[str]:
    rows = db.query(Record.month).distinct().all()
    have = {r.month for r in rows}
    return [m for m in MONTHS_ORDER if m in have]


@router.get("/years", response_model=List[int])
def available_years(db: Session = Depends(get_db)):
    """
    Returns all FY end years, merging:
    1. Years derived from actual data in the records table
    2. All years configured in the fiscal_years registry (including future FYs)

    This means future FYs with no data yet still appear in the selector,
    allowing budget planning and forward navigation.
    """
    # Years from actual data
    rows = db.query(Record.year, Record.month_no).distinct().all()
    fy_years: set[int] = set()
    for cal_year, month_no in rows:
        fy_end = cal_year + 1 if month_no >= 4 else cal_year
        fy_years.add(fy_end)

    # Years from the fiscal_years registry (historical + current + future)
    configured = db.query(FiscalYear.year).all()
    for (y,) in configured:
        fy_years.add(y)

    return sorted(fy_years)


@router.get("/fiscal-years")
def fiscal_years_list(db: Session = Depends(get_db)) -> List[Dict]:
    """
    Enriched list of all configured fiscal years with status badges,
    date ranges, tariff, and budget readiness indicators.
    Used by the frontend FY selector to show CURRENT / FUTURE / HISTORICAL labels.
    """
    from sqlalchemy import func as sqlfunc
    fys = db.query(FiscalYear).order_by(FiscalYear.year.desc()).all()

    # Budget line counts per year
    counts = (db.query(BudgetLine.year, sqlfunc.count().label("n"))
              .group_by(BudgetLine.year).all())
    count_map = {r.year: r.n for r in counts}

    # Years that have actual data
    data_rows = db.query(Record.year, Record.month_no).distinct().all()
    data_years: set[int] = set()
    for cal_year, month_no in data_rows:
        data_years.add(cal_year + 1 if month_no >= 4 else cal_year)

    result = []
    for fy in fys:
        result.append({
            "year":          fy.year,
            "label":         fy.label,
            "start_date":    fy.start_date,
            "end_date":      fy.end_date,
            "status":        fy.status,
            "tariff_per_m3": fy.tariff_per_m3,
            "notes":         fy.notes,
            "has_data":      fy.year in data_years,
            "has_budget":    count_map.get(fy.year, 0) > 0,
            "budget_line_count": count_map.get(fy.year, 0),
        })

    # Also include data-years not yet in the fiscal_years registry
    # (handles historical data uploaded before this feature existed)
    registered = {fy.year for fy in fys}
    for y in sorted(data_years - registered):
        result.append({
            "year":    y,
            "label":   fy_label(y),
            "start_date": f"{y-1}-04-01", "end_date": f"{y}-03-31",
            "status":  "historical",
            "tariff_per_m3": None,
            "notes":   "Auto-detected from data; not in FY registry",
            "has_data":  True,
            "has_budget": False,
            "budget_line_count": 0,
        })

    result.sort(key=lambda x: x["year"], reverse=True)
    return result


@router.get("/data-quality")
def data_quality(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Runs anomaly rules across all records. Results cached for 5 minutes."""
    # Return cached result if still fresh
    cached = _DQ_CACHE.get("result")
    if cached and time.time() - _DQ_CACHE.get("ts", 0) < DQ_CACHE_TTL:
        return cached

    rows = db.query(Record).all()
    issues = []

    for r in rows:
        tag = f"{r.zone} / {r.scheme} / {r.month}"

        if r.total_debtors < -1000:
            issues.append({"sev": "High", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "Total Debtors",
                "value": r.total_debtors,
                "msg": "Negative debtor balance — check debit/credit entries"})

        if r.private_debtors < -1000:
            issues.append({"sev": "High", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "Private Debtors",
                "value": r.private_debtors,
                "msg": "Negative private debtors — overpayment or reversal error"})

        if r.stuck_meters < 0:
            issues.append({"sev": "Medium", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "Stuck Meters C/Fwd",
                "value": r.stuck_meters,
                "msg": "Negative carried-forward — repairs exceed opening balance"})

        if r.staff_costs == 0 and r.active_customers > 500 and r.vol_produced > 0:
            issues.append({"sev": "Medium", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "Staff Costs",
                "value": 0,
                "msg": "Zero staff costs with >500 customers — payroll data missing?"})

        if r.amt_billed > 0 and r.cash_collected > r.amt_billed * 3:
            issues.append({"sev": "Medium", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "Cash Collected",
                "value": r.cash_collected,
                "msg": "Cash collected >3× amount billed — backdated receipts or error"})

        if r.vol_produced == 0 and r.month not in ("January", "February", "March"):
            issues.append({"sev": "Low", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "Vol Produced",
                "value": 0,
                "msg": "No production recorded — data entry gap or dry period"})

        if r.pct_nrw > 0.5 and r.vol_produced > 500:
            issues.append({"sev": "High", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "NRW %",
                "value": round(r.pct_nrw * 100, 1),
                "msg": "NRW exceeds 50% — verify metering or check for pipe losses"})

        if r.revenue_water > r.vol_produced + 1:
            issues.append({"sev": "High", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "Revenue Water",
                "value": r.revenue_water,
                "msg": "Revenue water exceeds total produced — calculation error"})

        if r.nrw < 0:
            issues.append({"sev": "High", "zone": r.zone, "scheme": r.scheme,
                "month": r.month, "field": "NRW (m³)",
                "value": r.nrw,
                "msg": "Negative NRW — revenue water exceeds production"})

    summary = {
        "total": len(issues),
        "high":   sum(1 for i in issues if i["sev"] == "High"),
        "medium": sum(1 for i in issues if i["sev"] == "Medium"),
        "low":    sum(1 for i in issues if i["sev"] == "Low"),
    }

    result = {"summary": summary, "issues": issues}

    # Store in cache
    _DQ_CACHE["result"] = result
    _DQ_CACHE["ts"] = time.time()

    return result
