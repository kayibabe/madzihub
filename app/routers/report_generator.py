"""
routers/report_generator.py — Report Centre
============================================
Eight structured report endpoints for the SRWB Report Centre feature.
Each endpoint accepts query params: year (int), zones (str CSV), months (str CSV).

All endpoints query the actual database via the Record model and reuse the
shared helpers from panels.py (_base, _nz_sum, _nz_avg, _latest, etc.).
Returns plain JSON-serialisable dicts.

Endpoints:
  GET /api/reports/board-pack          — Executive / Board Pack
  GET /api/reports/operations          — Operations Report
  GET /api/reports/financial           — Financial Report
  GET /api/reports/hra                 — HR & Administration (HRA) Report
  GET /api/reports/infrastructure      — Infrastructure & Assets Report
  GET /api/reports/zone-comparison     — Cross-Zone Comparison Table
  GET /api/reports/nrw-analysis        — NRW Analysis Report
  GET /api/reports/scheme-performance  — Per-Scheme Performance Summary
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import BudgetLine, get_db
from app.routers.panels import (
    ZONE_COLORS,
    _base,
    _latest,
    _latest_nonzero,
    _lk,
    _nz_avg,
    _nz_sum,
    _supply_daily,
    _by_zone,
    _monthly,
    _dedupe_rows,
    _filter,
)
from app.utils import MONTHS_ORDER as FY_MONTHS, csv_list

router = APIRouter(prefix="/api/reports", tags=["Report Centre"])

# SRWB NRW target percentage
NRW_TARGET_PCT = 27.0


# ── Internal helpers ───────────────────────────────────────────────────────────

def _trend_series(monthly_rows, value_field):
    """Convert monthly data rows to {month, value} trend dicts (data months only)."""
    return [
        {"month": m["month"], "value": m.get(value_field, 0)}
        for m in monthly_rows
        if m.get("has_data")
    ]


def _zone_rows_map(rows):
    """Group rows by zone, return {zone: [rows]}."""
    zd = defaultdict(list)
    for r in rows:
        zd[r.zone].append(r)
    return zd


def _dso(total_debtors, amt_billed, n_months):
    """Calculate Days Sales Outstanding."""
    if not amt_billed or not n_months:
        return 0
    monthly_rev = amt_billed / n_months
    return round(total_debtors / monthly_rev * 30, 1)


def _fetch_budget(db: Session, year: int):
    """Fetch all BudgetLine rows for a given FY year as a {category: value} dict."""
    if not year:
        return {}
    rows = db.query(BudgetLine).filter(BudgetLine.year == year).all()
    return {r.category: float(r.value) for r in rows}


# ── 1. Board Pack ─────────────────────────────────────────────────────────────

@router.get("/board-pack")
def report_board_pack(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Board Pack — executive KPIs, financial snapshot, zone risks, NRW trend,
    year-vs-prior-year comparison for key metrics.
    """
    rows, bz, mo = _base(zones, None, months, year, db)

    if not rows:
        return {
            "executive_kpis": {},
            "financial_snapshot": {},
            "zone_risks": [],
            "nrw_trend": [],
            "yoy_comparison": {},
        }

    lv = _latest(rows)
    lv_d = _latest_nonzero(rows, "total_debtors")
    data_months = [m for m in mo if m.get("has_data")]
    n_months = max(len(data_months), 1)

    revenue = _nz_sum(rows, "amt_billed")
    cash = _nz_sum(rows, "cash_collected")
    opex = _nz_sum(rows, "op_cost")
    vol_prod = _nz_sum(rows, "vol_produced")
    nrw_vol = _nz_sum(rows, "nrw")
    total_dbt = sum(max(0, r.total_debtors) for r in lv_d)
    active = sum(max(0, r.active_customers) for r in lv) or 1
    pipe_bd = _nz_sum(rows, "pipe_breakdowns")
    pump_bd = _nz_sum(rows, "pump_breakdowns")
    power_kwh = _nz_sum(rows, "power_kwh")
    supply_daily = _supply_daily(rows)

    nrw_pct = round(nrw_vol / vol_prod * 100, 1) if vol_prod else 0
    coll_rate = round(cash / revenue * 100, 1) if revenue else 0
    op_ratio = round(opex / revenue, 2) if revenue else 0
    dso = _dso(total_dbt, revenue, n_months)

    # ── Executive KPIs ─────────────────────────────────────────────
    executive_kpis = {
        "vol_produced": round(vol_prod, 1),
        "revenue": round(revenue, 2),
        "cash_collected": round(cash, 2),
        "collection_rate": coll_rate,
        "collection_rate_flag": "GOOD" if coll_rate >= 90 else ("WATCH" if coll_rate >= 75 else "HIGH"),
        "nrw_pct": nrw_pct,
        "nrw_flag": "GOOD" if nrw_pct <= NRW_TARGET_PCT else "HIGH",
        "active_customers": round(active),
        "total_breakdowns": round(pipe_bd + pump_bd),
        "supply_hours_avg": supply_daily,
        "op_ratio": op_ratio,
        "op_ratio_flag": "GOOD" if op_ratio < 0.8 else ("WATCH" if op_ratio < 1.0 else "HIGH"),
        "dso": dso,
        "dso_flag": "GOOD" if dso < 60 else ("WATCH" if dso < 90 else "HIGH"),
        "energy_intensity": round(power_kwh / vol_prod, 2) if vol_prod else 0,
    }

    # ── Financial Snapshot ─────────────────────────────────────────
    financial_snapshot = {
        "total_revenue": round(revenue, 2),
        "cash_collected": round(cash, 2),
        "collection_rate": coll_rate,
        "op_costs": round(opex, 2),
        "op_ratio": op_ratio,
        "total_debtors": round(total_dbt, 2),
        "dso": dso,
        "net_surplus": round(revenue - opex, 2),
        "net_margin_pct": round((revenue - opex) / revenue * 100, 1) if revenue else 0,
    }

    # ── Top 3 Zone Risks (NRW %, then DSO) ───────────────────────
    zone_risk_list = []
    zrm = _zone_rows_map(rows)
    for z in bz:
        zn = z["zone"]
        zr = zrm.get(zn, [])
        z_rev = z.get("amt_billed", 0) or 0
        z_nm = max(len(set(_lk(r) for r in zr)), 1)
        z_dbt = z.get("total_debtors", 0) or 0
        z_dso = _dso(z_dbt, z_rev, z_nm)
        zone_risk_list.append({
            "zone": zn,
            "color": z.get("color", "#64748b"),
            "nrw_pct": z.get("nrw_pct", 0),
            "dso": z_dso,
            "collection_rate": z.get("collection_rate", 0),
            "risk_score": (z.get("nrw_pct", 0) / NRW_TARGET_PCT) + (z_dso / 90.0),
        })
    top_zone_risks = sorted(zone_risk_list, key=lambda x: x["risk_score"], reverse=True)[:3]

    # ── NRW Trend (12 months) ─────────────────────────────────────
    nrw_trend = _trend_series(mo, "pct_nrw")

    # ── Year-on-Year Comparison ───────────────────────────────────
    yoy_comparison = {}
    if year:
        prior_rows, prior_bz, _ = _base(zones, None, months, year - 1, db)
        if prior_rows:
            p_rev = _nz_sum(prior_rows, "amt_billed")
            p_cash = _nz_sum(prior_rows, "cash_collected")
            p_vol = _nz_sum(prior_rows, "vol_produced")
            p_nrw = _nz_sum(prior_rows, "nrw")
            p_opex = _nz_sum(prior_rows, "op_cost")
            yoy_comparison = {
                "prior_year": year - 1,
                "current_year": year,
                "revenue": {
                    "current": round(revenue, 2),
                    "prior": round(p_rev, 2),
                    "change_pct": round((revenue - p_rev) / p_rev * 100, 1) if p_rev else 0,
                },
                "cash_collected": {
                    "current": round(cash, 2),
                    "prior": round(p_cash, 2),
                    "change_pct": round((cash - p_cash) / p_cash * 100, 1) if p_cash else 0,
                },
                "vol_produced": {
                    "current": round(vol_prod, 1),
                    "prior": round(p_vol, 1),
                    "change_pct": round((vol_prod - p_vol) / p_vol * 100, 1) if p_vol else 0,
                },
                "nrw_pct": {
                    "current": nrw_pct,
                    "prior": round(p_nrw / p_vol * 100, 1) if p_vol else 0,
                },
                "op_costs": {
                    "current": round(opex, 2),
                    "prior": round(p_opex, 2),
                    "change_pct": round((opex - p_opex) / p_opex * 100, 1) if p_opex else 0,
                },
            }

    return {
        "year": year,
        "zones_filter": csv_list(zones),
        "months_filter": csv_list(months),
        "executive_kpis": executive_kpis,
        "financial_snapshot": financial_snapshot,
        "zone_risks": top_zone_risks,
        "nrw_trend": nrw_trend,
        "yoy_comparison": yoy_comparison,
        "by_zone": [
            {
                "zone": z["zone"],
                "color": z.get("color", "#64748b"),
                "vol_produced": z.get("vol_produced", 0),
                "nrw_pct": z.get("nrw_pct", 0),
                "collection_rate": z.get("collection_rate", 0),
                "active_customers": z.get("active_customers", 0),
                "op_ratio": round(z.get("op_cost", 0) / z.get("amt_billed", 1), 2) if z.get("amt_billed") else 0,
            }
            for z in bz
        ],
    }


# ── 2. Operations Report ──────────────────────────────────────────────────────

@router.get("/operations")
def report_operations(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Operations Report — production summary (total, by zone, monthly trend),
    NRW breakdown, treatment energy intensity, breakdowns, supply hours,
    pipe extensions.
    """
    rows, bz, mo = _base(zones, None, months, year, db)

    vol_prod = _nz_sum(rows, "vol_produced")
    nrw_vol = _nz_sum(rows, "nrw")
    nrw_pct = round(nrw_vol / vol_prod * 100, 2) if vol_prod else 0
    power_kwh = _nz_sum(rows, "power_kwh")
    supply_daily = _supply_daily(rows)

    # production summary
    production_summary = {
        "total_vol_produced": round(vol_prod, 1),
        "revenue_water": round(_nz_sum(rows, "revenue_water"), 1),
        "nrw_vol": round(nrw_vol, 1),
        "nrw_pct": nrw_pct,
        "power_kwh": round(power_kwh, 1),
        "power_cost": round(_nz_sum(rows, "power_cost"), 2),
        "energy_intensity_kwh_m3": round(_nz_avg(rows, "power_kwh_per_m3"), 3),
        "chem_cost": round(_nz_sum(rows, "chem_cost"), 2),
        "chem_cost_per_m3": round(_nz_sum(rows, "chem_cost") / vol_prod, 3) if vol_prod else 0,
        "supply_hours_avg_daily": supply_daily,
        "power_fail_hours": round(_nz_sum(rows, "power_fail_hours")),
        "pipe_breakdowns": round(_nz_sum(rows, "pipe_breakdowns")),
        "pump_breakdowns": round(_nz_sum(rows, "pump_breakdowns")),
        "dev_lines_total": round(_nz_sum(rows, "dev_lines_total")),
    }

    # NRW breakdown by zone
    nrw_by_zone = [
        {
            "zone": z["zone"],
            "color": z.get("color", "#64748b"),
            "vol_produced": z.get("vol_produced", 0),
            "nrw_vol": z.get("nrw", 0),
            "nrw_pct": z.get("nrw_pct", 0),
            "above_target": z.get("nrw_pct", 0) > NRW_TARGET_PCT,
        }
        for z in bz
    ]

    # Treatment energy intensity by zone
    energy_by_zone = [
        {
            "zone": z["zone"],
            "color": z.get("color", "#64748b"),
            "power_kwh": z.get("power_kwh", 0),
            "power_cost": z.get("power_cost", 0),
            "energy_intensity_kwh_m3": z.get("power_kwh_per_m3", 0),
            "chem_cost": z.get("chem_cost", 0),
            "chlorine_kg_per_m3": z.get("chlorine_kg_per_m3", 0),
            "alum_kg_per_m3": z.get("alum_kg_per_m3", 0),
        }
        for z in bz
    ]

    # Breakdowns by zone
    breakdowns_by_zone = [
        {
            "zone": z["zone"],
            "color": z.get("color", "#64748b"),
            "pipe_breakdowns": z.get("pipe_breakdowns", 0),
            "pump_breakdowns": z.get("pump_breakdowns", 0),
            "total": (z.get("pipe_breakdowns", 0) or 0) + (z.get("pump_breakdowns", 0) or 0),
            "pump_hours_lost": z.get("pump_hours_lost", 0),
        }
        for z in bz
    ]

    # Pipeline extensions by size
    pipe_extensions = {
        "dev_lines_32mm": round(_nz_sum(rows, "dev_lines_32mm")),
        "dev_lines_50mm": round(_nz_sum(rows, "dev_lines_50mm")),
        "dev_lines_63mm": round(_nz_sum(rows, "dev_lines_63mm")),
        "dev_lines_90mm": round(_nz_sum(rows, "dev_lines_90mm")),
        "dev_lines_110mm": round(_nz_sum(rows, "dev_lines_110mm")),
        "dev_lines_total": round(_nz_sum(rows, "dev_lines_total")),
    }

    # Monthly production trend
    production_trend = [
        {
            "month": m["month"],
            "vol_produced": m.get("vol_produced", 0),
            "nrw_pct": m.get("pct_nrw", 0),
            "supply_hours": m.get("supply_hours", 0),
        }
        for m in mo
        if m.get("has_data")
    ]

    return {
        "year": year,
        "production_summary": production_summary,
        "production_by_zone": [
            {
                "zone": z["zone"],
                "color": z.get("color", "#64748b"),
                "vol_produced": z.get("vol_produced", 0),
                "nrw_pct": z.get("nrw_pct", 0),
                "supply_hours_avg": z.get("supply_hours", 0),
            }
            for z in bz
        ],
        "production_trend": production_trend,
        "nrw_by_zone": nrw_by_zone,
        "energy_intensity_by_zone": energy_by_zone,
        "breakdowns_by_zone": breakdowns_by_zone,
        "pipe_extensions": pipe_extensions,
    }


# ── 3. Financial Report ───────────────────────────────────────────────────────

@router.get("/financial")
def report_financial(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Financial Report — total revenue, collection rate, operating costs, op ratio,
    DSO, debtors by zone, billed vs collected trend, budget variance if available.
    """
    rows, bz, mo = _base(zones, None, months, year, db)
    lv_d = _latest_nonzero(rows, "total_debtors")
    data_months = [m for m in mo if m.get("has_data")]
    n_months = max(len(data_months), 1)

    revenue = _nz_sum(rows, "amt_billed")
    cash = _nz_sum(rows, "cash_collected")
    opex = _nz_sum(rows, "op_cost")
    total_dbt = sum(max(0, r.total_debtors) for r in lv_d)
    coll_rate = round(cash / revenue * 100, 1) if revenue else 0
    op_ratio = round(opex / revenue, 2) if revenue else 0
    dso = _dso(total_dbt, revenue, n_months)

    # Budget variance (if available)
    budget_variance = {}
    if year:
        budget = _fetch_budget(db, year)
        if budget:
            bud_rev = budget.get("water_sales", 0)
            bud_cash = budget.get("cash_collected", 0)
            bud_opex = budget.get("op_cost", 0)
            budget_variance = {
                "revenue": {
                    "actual": round(revenue, 2),
                    "budget": round(bud_rev, 2),
                    "variance": round(revenue - bud_rev, 2),
                    "variance_pct": round((revenue - bud_rev) / bud_rev * 100, 1) if bud_rev else 0,
                },
                "cash_collected": {
                    "actual": round(cash, 2),
                    "budget": round(bud_cash, 2),
                    "variance": round(cash - bud_cash, 2),
                    "variance_pct": round((cash - bud_cash) / bud_cash * 100, 1) if bud_cash else 0,
                },
                "op_cost": {
                    "actual": round(opex, 2),
                    "budget": round(bud_opex, 2),
                    "variance": round(opex - bud_opex, 2),
                    "variance_pct": round((opex - bud_opex) / bud_opex * 100, 1) if bud_opex else 0,
                },
            }

    # Debtors by zone
    debtors_by_zone = [
        {
            "zone": z["zone"],
            "color": z.get("color", "#64748b"),
            "total_debtors": z.get("total_debtors", 0),
            "private_debtors": z.get("private_debtors", 0),
            "public_debtors": z.get("public_debtors", 0),
            "debtors_to_billed_pct": round(
                z.get("total_debtors", 0) / z.get("amt_billed", 1) * 100, 1
            ) if z.get("amt_billed") else 0,
        }
        for z in bz
    ]

    # Billed vs collected trend
    billed_collected_trend = [
        {
            "month": m["month"],
            "amt_billed": m.get("amt_billed", 0),
            "cash_collected": m.get("cash_collected", 0),
            "collection_rate": m.get("collection_rate", 0),
        }
        for m in mo
        if m.get("has_data")
    ]

    # Cost breakdown
    cost_breakdown = {
        "op_cost": round(opex, 2),
        "staff_costs": round(_nz_sum(rows, "staff_costs"), 2),
        "wages": round(_nz_sum(rows, "wages"), 2),
        "power_cost": round(_nz_sum(rows, "power_cost"), 2),
        "chem_cost": round(_nz_sum(rows, "chem_cost"), 2),
        "fuel_cost": round(_nz_sum(rows, "fuel_cost"), 2),
        "maintenance": round(_nz_sum(rows, "maintenance"), 2),
        "other_overhead": round(_nz_sum(rows, "other_overhead"), 2),
    }

    return {
        "year": year,
        "summary": {
            "total_revenue": round(revenue, 2),
            "cash_collected": round(cash, 2),
            "collection_rate": coll_rate,
            "collection_rate_flag": "GOOD" if coll_rate >= 90 else ("WATCH" if coll_rate >= 75 else "HIGH"),
            "op_costs": round(opex, 2),
            "op_ratio": op_ratio,
            "op_ratio_flag": "GOOD" if op_ratio < 0.8 else ("WATCH" if op_ratio < 1.0 else "HIGH"),
            "total_debtors": round(total_dbt, 2),
            "dso": dso,
            "dso_flag": "GOOD" if dso < 60 else ("WATCH" if dso < 90 else "HIGH"),
            "net_surplus": round(revenue - opex, 2),
            "service_charge": round(_nz_sum(rows, "service_charge"), 2),
            "meter_rental": round(_nz_sum(rows, "meter_rental"), 2),
            "total_sales": round(_nz_sum(rows, "total_sales"), 2),
        },
        "by_zone": [
            {
                "zone": z["zone"],
                "color": z.get("color", "#64748b"),
                "amt_billed": z.get("amt_billed", 0),
                "cash_collected": z.get("cash_collected", 0),
                "collection_rate": z.get("collection_rate", 0),
                "op_cost": z.get("op_cost", 0),
                "total_debtors": z.get("total_debtors", 0),
            }
            for z in bz
        ],
        "cost_breakdown": cost_breakdown,
        "debtors_by_zone": debtors_by_zone,
        "billed_collected_trend": billed_collected_trend,
        "budget_variance": budget_variance,
    }


# ── 4. HRA Report ─────────────────────────────────────────────────────────────

@router.get("/hra")
def report_hra(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    HR & Administration (HRA) Report — permanent + temporary staff by zone,
    staff efficiency (m³ per staff), wages, fuel used, fleet metrics.
    """
    rows, bz, mo = _base(zones, None, months, year, db)
    lv = _latest(rows)

    perm = sum(r.perm_staff for r in lv)
    temp = sum(r.temp_staff for r in lv)
    total_staff = (perm + temp) or 1
    vol_prod = _nz_sum(rows, "vol_produced")
    wages = _nz_sum(rows, "wages")
    staff_costs = _nz_sum(rows, "staff_costs")
    fuel_litres = _nz_sum(rows, "fuel_used_litres")
    fuel_cost = _nz_sum(rows, "fuel_cost")
    dist_km = _nz_sum(rows, "distances_km")
    # Active connections (latest balance) and revenue (derived from by-zone
    # billing) for the industry-standard HR ratios.
    active = sum(max(0, r.active_customers) for r in lv)
    revenue = sum((z.get("amt_billed", 0) or 0) for z in bz)
    total_payroll = staff_costs + wages

    summary = {
        "perm_staff": round(perm),
        "temp_staff": round(temp),
        "total_staff": round(perm + temp),
        "active_customers": round(active),
        # IBNET-standard staffing ratio: employees per 1,000 active connections.
        "staff_per_1000_conn": round((perm + temp) / active * 1000, 1) if active else 0,
        "staff_per_1000m3_12h": round(_nz_avg(rows, "staff_per_1000m3_12h"), 3),
        "m3_per_staff": round(vol_prod / total_staff, 1),
        "wages": round(wages, 2),
        "staff_costs": round(staff_costs, 2),
        "total_payroll": round(total_payroll, 2),
        # Payroll (staff costs + wages) as a share of operating revenue.
        "payroll_cost_ratio": round(total_payroll / revenue * 100, 1) if revenue else 0,
        "wages_per_staff": round(wages / total_staff, 2),
        "fuel_used_litres": round(fuel_litres, 1),
        "fuel_cost": round(fuel_cost, 2),
        "distances_km": round(dist_km, 1),
        "fuel_per_km": round(fuel_litres / dist_km, 2) if dist_km else 0,
        "maintenance": round(_nz_sum(rows, "maintenance"), 2),
    }

    # Staff by zone
    staff_by_zone = []
    for z in bz:
        zn = z["zone"]
        zr = _zone_rows_map(rows).get(zn, [])
        zlv = _latest(zr)
        z_perm = sum(r.perm_staff for r in zlv)
        z_temp = sum(r.temp_staff for r in zlv)
        z_vol = z.get("vol_produced", 0) or 0
        z_total = (z_perm + z_temp) or 1
        staff_by_zone.append({
            "zone": zn,
            "color": z.get("color", "#64748b"),
            "perm_staff": round(z_perm),
            "temp_staff": round(z_temp),
            "total_staff": round(z_perm + z_temp),
            "m3_per_staff": round(z_vol / z_total, 1),
            "wages": z.get("wages", 0),
            "staff_costs": z.get("staff_costs", 0),
            "fuel_used_litres": z.get("fuel_used_litres", 0),
            "fuel_cost": z.get("fuel_cost", 0),
            "distances_km": z.get("distances_km", 0),
        })

    # Staff trend
    staff_trend = [
        {
            "month": m["month"],
            "perm_staff": m.get("perm_staff", 0),
            "temp_staff": m.get("temp_staff", 0),
            "wages": m.get("wages", 0),
            "staff_costs": m.get("staff_costs", 0),
        }
        for m in mo
        if m.get("has_data")
    ]

    # Fuel trend
    fuel_trend = [
        {
            "month": m["month"],
            "fuel_used_litres": m.get("fuel_used_litres", 0),
            "fuel_cost": m.get("fuel_cost", 0),
            "distances_km": m.get("distances_km", 0),
        }
        for m in mo
        if m.get("has_data")
    ]

    return {
        "year": year,
        "summary": summary,
        "staff_by_zone": staff_by_zone,
        "staff_trend": staff_trend,
        "fuel_trend": fuel_trend,
    }


# ── 5. Infrastructure Report ──────────────────────────────────────────────────

@router.get("/infrastructure")
def report_infrastructure(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Infrastructure & Assets Report — total breakdowns (pipe + pump by zone),
    pipeline extensions by size, stuck meters, pump hours lost,
    power failure hours, supply continuity.
    """
    rows, bz, mo = _base(zones, None, months, year, db)
    lv = _latest(rows)

    pipe_bd = _nz_sum(rows, "pipe_breakdowns")
    pump_bd = _nz_sum(rows, "pump_breakdowns")
    active = sum(max(0, r.active_customers) for r in lv) or 1
    stuck = sum(max(0, r.stuck_meters) for r in lv)
    metered = sum(max(0, r.total_metered) for r in lv)

    summary = {
        "pipe_breakdowns": round(pipe_bd),
        "pump_breakdowns": round(pump_bd),
        "total_breakdowns": round(pipe_bd + pump_bd),
        "breakdowns_per_1k_customers": round((pipe_bd + pump_bd) / active * 1000, 1),
        "pump_hours_lost": round(_nz_sum(rows, "pump_hours_lost")),
        "power_fail_hours": round(_nz_sum(rows, "power_fail_hours")),
        "supply_hours_avg_daily": _supply_daily(rows),
        "stuck_meters": round(stuck),
        "stuck_new": round(_nz_sum(rows, "stuck_new")),
        "stuck_repaired": round(_nz_sum(rows, "stuck_repaired")),
        "stuck_pct": round(stuck / metered * 100, 1) if metered else 0,
        "dev_lines_total": round(_nz_sum(rows, "dev_lines_total")),
        "total_metered": round(metered),
        # total_metered is the full metered connection base (active +
        # disconnected). Active Connection Ratio = active share of that base;
        # the remainder are disconnected/inactive meters (revenue at risk).
        "active_conn_ratio": round(active / metered * 100, 1) if metered else 0,
    }

    # Breakdowns by zone
    breakdowns_by_zone = [
        {
            "zone": z["zone"],
            "color": z.get("color", "#64748b"),
            "pipe_breakdowns": z.get("pipe_breakdowns", 0),
            "pump_breakdowns": z.get("pump_breakdowns", 0),
            "total_breakdowns": (z.get("pipe_breakdowns", 0) or 0) + (z.get("pump_breakdowns", 0) or 0),
            "pump_hours_lost": z.get("pump_hours_lost", 0),
            "pipe_pvc": z.get("pipe_pvc", 0),
            "pipe_gi": z.get("pipe_gi", 0),
            "pipe_di": z.get("pipe_di", 0),
            "pipe_hdpe_ac": z.get("pipe_hdpe_ac", 0),
        }
        for z in bz
    ]

    # Pipeline extensions by size
    pipeline_extensions = [
        {"size": "32mm", "metres": round(_nz_sum(rows, "dev_lines_32mm"))},
        {"size": "50mm", "metres": round(_nz_sum(rows, "dev_lines_50mm"))},
        {"size": "63mm", "metres": round(_nz_sum(rows, "dev_lines_63mm"))},
        {"size": "90mm", "metres": round(_nz_sum(rows, "dev_lines_90mm"))},
        {"size": "110mm", "metres": round(_nz_sum(rows, "dev_lines_110mm"))},
    ]

    # PVC breakdown by pipe size
    pvc_by_size = [
        {"size": "20mm", "count": round(_nz_sum(rows, "pvc_20mm"))},
        {"size": "25mm", "count": round(_nz_sum(rows, "pvc_25mm"))},
        {"size": "32mm", "count": round(_nz_sum(rows, "pvc_32mm"))},
        {"size": "40mm", "count": round(_nz_sum(rows, "pvc_40mm"))},
        {"size": "50mm", "count": round(_nz_sum(rows, "pvc_50mm"))},
        {"size": "63mm", "count": round(_nz_sum(rows, "pvc_63mm"))},
        {"size": "75mm", "count": round(_nz_sum(rows, "pvc_75mm"))},
        {"size": "90mm", "count": round(_nz_sum(rows, "pvc_90mm"))},
        {"size": "110mm", "count": round(_nz_sum(rows, "pvc_110mm"))},
        {"size": "160mm", "count": round(_nz_sum(rows, "pvc_160mm"))},
        {"size": "200mm", "count": round(_nz_sum(rows, "pvc_200mm"))},
    ]

    # Infrastructure trend
    infra_trend = [
        {
            "month": m["month"],
            "pipe_breakdowns": m.get("pipe_breakdowns", 0),
            "pump_breakdowns": m.get("pump_breakdowns", 0),
            "supply_hours": m.get("supply_hours", 0),
            "power_fail_hours": m.get("power_fail_hours", 0),
            "stuck_meters": m.get("stuck_meters", 0),
        }
        for m in mo
        if m.get("has_data")
    ]

    return {
        "year": year,
        "summary": summary,
        "breakdowns_by_zone": breakdowns_by_zone,
        "pipeline_extensions": pipeline_extensions,
        "pvc_breakdowns_by_size": pvc_by_size,
        "infrastructure_trend": infra_trend,
    }


# ── 6. Zone Comparison ────────────────────────────────────────────────────────

@router.get("/zone-comparison")
def report_zone_comparison(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Cross-Zone Comparison Table — for each zone:
    vol_produced, NRW%, collection_rate, active_customers,
    breakdowns, DSO, op_cost_per_m3.
    """
    rows, bz, mo = _base(zones, None, months, year, db)
    data_months = [m for m in mo if m.get("has_data")]
    zrm = _zone_rows_map(rows)

    comparison_table = []
    for z in bz:
        zn = z["zone"]
        zr = zrm.get(zn, [])
        z_rev = z.get("amt_billed", 0) or 0
        z_nm = max(len(set(_lk(r) for r in zr)), 1)
        z_dbt = z.get("total_debtors", 0) or 0
        z_dso = _dso(z_dbt, z_rev, z_nm)
        z_vol = z.get("vol_produced", 0) or 0
        z_opex = z.get("op_cost", 0) or 0

        comparison_table.append({
            "zone": zn,
            "color": z.get("color", "#64748b"),
            "vol_produced": z.get("vol_produced", 0),
            "nrw_pct": z.get("nrw_pct", 0),
            "nrw_flag": "GOOD" if z.get("nrw_pct", 0) <= NRW_TARGET_PCT else "HIGH",
            "collection_rate": z.get("collection_rate", 0),
            "collection_flag": "GOOD" if z.get("collection_rate", 0) >= 90 else ("WATCH" if z.get("collection_rate", 0) >= 75 else "HIGH"),
            "active_customers": z.get("active_customers", 0),
            "pipe_breakdowns": z.get("pipe_breakdowns", 0),
            "pump_breakdowns": z.get("pump_breakdowns", 0),
            "total_breakdowns": (z.get("pipe_breakdowns", 0) or 0) + (z.get("pump_breakdowns", 0) or 0),
            "dso": z_dso,
            "dso_flag": "GOOD" if z_dso < 60 else ("WATCH" if z_dso < 90 else "HIGH"),
            "op_cost": z.get("op_cost", 0),
            "op_cost_per_m3": round(z_opex / z_vol, 2) if z_vol else 0,
            "amt_billed": z.get("amt_billed", 0),
            "cash_collected": z.get("cash_collected", 0),
            "total_debtors": z.get("total_debtors", 0),
            "staff_per_1000m3_12h": z.get("staff_per_1000m3_12h", 0),
        })

    # Totals row
    total_vol = sum(z.get("vol_produced", 0) or 0 for z in bz)
    total_nrw = _nz_sum(rows, "nrw")
    total_rev = _nz_sum(rows, "amt_billed")
    total_cash = _nz_sum(rows, "cash_collected")
    lv_all = _latest(rows)
    lv_d_all = _latest_nonzero(rows, "total_debtors")
    total_active = sum(max(0, r.active_customers) for r in lv_all)
    total_dbt_all = sum(max(0, r.total_debtors) for r in lv_d_all)
    total_opex = _nz_sum(rows, "op_cost")
    n_months = max(len(data_months), 1)

    totals = {
        "zone": "TOTAL",
        "color": "#374151",
        "vol_produced": round(total_vol, 1),
        "nrw_pct": round(total_nrw / total_vol * 100, 1) if total_vol else 0,
        "collection_rate": round(total_cash / total_rev * 100, 1) if total_rev else 0,
        "active_customers": round(total_active),
        "pipe_breakdowns": round(_nz_sum(rows, "pipe_breakdowns")),
        "pump_breakdowns": round(_nz_sum(rows, "pump_breakdowns")),
        "total_breakdowns": round(_nz_sum(rows, "pipe_breakdowns") + _nz_sum(rows, "pump_breakdowns")),
        "dso": _dso(total_dbt_all, total_rev, n_months),
        "op_cost": round(total_opex, 2),
        "op_cost_per_m3": round(total_opex / total_vol, 2) if total_vol else 0,
        "amt_billed": round(total_rev, 2),
        "cash_collected": round(total_cash, 2),
        "total_debtors": round(total_dbt_all, 2),
    }

    return {
        "year": year,
        "comparison_table": comparison_table,
        "totals": totals,
        "nrw_target": NRW_TARGET_PCT,
    }


# ── 7. NRW Analysis ───────────────────────────────────────────────────────────

@router.get("/nrw-analysis")
def report_nrw_analysis(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    NRW Analysis — NRW volume and % by zone, monthly NRW trend,
    NRW components, zones above/below SRWB 27% target.
    """
    rows, bz, mo = _base(zones, None, months, year, db)

    vol_prod = _nz_sum(rows, "vol_produced")
    nrw_vol = _nz_sum(rows, "nrw")
    rev_water = _nz_sum(rows, "revenue_water")
    nrw_pct = round(nrw_vol / vol_prod * 100, 1) if vol_prod else 0

    # Estimate NRW cost using average tariff
    vol_billed = (
        _nz_sum(rows, "total_vol_billed_pp")
        + _nz_sum(rows, "total_vol_billed_prepaid")
    )
    amt_billed = _nz_sum(rows, "amt_billed")
    avg_tariff = round(amt_billed / vol_billed, 2) if vol_billed else 0
    nrw_cost_estimate = round(nrw_vol * avg_tariff, 2)

    summary = {
        "vol_produced": round(vol_prod, 1),
        "revenue_water": round(rev_water, 1),
        "nrw_vol": round(nrw_vol, 1),
        "nrw_pct": nrw_pct,
        "srwb_target_pct": NRW_TARGET_PCT,
        "above_target": nrw_pct > NRW_TARGET_PCT,
        "nrw_cost_estimate": nrw_cost_estimate,
        "avg_tariff": avg_tariff,
        "vol_billed": round(vol_billed, 1),
    }

    # NRW by zone with target flags
    nrw_by_zone = []
    zones_above = []
    zones_below = []
    for z in bz:
        zn = z["zone"]
        z_nrw = z.get("nrw_pct", 0)
        above = z_nrw > NRW_TARGET_PCT
        entry = {
            "zone": zn,
            "color": z.get("color", "#64748b"),
            "vol_produced": z.get("vol_produced", 0),
            "nrw_vol": z.get("nrw", 0),
            "nrw_pct": z_nrw,
            "above_target": above,
            "distance_from_target": round(z_nrw - NRW_TARGET_PCT, 1),
        }
        nrw_by_zone.append(entry)
        if above:
            zones_above.append(zn)
        else:
            zones_below.append(zn)

    # NRW component breakdown (physical vs commercial loss proxy).
    # NRW = produced − billed. The split into physical (leaks/bursts) vs
    # commercial (meter under-reading, illegal use, billing errors) losses is
    # indicative. We split NRW itself so the two components always sum to NRW
    # (an earlier formula subtracted revenue_water as well, producing a
    # "physical" component larger than total NRW). Physical losses are assumed
    # to be the dominant share (~75%) absent a dedicated water-balance audit.
    PHYSICAL_LOSS_SHARE = 0.75
    physical_loss_proxy = max(0, round(nrw_vol * PHYSICAL_LOSS_SHARE, 1))
    commercial_loss_proxy = max(0, round(nrw_vol - physical_loss_proxy, 1))

    nrw_components = {
        "total_nrw": round(nrw_vol, 1),
        "physical_loss_proxy": round(physical_loss_proxy, 1),
        "commercial_loss_proxy": round(commercial_loss_proxy, 1),
        "note": "Indicative split: physical losses assumed ~75% of NRW pending a full water-balance audit. Components sum to total NRW.",
    }

    # Monthly NRW trend
    nrw_trend = [
        {
            "month": m["month"],
            "nrw_vol": m.get("nrw", 0),
            "nrw_pct": m.get("pct_nrw", 0),
            "vol_produced": m.get("vol_produced", 0),
            "above_target": (m.get("pct_nrw", 0) or 0) > NRW_TARGET_PCT,
        }
        for m in mo
        if m.get("has_data")
    ]

    return {
        "year": year,
        "summary": summary,
        "nrw_by_zone": nrw_by_zone,
        "zones_above_target": zones_above,
        "zones_below_target": zones_below,
        "nrw_components": nrw_components,
        "nrw_trend": nrw_trend,
        "nrw_target": NRW_TARGET_PCT,
    }


# ── 8. Scheme Performance ─────────────────────────────────────────────────────

@router.get("/scheme-performance")
def report_scheme_performance(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Per-Scheme Performance Summary — for each scheme in the selected zone(s):
    production, NRW%, active customers, collections, breakdowns.
    """
    rows, _, mo = _base(zones, None, months, year, db)
    lv = _latest(rows)
    lv_d = _latest_nonzero(rows, "total_debtors")

    # Group rows by (zone, scheme)
    scheme_rows: dict = defaultdict(list)
    for r in rows:
        scheme_rows[(r.zone, r.scheme)].append(r)

    # Build latest-per-scheme lookups
    lv_by_scheme: dict = defaultdict(list)
    for r in lv:
        lv_by_scheme[(r.zone, r.scheme)].append(r)

    lvd_by_scheme: dict = defaultdict(list)
    for r in lv_d:
        lvd_by_scheme[(r.zone, r.scheme)].append(r)

    # Aggregate per scheme
    scheme_summaries = []
    for (zone, scheme), sr in sorted(scheme_rows.items()):
        slv = lv_by_scheme.get((zone, scheme), [])
        slv_d = lvd_by_scheme.get((zone, scheme), [])

        s_vol = _nz_sum(sr, "vol_produced")
        s_nrw = _nz_sum(sr, "nrw")
        s_nrw_pct = round(s_nrw / s_vol * 100, 1) if s_vol else 0
        s_billed = _nz_sum(sr, "amt_billed")
        s_cash = _nz_sum(sr, "cash_collected")
        s_active = sum(max(0, r.active_customers) for r in slv)
        s_dbt = sum(max(0, r.total_debtors) for r in slv_d)
        s_pipe_bd = _nz_sum(sr, "pipe_breakdowns")
        s_pump_bd = _nz_sum(sr, "pump_breakdowns")
        s_opex = _nz_sum(sr, "op_cost")
        s_n_months = max(len(set(_lk(r) for r in sr)), 1)
        s_perm = sum(r.perm_staff for r in slv)
        s_temp = sum(r.temp_staff for r in slv)

        scheme_summaries.append({
            "zone": zone,
            "zone_color": ZONE_COLORS.get(zone, "#64748b"),
            "scheme": scheme,
            "vol_produced": round(s_vol, 1),
            "nrw_vol": round(s_nrw, 1),
            "nrw_pct": s_nrw_pct,
            "nrw_flag": "GOOD" if s_nrw_pct <= NRW_TARGET_PCT else "HIGH",
            "active_customers": round(s_active),
            "amt_billed": round(s_billed, 2),
            "cash_collected": round(s_cash, 2),
            "collection_rate": round(s_cash / s_billed * 100, 1) if s_billed else 0,
            "total_debtors": round(s_dbt, 2),
            "dso": _dso(s_dbt, s_billed, s_n_months),
            "pipe_breakdowns": round(s_pipe_bd),
            "pump_breakdowns": round(s_pump_bd),
            "total_breakdowns": round(s_pipe_bd + s_pump_bd),
            "op_cost": round(s_opex, 2),
            "op_cost_per_m3": round(s_opex / s_vol, 2) if s_vol else 0,
            "perm_staff": round(s_perm),
            "temp_staff": round(s_temp),
            "supply_hours_avg": _supply_daily(sr),
            "months_with_data": s_n_months,
        })

    # Totals
    total_vol = _nz_sum(rows, "vol_produced")
    total_nrw = _nz_sum(rows, "nrw")
    total_rev = _nz_sum(rows, "amt_billed")
    total_cash = _nz_sum(rows, "cash_collected")
    total_active = sum(max(0, r.active_customers) for r in lv)
    total_dbt = sum(max(0, r.total_debtors) for r in lv_d)
    total_opex = _nz_sum(rows, "op_cost")
    data_months = [m for m in mo if m.get("has_data")]
    n_months = max(len(data_months), 1)

    totals = {
        "scheme_count": len(scheme_summaries),
        "vol_produced": round(total_vol, 1),
        "nrw_pct": round(total_nrw / total_vol * 100, 1) if total_vol else 0,
        "active_customers": round(total_active),
        "amt_billed": round(total_rev, 2),
        "cash_collected": round(total_cash, 2),
        "collection_rate": round(total_cash / total_rev * 100, 1) if total_rev else 0,
        "total_debtors": round(total_dbt, 2),
        "dso": _dso(total_dbt, total_rev, n_months),
        "total_breakdowns": round(_nz_sum(rows, "pipe_breakdowns") + _nz_sum(rows, "pump_breakdowns")),
        "op_cost": round(total_opex, 2),
    }

    return {
        "year": year,
        "zones_filter": csv_list(zones),
        "schemes": scheme_summaries,
        "totals": totals,
        "nrw_target": NRW_TARGET_PCT,
    }


# ── 9. AI Performance Scorecard ───────────────────────────────────────────────

@router.get("/scorecard")
def report_scorecard(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    AI Performance Scorecard — letter grades (A–F) for 5 KPI domains:
    Financial Health, Water Operations, Infrastructure, Customer Service, Workforce.
    Each domain includes contributing metrics, score (0–100), and grade.
    """
    rows, bz, mo = _base(zones, None, months, year, db)

    if not rows:
        return {"domains": [], "overall_grade": "N/A", "overall_score": 0}

    lv = _latest(rows)
    lv_d = _latest_nonzero(rows, "total_debtors")
    data_months = [m for m in mo if m.get("has_data")]
    n_months = max(len(data_months), 1)

    revenue = _nz_sum(rows, "amt_billed")
    cash = _nz_sum(rows, "cash_collected")
    opex = _nz_sum(rows, "op_cost")
    vol_prod = _nz_sum(rows, "vol_produced")
    nrw_vol = _nz_sum(rows, "nrw")
    total_dbt = sum(max(0, r.total_debtors) for r in lv_d)
    active = sum(max(0, r.active_customers) for r in lv) or 1
    stuck = sum(max(0, r.stuck_meters) for r in lv)
    metered = sum(max(0, r.total_metered) for r in lv) or 1
    pipe_bd = _nz_sum(rows, "pipe_breakdowns")
    pump_bd = _nz_sum(rows, "pump_breakdowns")
    perm = sum(r.perm_staff for r in lv)
    temp = sum(r.temp_staff for r in lv)
    total_staff = (perm + temp) or 1
    supply_daily = _supply_daily(rows)
    dtc_avg = _nz_avg(rows, "days_to_connect", cap=365)

    nrw_pct = round(nrw_vol / vol_prod * 100, 1) if vol_prod else 0
    coll_rate = round(cash / revenue * 100, 1) if revenue else 0
    op_ratio = round(opex / revenue, 2) if revenue else 0
    dso = _dso(total_dbt, revenue, n_months)
    stuck_pct = round(stuck / metered * 100, 1) if metered else 0
    bd_per_1k = round((pipe_bd + pump_bd) / active * 1000, 1)
    m3_per_staff = round(vol_prod / total_staff, 1)
    staff_per_1k = round(total_staff / active * 1000, 1)

    def _grade(score):
        if score >= 85: return "A"
        if score >= 70: return "B"
        if score >= 55: return "C"
        if score >= 40: return "D"
        return "F"

    def _score_coll(v):     return min(100, max(0, round((v - 50) / 50 * 100)))
    def _score_nrw(v):      return min(100, max(0, round((70 - v) / 43 * 100)))
    def _score_op_ratio(v): return min(100, max(0, round((1.5 - v) / 0.7 * 100)))
    def _score_dso(v):      return min(100, max(0, round((180 - v) / 120 * 100)))
    def _score_supply(v):   return min(100, max(0, round(v / 24 * 100)))
    def _score_bd(v):       return min(100, max(0, round((200 - v) / 200 * 100)))
    def _score_stuck(v):    return min(100, max(0, round((20 - v) / 20 * 100)))
    def _score_dtc(v):      return min(100, max(0, round((90 - v) / 60 * 100))) if v else 80
    def _score_m3staff(v):  return min(100, max(0, round(min(v, 5000) / 5000 * 100)))
    def _score_staff1k(v):  return min(100, max(0, round((15 - v) / 12 * 100)))

    fin_score = round((_score_coll(coll_rate) * 0.35 + _score_op_ratio(op_ratio) * 0.35 + _score_dso(dso) * 0.30))
    ops_score = round((_score_nrw(nrw_pct) * 0.50 + _score_supply(supply_daily) * 0.30 + 70 * 0.20))
    inf_score = round((_score_bd(bd_per_1k) * 0.60 + _score_stuck(stuck_pct) * 0.40))
    svc_score = round((_score_dtc(dtc_avg) * 0.50 + min(100, active / 1000) * 0.50))
    hrf_score = round((_score_m3staff(m3_per_staff) * 0.50 + _score_staff1k(staff_per_1k) * 0.50))

    domains = [
        {
            "id": "financial",
            "title": "Financial Health",
            "score": fin_score,
            "grade": _grade(fin_score),
            "metrics": [
                {"name": "Collection Rate",   "value": f"{coll_rate}%",         "benchmark": ">90% (IBNET)",        "flag": "GOOD" if coll_rate >= 90 else ("WATCH" if coll_rate >= 75 else "HIGH")},
                {"name": "Operating Ratio",   "value": f"{op_ratio:.2f}",        "benchmark": "<0.80 (World Bank)", "flag": "GOOD" if op_ratio < 0.80 else ("WATCH" if op_ratio < 1.0 else "HIGH")},
                {"name": "DSO (days)",         "value": f"{dso:.0f}d",            "benchmark": "<90d (IBNET)",       "flag": "GOOD" if dso < 60 else ("WATCH" if dso < 90 else "HIGH")},
            ],
        },
        {
            "id": "operations",
            "title": "Water Operations",
            "score": ops_score,
            "grade": _grade(ops_score),
            "metrics": [
                {"name": "NRW Rate",           "value": f"{nrw_pct}%",           "benchmark": "<27% (SRWB target)", "flag": "GOOD" if nrw_pct <= 27 else ("WATCH" if nrw_pct <= 35 else "HIGH")},
                {"name": "Supply Hours/Day",   "value": f"{supply_daily:.1f}h",  "benchmark": "≥20h/day",           "flag": "GOOD" if supply_daily >= 20 else ("WATCH" if supply_daily >= 16 else "HIGH")},
                {"name": "Vol Produced (m³)",  "value": f"{vol_prod:,.0f}",      "benchmark": "YTD total",          "flag": ""},
            ],
        },
        {
            "id": "infrastructure",
            "title": "Infrastructure",
            "score": inf_score,
            "grade": _grade(inf_score),
            "metrics": [
                {"name": "Breakdowns/1k Cust","value": f"{bd_per_1k:.1f}",      "benchmark": "<10 (IBNET)",        "flag": "GOOD" if bd_per_1k < 10 else ("WATCH" if bd_per_1k < 20 else "HIGH")},
                {"name": "Stuck Meters",       "value": f"{stuck_pct:.1f}% of meters","benchmark": "<8% (target)", "flag": "GOOD" if stuck_pct < 5 else ("WATCH" if stuck_pct < 8 else "HIGH")},
            ],
        },
        {
            "id": "service",
            "title": "Customer Service",
            "score": svc_score,
            "grade": _grade(svc_score),
            "metrics": [
                {"name": "Active Customers",   "value": f"{active:,}",           "benchmark": "YTD snapshot",       "flag": ""},
                {"name": "Days to Connect",    "value": f"{dtc_avg:.0f}d" if dtc_avg else "N/A", "benchmark": "<30d (World Bank)", "flag": "GOOD" if dtc_avg and dtc_avg < 30 else ("WATCH" if dtc_avg and dtc_avg < 60 else ("HIGH" if dtc_avg else ""))},
            ],
        },
        {
            "id": "workforce",
            "title": "Workforce",
            "score": hrf_score,
            "grade": _grade(hrf_score),
            "metrics": [
                {"name": "m³/Staff",           "value": f"{m3_per_staff:,.0f}",  "benchmark": "Higher = better",    "flag": ""},
                {"name": "Staff/1k Connections","value": f"{staff_per_1k:.1f}",  "benchmark": "<5 (IBNET)",         "flag": "GOOD" if staff_per_1k < 5 else ("WATCH" if staff_per_1k < 10 else "HIGH")},
                {"name": "Total Staff",         "value": str(int(perm + temp)),   "benchmark": f"Perm: {int(perm)}, Temp: {int(temp)}", "flag": ""},
            ],
        },
    ]

    overall = round(sum(d["score"] for d in domains) / len(domains))
    return {
        "year": year,
        "zones_filter": csv_list(zones),
        "domains": domains,
        "overall_score": overall,
        "overall_grade": _grade(overall),
        "nrw_target": NRW_TARGET_PCT,
    }


# ── 10. AI Recommendations ────────────────────────────────────────────────────

@router.get("/recommendations")
def report_recommendations(
    year: Optional[int] = Query(None),
    zones: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    AI Recommendations — rule-based prioritised action items derived from
    KPI analysis. Groups findings into Critical / Warning / Monitoring tiers
    with specific, measurable recommendations for SRWB operational context.
    """
    from app.services.insights_engine import generate_alerts
    alerts_data = generate_alerts(db=db, year=year)
    alerts = alerts_data.get("alerts", [])
    kpi = alerts_data.get("kpi_snapshot", {})

    rows, bz, _ = _base(zones, None, months, year, db)
    lv = _latest(rows)

    critical = [a for a in alerts if a["severity"] == "critical"]
    warnings  = [a for a in alerts if a["severity"] == "warning"]
    info      = [a for a in alerts if a["severity"] == "info"]

    def _mk_action(alert):
        cat = alert["category"]
        sev = alert["severity"]
        base = {
            "title":    alert["title"],
            "detail":   alert["detail"],
            "category": cat,
            "severity": sev,
            "zone":     alert.get("zone"),
            "metric":   alert.get("metric"),
            "value":    alert.get("value"),
        }
        # Enrich with SRWB-specific action guidance
        if cat == "nrw":
            base["actions"] = [
                "Deploy district metered area (DMA) monitoring to identify leakage hotspots",
                "Increase meter reading frequency in high-NRW zones",
                "Schedule targeted pipe replacement for aged GI/AC mains",
                "Investigate illegal connections in areas with high commercial NRW",
            ]
        elif cat == "financial":
            base["actions"] = [
                "Launch debtor recovery drive targeting arrears >90 days",
                "Review tariff collection processes in underperforming zones",
                "Implement pre-payment metering for chronic defaulters",
                "Escalate public institution debtors to finance/legal for recovery",
            ]
        elif cat == "operations":
            base["actions"] = [
                "Review breakdowns log for recurring failure locations",
                "Prioritise preventive maintenance schedule for high-failure zones",
                "Check pump efficiency and scheduling to reduce power costs",
                "Audit supply hours reporting for data quality issues",
            ]
        elif cat == "service":
            base["actions"] = [
                "Review new connection application backlog and staffing",
                "Audit stuck meter inventory and escalate repairs",
                "Check if meter reading routes cover all registered accounts",
                "Verify customer database accuracy against field surveys",
            ]
        else:
            base["actions"] = ["Review data, investigate root cause, and escalate to management."]
        return base

    recommendations = {
        "critical": [_mk_action(a) for a in critical],
        "warning":  [_mk_action(a) for a in warnings],
        "monitoring": [_mk_action(a) for a in info],
        "summary": {
            "critical_count": len(critical),
            "warning_count":  len(warnings),
            "info_count":     len(info),
            "total_count":    len(alerts),
        },
        "kpi_snapshot": kpi,
    }

    return {
        "year": year,
        "zones_filter": csv_list(zones),
        "recommendations": recommendations,
    }
