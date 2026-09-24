"""
routers/analytics.py

Pre-aggregated analytic endpoints — these do the heavy lifting so the
frontend receives ready-to-render numbers rather than raw rows.

GET /api/analytics/kpi          — overall KPI summary (respects filters)
GET /api/analytics/monthly      — monthly pivot (12-col array, one row per metric)
GET /api/analytics/by-zone      — per-zone totals for selected period
GET /api/analytics/by-scheme    — per-scheme totals
GET /api/analytics/nrw-trend    — NRW % month-by-month per zone
GET /api/analytics/customers    — customer pivot for the Customers Report page
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import Record, get_db
from app.utils import MONTHS_ORDER, apply_fy_filter, csv_list

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

# Single source of truth for zone colours — also defined in panels.py.
# Both must be kept in sync if zones are added or renamed.
# Long-term, consider a zones catalogue table in the DB.
ZONE_COLORS = {
    "Liwonde": "#0077b6", "Mangochi": "#0d9488",
    "Mulanje": "#16a34a", "Ngabu": "#d97706", "Zomba": "#7c3aed",
}



# ── shared filter helper ──────────────────────────────────────
def _filter(q, zones=None, schemes=None, months=None, quarters=None, year=None):
    if zones:    q = q.filter(Record.zone.in_(zones))
    if schemes:  q = q.filter(Record.scheme.in_(schemes))
    if months:   q = q.filter(Record.month.in_(months))
    if quarters: q = q.filter(Record.quarter.in_(quarters))
    if year:
        q = apply_fy_filter(q, year)
    return q




# ── KPI summary ───────────────────────────────────────────────
@router.get("/kpi")
def kpi_summary(
    zones: Optional[str] = Query(None),
    schemes: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    quarters: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:

    rows = _filter(
        db.query(Record), csv_list(zones), csv_list(schemes),
        csv_list(months), csv_list(quarters), year
    ).all()

    if not rows:
        return {"total_records": 0}

    vol   = sum(r.vol_produced  for r in rows)
    rw    = sum(r.revenue_water for r in rows)
    nrw_v = sum(r.nrw           for r in rows)
    cash  = sum(r.cash_collected for r in rows)
    billed= sum(r.amt_billed    for r in rows)
    opex  = sum(r.op_cost       for r in rows)
    conn  = sum(r.new_connections for r in rows)

    # Active customers & debtors: latest snapshot per scheme
    # Smart selection: prefer rows with actual data over empty stub rows,
    # and for debtors specifically prefer last non-zero balance.
    latest_any: Dict[str, Record] = {}
    latest_data: Dict[str, Record] = {}
    latest_dbt: Dict[str, Record] = {}
    for r in rows:
        k = (r.zone, r.scheme)
        if k not in latest_any or (r.year, r.month_no) > (latest_any[k].year, latest_any[k].month_no):
            latest_any[k] = r
        has_data = (r.active_customers or 0) > 0 or (r.vol_produced or 0) > 0 or (r.amt_billed or 0) > 0
        if has_data and (k not in latest_data or (r.year, r.month_no) > (latest_data[k].year, latest_data[k].month_no)):
            latest_data[k] = r
        if (r.total_debtors or 0) != 0 and (k not in latest_dbt or (r.year, r.month_no) > (latest_dbt[k].year, latest_dbt[k].month_no)):
            latest_dbt[k] = r
    lv_stock  = [latest_data.get(k, latest_any[k]) for k in latest_any]
    lv_debtor = [latest_dbt.get(k, latest_any[k])  for k in latest_any]
    active  = sum(max(0, r.active_customers) for r in lv_stock)
    debtors = sum(max(0, r.total_debtors)   for r in lv_debtor)

    chem   = sum(r.chem_cost   for r in rows)
    power  = sum(r.power_cost  for r in rows)
    sales  = sum(r.total_sales     for r in rows)
    svc    = sum(r.service_charge  for r in rows)
    meter  = sum(r.meter_rental    for r in rows)
    # Stuck meters: latest snapshot per scheme
    stuck  = sum(max(0, r.stuck_meters) for r in latest_any.values())
    # Population served: latest snapshot per scheme
    pop    = sum(max(0, r.pop_supplied) for r in latest_any.values())
    # Supply hours: average across schemes that reported > 0
    sh_vals = [r.supply_hours for r in rows if r.supply_hours and r.supply_hours > 0]
    supply_avg = sum(sh_vals) / len(sh_vals) if sh_vals else 0

    return {
        "total_records":  len(rows),
        "vol_produced":   round(vol, 1),
        "revenue_water":  round(rw, 1),
        "nrw_m3":         round(nrw_v, 1),
        "nrw_pct":        round(nrw_v / vol * 100, 2) if vol else 0,
        "active_customers": round(active),
        "new_connections":  round(conn),
        "cash_collected":   round(cash, 2),
        "amt_billed":       round(billed, 2),
        "collection_rate":  round(cash / billed * 100, 2) if billed else 0,
        "op_cost":          round(opex, 2),
        "total_debtors":    round(debtors, 2),
        "total_sales":      round(sales, 2),
        "service_charge":   round(svc, 2),
        "meter_rental":     round(meter, 2),
        "chem_cost":        round(chem, 2),
        "power_cost":       round(power, 2),
        "stuck_meters":     round(stuck),
        "supply_hours_avg": round(supply_avg, 1),
        "pop_supplied":     round(pop),
    }


# ── Monthly pivot ─────────────────────────────────────────────
@router.get("/monthly")
def monthly_pivot(
    zones: Optional[str] = Query(None),
    schemes: Optional[str] = Query(None),
    quarters: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Returns one dict per month in FY order with summed/latest metrics."""

    rows = _filter(
        db.query(Record), csv_list(zones), csv_list(schemes),
        None, csv_list(quarters), year
    ).all()

    # Group by month
    by_month: Dict[str, List[Record]] = defaultdict(list)
    for r in rows:
        by_month[r.month].append(r)

    result = []
    for month in MONTHS_ORDER:
        mrows = by_month.get(month, [])
        if not mrows:
            result.append({"month": month, "has_data": False})
            continue

        # Latest per scheme for stock metrics
        latest: Dict[str, Record] = {}
        for r in mrows:
            k = (r.zone, r.scheme)
            if k not in latest or (r.year, r.month_no) > (latest[k].year, latest[k].month_no):
                latest[k] = r
        lv = list(latest.values())

        # Mark as no-data if all records have zero production AND zero customers
        # (handles Q4 placeholder rows imported from Excel with no data yet)
        total_vol = sum(r.vol_produced for r in mrows)
        total_cust = sum(r.active_customers for r in lv)
        if total_vol == 0 and total_cust == 0:
            result.append({"month": month, "has_data": False})
            continue

        result.append({
            "month":            month,
            "has_data":         True,
            "vol_produced":     round(sum(r.vol_produced  for r in mrows), 1),
            "revenue_water":    round(sum(r.revenue_water for r in mrows), 1),
            "nrw":              round(sum(r.nrw           for r in mrows), 1),
            "pct_nrw":          round(sum(r.nrw for r in mrows) / sum(r.vol_produced for r in mrows) * 100, 2)
                                if sum(r.vol_produced for r in mrows) else 0,
            "active_customers": round(sum(r.active_customers for r in lv)),
            "active_postpaid":  round(sum(r.active_postpaid  for r in lv)),
            "active_prepaid":   round(sum(r.active_prepaid   for r in lv)),
            "new_connections":  round(sum(r.new_connections  for r in mrows)),
            "cash_collected":   round(sum(r.cash_collected   for r in mrows), 2),
            "amt_billed":       round(sum(r.amt_billed       for r in mrows), 2),
            "op_cost":          round(sum(r.op_cost          for r in mrows), 2),
            "chem_cost":        round(sum(r.chem_cost        for r in mrows), 2),
            "power_cost":       round(sum(r.power_cost       for r in mrows), 2),
            "power_kwh":        round(sum(r.power_kwh        for r in mrows), 1),
            "fuel_cost":        round(sum(r.fuel_cost        for r in mrows), 2),
            "staff_costs":      round(sum(r.staff_costs      for r in mrows), 2),
            "perm_staff":       round(sum(r.perm_staff       for r in lv)),
            "temp_staff":       round(sum(r.temp_staff       for r in lv)),
            "power_fail_hours": round(sum(r.power_fail_hours for r in mrows)),
            "supply_hours":     round(sum(r.supply_hours     for r in mrows) / max(len(mrows),1), 1),
            "pipe_breakdowns":  round(sum(r.pipe_breakdowns  for r in mrows)),
            "pump_breakdowns":  round(sum(r.pump_breakdowns  for r in mrows)),
            "stuck_meters":     round(sum(max(0, r.stuck_meters)  for r in lv)),
            "stuck_repaired":   round(sum(r.stuck_repaired        for r in mrows)),
            "stuck_new":        round(sum(r.stuck_new             for r in mrows)),
            "total_debtors":    round(sum(max(0, r.total_debtors) for r in lv), 2),
            "pop_supplied":     round(sum(r.pop_supplied     for r in lv)),
            "service_charge":   round(sum(r.service_charge   for r in mrows), 2),
            "meter_rental":     round(sum(r.meter_rental     for r in mrows), 2),
            "total_sales":      round(sum(r.total_sales      for r in mrows), 2),
            "conn_applied":     round(sum(r.conn_applied     for r in mrows)),
            "days_to_connect":  round(sum(r.days_to_connect  for r in mrows) / max(len(mrows),1), 1),
            "all_conn_applied": round(sum(r.all_conn_applied for r in mrows)),
            "all_conn_cfwd":    round(sum(r.all_conn_cfwd    for r in lv)),
        })

    return result


# ── By-zone totals ────────────────────────────────────────────
@router.get("/by-zone")
def by_zone(
    zones: Optional[str] = Query(None),
    schemes: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    quarters: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:

    rows = _filter(
        db.query(Record), csv_list(zones), csv_list(schemes),
        csv_list(months), csv_list(quarters), year
    ).all()

    zone_data: Dict[str, List[Record]] = defaultdict(list)
    for r in rows:
        zone_data[r.zone].append(r)

    result = []
    for zone, zrows in sorted(zone_data.items()):
        latest_any: Dict[str, Record] = {}
        latest_data: Dict[str, Record] = {}
        latest_dbt: Dict[str, Record] = {}
        for r in zrows:
            k = r.scheme
            if k not in latest_any or (r.year, r.month_no) > (latest_any[k].year, latest_any[k].month_no):
                latest_any[k] = r
            has_data = (r.active_customers or 0) > 0 or (r.vol_produced or 0) > 0 or (r.amt_billed or 0) > 0
            if has_data and (k not in latest_data or (r.year, r.month_no) > (latest_data[k].year, latest_data[k].month_no)):
                latest_data[k] = r
            if (r.total_debtors or 0) != 0 and (k not in latest_dbt or (r.year, r.month_no) > (latest_dbt[k].year, latest_dbt[k].month_no)):
                latest_dbt[k] = r
        lv      = [latest_data.get(k, latest_any[k]) for k in latest_any]
        lv_dbt  = [latest_dbt.get(k,  latest_any[k]) for k in latest_any]
        vol = sum(r.vol_produced for r in zrows)
        nrw = sum(r.nrw          for r in zrows)
        result.append({
            "zone":             zone,
            "color":            ZONE_COLORS.get(zone, "#64748b"),
            "schemes":          len(set(r.scheme for r in zrows)),
            "vol_produced":     round(vol, 1),
            "nrw_pct":          round(nrw / vol * 100, 2) if vol else 0,
            "active_customers": round(sum(r.active_customers for r in lv)),
            "active_postpaid":  round(sum(r.active_postpaid  for r in lv)),
            "active_prepaid":   round(sum(r.active_prepaid   for r in lv)),
            "new_connections":  round(sum(r.new_connections  for r in zrows)),
            "cash_collected":   round(sum(r.cash_collected   for r in zrows), 2),
            "amt_billed":       round(sum(r.amt_billed       for r in zrows), 2),
            "op_cost":          round(sum(r.op_cost          for r in zrows), 2),
            "chem_cost":        round(sum(r.chem_cost        for r in zrows), 2),
            "power_cost":       round(sum(r.power_cost       for r in zrows), 2),
            "power_kwh":        round(sum(r.power_kwh        for r in zrows), 1),
            "fuel_cost":        round(sum(r.fuel_cost        for r in zrows), 2),
            "perm_staff":       round(sum(r.perm_staff       for r in lv)),
            "temp_staff":       round(sum(r.temp_staff       for r in lv)),
            "pipe_breakdowns":  round(sum(r.pipe_breakdowns  for r in zrows)),
            "stuck_meters":     round(sum(max(0, r.stuck_meters) for r in lv)),
            "total_debtors":    round(sum(max(0, r.total_debtors) for r in lv_dbt), 2),
        })

    return result


# ── By-scheme totals ──────────────────────────────────────────
@router.get("/by-scheme")
def by_scheme(
    zones: Optional[str] = Query(None),
    schemes: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    quarters: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:

    rows = _filter(
        db.query(Record), csv_list(zones), csv_list(schemes),
        csv_list(months), csv_list(quarters), year
    ).all()

    sch_data: Dict[str, List[Record]] = defaultdict(list)
    for r in rows:
        sch_data[(r.zone, r.scheme)].append(r)

    result = []
    for (zone, scheme), srows in sorted(sch_data.items()):
        latest = max(srows, key=lambda r: r.month_no)
        vol = sum(r.vol_produced for r in srows)
        nrw = sum(r.nrw          for r in srows)
        result.append({
            "zone":             zone,
            "scheme":           scheme,
            "months_reported":  len(srows),
            "vol_produced":     round(vol, 1),
            "nrw_pct":          round(nrw / vol * 100, 2) if vol else 0,
            "active_customers": round(latest.active_customers),
            "active_postpaid":  round(latest.active_postpaid),
            "active_prepaid":   round(latest.active_prepaid),
            "new_connections":  round(sum(r.new_connections for r in srows)),
            "cash_collected":   round(sum(r.cash_collected  for r in srows), 2),
            "amt_billed":       round(sum(r.amt_billed      for r in srows), 2),
            "op_cost":          round(sum(r.op_cost         for r in srows), 2),
            "total_debtors":    round(max(0, latest.total_debtors), 2),
            "stuck_meters":     round(max(0, latest.stuck_meters)),
            "perm_staff":       round(latest.perm_staff),
            "temp_staff":       round(latest.temp_staff),
            "pipe_breakdowns":  round(sum(r.pipe_breakdowns for r in srows)),
        })

    return result


# ── NRW trend by zone ─────────────────────────────────────────
@router.get("/nrw-trend")
def nrw_trend(
    zones: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:

    rows = _filter(db.query(Record), csv_list(zones), None, None, None, year).all()

    zone_month: Dict[str, Dict[str, tuple]] = defaultdict(lambda: defaultdict(lambda: (0.0, 0.0)))
    for r in rows:
        vol, nrw = zone_month[r.zone][r.month]
        zone_month[r.zone][r.month] = (vol + r.vol_produced, nrw + r.nrw)

    series = {}
    for zone, months in zone_month.items():
        series[zone] = [
            {
                "month": m,
                "pct_nrw": round(nrw / vol * 100, 2) if vol else 0
            }
            for m, (vol, nrw) in sorted(months.items(), key=lambda x: MONTHS_ORDER.index(x[0]) if x[0] in MONTHS_ORDER else 99)
        ]

    return {"months": MONTHS_ORDER, "series": series}


# ── Customer pivot for Reports page ──────────────────────────
@router.get("/customers")
def customer_pivot(
    zones: Optional[str] = Query(None),
    schemes: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Monthly customer metrics — drives the Customers Report pivot table."""

    rows = _filter(
        db.query(Record), csv_list(zones), csv_list(schemes),
        csv_list(months), None, year
    ).all()

    by_month: Dict[str, List[Record]] = defaultdict(list)
    for r in rows:
        by_month[r.month].append(r)

    result = []
    for month in MONTHS_ORDER:
        mrows = by_month.get(month, [])
        if not mrows:
            result.append({"month": month, "has_data": False})
            continue

        latest: Dict[str, Record] = {}
        for r in mrows:
            k = (r.zone, r.scheme)
            if k not in latest or (r.year, r.month_no) > (latest[k].year, latest[k].month_no):
                latest[k] = r
        lv = list(latest.values())

        active   = sum((r.active_customers or 0) for r in lv)
        if active == 0 and sum((r.vol_produced or 0) for r in mrows) == 0:
            result.append({"month": month, "has_data": False})
            continue
        postpaid = sum((r.active_postpaid  or 0) for r in lv)
        prepaid  = sum((r.active_prepaid   or 0) for r in lv)
        amt_billed     = sum((r.amt_billed     or 0) for r in mrows)
        cash_collected = sum((r.cash_collected or 0) for r in mrows)
        service_charge = sum((r.service_charge or 0) for r in mrows)
        meter_rental   = sum((r.meter_rental   or 0) for r in mrows)

        result.append({
            "month":            month,
            "has_data":         True,
            "active_customers": round(active),
            "active_postpaid":  round(postpaid),
            "active_prepaid":   round(prepaid),
            "postpaid_pct":     round(postpaid / active * 100, 1) if active else 0,
            "prepaid_pct":      round(prepaid  / active * 100, 1) if active else 0,
            "new_connections":  round(sum((r.new_connections or 0) for r in mrows)),
            "pop_supplied":     round(sum((r.pop_supplied    or 0) for r in lv)),
            "amt_billed":       round(amt_billed, 2),
            "cash_collected":   round(cash_collected, 2),
            "service_charge":   round(service_charge, 2),
            "meter_rental":     round(meter_rental, 2),
            "collection_rate":  round(cash_collected / amt_billed * 100, 1) if amt_billed else 0,
        })

    return result
