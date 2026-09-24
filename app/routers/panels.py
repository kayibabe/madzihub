"""
routers/panels.py — v4 (comprehensive data + UX fix)

Changes from v3:
  - _nz_avg() helper: averages only non-zero values with optional outlier cap
    (fixes days_to_connect inflation from Mangochi data-entry error)
  - _monthly() now returns ALL fields needed by every page's table and charts
  - All panel endpoints now return "monthly": mo (full data, no field filtering)
    so tables never get '—' from a missing key
  - supply_hours averaged over non-zero schemes per month
  - expenses panel now includes "monthly": mo
"""
from __future__ import annotations
from collections import defaultdict
from types import SimpleNamespace
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, Integer, Numeric
from sqlalchemy.orm import Session
from app.database import Record, get_db
from app.utils import MONTHS_ORDER as FY_MONTHS, apply_fy_filter, csv_list

router = APIRouter(prefix="/api/panels", tags=["Panels"])

ZONE_COLORS = {
    "Liwonde":"#0077b6","Mangochi":"#0d9488",
    "Mulanje":"#16a34a","Ngabu":"#d97706","Zomba":"#7c3aed",
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _lk(r): return (r.year, r.month_no)

def _filter(q, zones=None, schemes=None, months=None, year=None):
    if zones:   q = q.filter(Record.zone.in_(zones))
    if schemes: q = q.filter(Record.scheme.in_(schemes))
    if months:  q = q.filter(Record.month.in_(months))
    if year:
        q = apply_fy_filter(q, year)
    return q


def _latest(rows):
    """Latest known snapshot per (zone, scheme), with stock balances carried
    forward.

    Stock/balance fields (active customers, metered, debtors, population,
    staff, connection balances, etc.) are typically recorded in only one
    month and left blank/zero afterwards. A naive "latest row" loses the
    balance whenever a later month carries flow data (production, billing) but
    no fresh stock snapshot — which made e.g. Active Customers collapse to 0
    under multi-month scopes.

    This returns, per (zone, scheme), a synthesized row that carries forward
    each numeric field's most recent NON-ZERO value (falling back to the
    latest row's value). For single-month scopes there is one row per key, so
    carry-forward is a no-op and per-month values are preserved.
    """
    cols = [c.name for c in Record.__table__.columns]
    groups = defaultdict(list)
    for r in rows:
        groups[(r.zone, r.scheme)].append(r)
    result = []
    for grp in groups.values():
        grp.sort(key=_lk)                 # ascending by (year, month_no)
        latest = grp[-1]
        snap = {c: getattr(latest, c, None) for c in cols}
        for c in cols:
            for r in reversed(grp):       # newest first
                v = getattr(r, c, None)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                    snap[c] = v
                    break
        result.append(SimpleNamespace(**snap))
    return result


def _latest_nonzero(rows, field):
    """Latest row per (zone, scheme) where `field` is non-zero and non-null.
    Used for stock balance metrics (debtors, stuck meters) where a missing
    entry is recorded as 0 but the prior balance is still the correct value.
    Falls back to _latest() for any scheme that never had a non-zero value."""
    lv_nz  = {}   # latest row where field != 0
    lv_any = {}   # fallback: latest regardless
    for r in rows:
        k = (r.zone, r.scheme)
        if k not in lv_any or _lk(r) > _lk(lv_any[k]):
            lv_any[k] = r
        v = getattr(r, field, None)
        if v is not None and v != 0 and (k not in lv_nz or _lk(r) > _lk(lv_nz[k])):
            lv_nz[k] = r
    merged = {k: lv_nz.get(k, lv_any[k]) for k in lv_any}
    return list(merged.values())

def _nz_avg(rows, field, cap=None):
    """Average of non-zero values; optionally cap outliers before averaging."""
    vals = []
    for r in rows:
        v = getattr(r, field, 0) or 0
        if v > 0 and (cap is None or v <= cap):
            vals.append(v)
    return sum(vals)/len(vals) if vals else 0

def _nz_sum(rows, field):
    return sum(getattr(r, field, 0) or 0 for r in rows)


def _supply_daily(rows):
    """Average daily supply hours, normalising a mixed source unit.

    Some zones record ``supply_hours`` as a daily figure (<=24 h/day) while
    others (e.g. Liwonde) record a monthly total (up to ~744 h). Converting
    every value with a blanket ÷30.44 understated continuity ~6x and badged
    healthy utilities as CRITICAL. Here each row is normalised individually:
    a monthly-scale value (>31) is divided to a daily rate, a daily value is
    kept as-is, and the result is capped at 24 h/day before averaging the
    non-zero rows.
    """
    daily = []
    for r in rows:
        v = getattr(r, "supply_hours", 0) or 0
        if v <= 0:
            continue
        d = (v / 30.44) if v > 31 else v
        daily.append(min(24.0, d))
    return round(sum(daily) / len(daily), 1) if daily else 0


CHEM_INTENSITY_FIELDS = [
    'chlorine_kg_per_m3', 'alum_kg_per_m3', 'soda_ash_kg_per_m3',
    'algae_floc_per_m3', 'sud_floc_per_m3', 'kmno4_per_m3',
]
CUSTOMER_VOLUME_FIELDS = [
    'vol_billed_indiv_pp', 'vol_billed_cwp_pp', 'vol_billed_inst_pp', 'vol_billed_comm_pp',
    'vol_billed_indiv_prepaid', 'vol_billed_cwp_prepaid', 'vol_billed_inst_prepaid', 'vol_billed_comm_prepaid',
]
CONNECTION_FLOW_FIELDS = [
    'conn_indiv_applied_pp', 'conn_indiv_done_pp', 'conn_indiv_done_prepaid', 'conn_indiv_total_done',
    'conn_inst_applied_pp', 'conn_inst_done_pp', 'conn_inst_done_prepaid', 'conn_inst_total_done',
    'conn_comm_applied_pp', 'conn_comm_done_pp', 'conn_comm_done_prepaid', 'conn_comm_total_done',
    'conn_cwp_applied_pp', 'conn_cwp_done_pp', 'conn_cwp_done_prepaid', 'conn_cwp_total_done',
]
CONNECTION_STOCK_FIELDS = [
    'conn_indiv_bfwd', 'conn_indiv_cfwd',
    'conn_inst_bfwd', 'conn_inst_cfwd',
    'conn_comm_bfwd', 'conn_comm_cfwd',
    'conn_cwp_bfwd', 'conn_cwp_cfwd',
]
STUCK_FLOW_FIELDS = [
    'stuck_indiv_new', 'stuck_indiv_repaired', 'stuck_indiv_replaced',
    'stuck_inst_new', 'stuck_inst_repaired', 'stuck_inst_replaced',
    'stuck_comm_new', 'stuck_comm_repaired', 'stuck_comm_replaced',
    'stuck_cwp_new', 'stuck_cwp_repaired', 'stuck_cwp_replaced',
]
STUCK_STOCK_FIELDS = [
    'all_stuck_cfwd',
    'stuck_indiv_bfwd', 'stuck_indiv_cfwd',
    'stuck_inst_bfwd', 'stuck_inst_cfwd',
    'stuck_comm_bfwd', 'stuck_comm_cfwd',
    'stuck_cwp_bfwd', 'stuck_cwp_cfwd',
]
SEGMENT_REVENUE_FIELDS = [
    'cash_coll_indiv_pp', 'cash_coll_cwp_pp', 'cash_coll_comm_pp', 'cash_coll_inst_pp',
    'cash_coll_indiv_prepaid', 'cash_coll_cwp_prepaid', 'cash_coll_comm_prepaid', 'cash_coll_inst_prepaid',
    'amt_billed_indiv_pp', 'amt_billed_cwp_pp', 'amt_billed_inst_pp', 'amt_billed_comm_pp',
    'amt_billed_indiv_prepaid', 'amt_billed_cwp_prepaid', 'amt_billed_inst_prepaid', 'amt_billed_comm_prepaid',
    'service_charge_individual', 'service_charge_cwp', 'service_charge_institutions', 'service_charge_commercial',
    'meter_rental_individual', 'meter_rental_cwp', 'meter_rental_institutions', 'meter_rental_commercial',
]
PIPE_MATERIAL_SIZE_FIELDS = [
    'gi_15mm', 'gi_20mm', 'gi_25mm', 'gi_40mm', 'gi_50mm', 'gi_75mm', 'gi_100mm', 'gi_150mm', 'gi_200mm',
    'di_150mm', 'di_200mm', 'di_250mm', 'di_300mm', 'di_350mm', 'di_525mm',
    'hdpe_20mm', 'hdpe_25mm', 'hdpe_32mm', 'hdpe_50mm',
    'ac_50mm', 'ac_75mm', 'ac_100mm', 'ac_150mm',
]
WORKFORCE_EFFICIENCY_FIELDS = [
    'distances_km', 'fuel_used_litres', 'fuel_cost', 'maintenance',
    'perm_staff', 'temp_staff', 'staff_per_1000m3_12h',
    'op_cost_per_m3_produced', 'op_cost_per_m3_billed', 'op_cost_per_sales',
]


def _sum_field_map(rows, fields, digits=2):
    return {field: round(_nz_sum(rows, field), digits) for field in fields}


def _latest_field_map(rows, fields, digits=2):
    return {field: round(sum(getattr(r, field, 0) or 0 for r in rows), digits) for field in fields}


def _avg_field_map(rows, fields, cap=None, digits=3):
    return {field: round(_nz_avg(rows, field, cap=cap), digits) for field in fields}


# ── by_zone aggregation ────────────────────────────────────────────────────

def _by_zone(rows):
    zd = defaultdict(list)
    for r in rows: zd[r.zone].append(r)
    result = []
    for zone, zrows in sorted(zd.items()):
        lv   = _latest(zrows)
        lv_d = _latest_nonzero(zrows, 'total_debtors')  # debtor-aware latest
        vol = _nz_sum(zrows, 'vol_produced')
        nrw = _nz_sum(zrows, 'nrw')
        ch  = _nz_sum(zrows, 'chem_cost')
        pw  = _nz_sum(zrows, 'power_cost')
        bi  = _nz_sum(zrows, 'amt_billed')
        ca  = _nz_sum(zrows, 'cash_collected')
        _d_ind  = round(sum(r.disconnected_individual for r in lv))
        _d_inst = round(sum(r.disconnected_inst       for r in lv))
        _d_comm = round(sum(r.disconnected_commercial for r in lv))
        _d_cwp  = round(sum(r.disconnected_cwp        for r in lv))
        _d_raw  = round(sum(r.total_disconnected      for r in lv))
        entry = {
            "zone": zone, "color": ZONE_COLORS.get(zone,"#64748b"),
            "vol_produced":      round(vol,1),
            "revenue_water":     round(_nz_sum(zrows,'revenue_water'),1),
            "nrw":               round(nrw,1),
            "nrw_pct":           round(nrw/vol*100,2) if vol else 0,
            "total_metered":     round(sum(r.total_metered for r in lv)),
            "total_disconnected":      _d_raw or (_d_ind + _d_inst + _d_comm + _d_cwp),
            "disconnected_individual": _d_ind,
            "disconnected_inst":       _d_inst,
            "disconnected_commercial": _d_comm,
            "disconnected_cwp":        _d_cwp,
            "active_customers":  round(sum(r.active_customers  for r in lv)),
            "active_postpaid":   round(sum(r.active_postpaid   for r in lv)),
            "active_prepaid":    round(sum(r.active_prepaid    for r in lv)),
            "active_post_cwp":   round(sum(r.active_post_cwp   for r in lv)),
            "active_prep_cwp":   round(sum(r.active_prep_cwp   for r in lv)),
            "pop_supply_area":   round(sum(r.pop_supply_area   for r in lv)),
            "pop_supplied":      round(sum(r.pop_supplied      for r in lv)),
            "pct_pop_supplied":  round((sum(r.pop_supplied for r in lv) / sum(r.pop_supply_area for r in lv) * 100), 1) if sum(r.pop_supply_area for r in lv) else 0,
            "new_connections":   round(_nz_sum(zrows,'new_connections')),
            "conn_applied":      round(_nz_sum(zrows,'conn_applied')),
            "all_conn_applied":  round(_nz_sum(zrows,'all_conn_applied')),
            "cash_collected":    round(ca,2),
            "amt_billed":        round(bi,2),
            "collection_rate":   round(ca/bi*100,1) if bi else 0,
            "collection_per_sales": round(_nz_avg(zrows,'collection_per_sales'),3),
            "op_cost":           round(_nz_sum(zrows,'op_cost'),2),
            "chem_cost":         round(ch,2),
            "power_cost":        round(pw,2),
            "power_cost_per_m3": round(pw/vol,2) if vol else 0,
            "power_kwh":         round(_nz_sum(zrows,'power_kwh'),1),
            "fuel_cost":         round(_nz_sum(zrows,'fuel_cost'),2),
            "staff_costs":       round(_nz_sum(zrows,'staff_costs'),2),
            "wages":             round(_nz_sum(zrows,'wages'),2),
            "maintenance":       round(_nz_sum(zrows,'maintenance'),2),
            "chlorine_kg":       round(_nz_sum(zrows,'chlorine_kg'),1),
            "alum_kg":           round(_nz_sum(zrows,'alum_kg'),1),
            "soda_ash_kg":       round(_nz_sum(zrows,'soda_ash_kg'),1),
            "pipe_breakdowns":   round(_nz_sum(zrows,'pipe_breakdowns')) if any(getattr(r,'pipe_breakdowns',None) is not None for r in zrows) else None,
            "pump_breakdowns":   round(_nz_sum(zrows,'pump_breakdowns')) if any(getattr(r,'pump_breakdowns',None) is not None for r in zrows) else None,
            "pump_hours_lost":   round(_nz_sum(zrows,'pump_hours_lost')),
            "power_fail_hours":  round(_nz_sum(zrows,'power_fail_hours')),
            "supply_hours":      _supply_daily(zrows),
            "pipe_pvc":          round(_nz_sum(zrows,'pipe_pvc')),
            "pipe_gi":           round(_nz_sum(zrows,'pipe_gi')),
            "pipe_di":           round(_nz_sum(zrows,'pipe_di')),
            "pipe_hdpe_ac":      round(_nz_sum(zrows,'pipe_hdpe_ac')),
            "pvc_20mm":          round(_nz_sum(zrows,'pvc_20mm')),
            "pvc_25mm":          round(_nz_sum(zrows,'pvc_25mm')),
            "pvc_32mm":          round(_nz_sum(zrows,'pvc_32mm')),
            "pvc_40mm":          round(_nz_sum(zrows,'pvc_40mm')),
            "pvc_50mm":          round(_nz_sum(zrows,'pvc_50mm')),
            "pvc_63mm":          round(_nz_sum(zrows,'pvc_63mm')),
            "pvc_75mm":          round(_nz_sum(zrows,'pvc_75mm')),
            "pvc_90mm":          round(_nz_sum(zrows,'pvc_90mm')),
            "pvc_110mm":         round(_nz_sum(zrows,'pvc_110mm')),
            "pvc_160mm":         round(_nz_sum(zrows,'pvc_160mm')),
            "pvc_200mm":         round(_nz_sum(zrows,'pvc_200mm')),
            "pvc_250mm":         round(_nz_sum(zrows,'pvc_250mm')),
            "pvc_315mm":         round(_nz_sum(zrows,'pvc_315mm')),
            "dev_lines_total":   round(_nz_sum(zrows,'dev_lines_total')),
            "service_charge":    round(_nz_sum(zrows,'service_charge'),2),
            "meter_rental":      round(_nz_sum(zrows,'meter_rental'),2),
            "total_sales":       round(_nz_sum(zrows,'total_sales'),2),
            "private_debtors":   round(sum(max(0,r.private_debtors) for r in lv_d),2),
            "public_debtors":    round(sum(max(0,r.public_debtors)  for r in lv_d),2),
            "total_debtors":     round(sum(max(0,r.total_debtors)   for r in lv_d),2),
            "stuck_meters":      round(sum(max(0,r.stuck_meters)    for r in lv)),
            "stuck_new":         round(_nz_sum(zrows,'stuck_new')),
            "stuck_repaired":    round(_nz_sum(zrows,'stuck_repaired')),
            "amt_billed_pp":     round(_nz_sum(zrows,'amt_billed_pp'),2),
            "amt_billed_prepaid":round(_nz_sum(zrows,'amt_billed_prepaid'),2),
            "cash_coll_pp":      round(_nz_sum(zrows,'cash_coll_pp'),2),
            "cash_coll_prepaid": round(_nz_sum(zrows,'cash_coll_prepaid'),2),
        }
        entry.update(_avg_field_map(zrows, CHEM_INTENSITY_FIELDS + ['power_kwh_per_m3', 'staff_per_1000m3_12h'], digits=3))
        entry.update(_sum_field_map(zrows, CUSTOMER_VOLUME_FIELDS + CONNECTION_FLOW_FIELDS + SEGMENT_REVENUE_FIELDS + PIPE_MATERIAL_SIZE_FIELDS + ['paid_up_applicants'], digits=2))
        entry.update(_latest_field_map(lv, CONNECTION_STOCK_FIELDS + STUCK_STOCK_FIELDS, digits=2))
        entry.update(_sum_field_map(zrows, STUCK_FLOW_FIELDS + WORKFORCE_EFFICIENCY_FIELDS, digits=2))
        entry.update(_avg_field_map(zrows, ['connection_days'], digits=1))
        result.append(entry)
    return result


# ── Monthly series — ALL fields every page needs ───────────────────────────

def _monthly(rows):
    bm = defaultdict(list)
    for r in rows: bm[r.month].append(r)

    result = []
    for month in FY_MONTHS:
        mr = bm.get(month, [])
        if not mr:
            result.append({"month": month, "has_data": False}); continue

        lv  = _latest(mr)
        vol = _nz_sum(mr, 'vol_produced')
        # Mark months with zero production AND zero customers as no-data (stub rows)
        if vol == 0 and sum(r.active_customers for r in lv) == 0:
            result.append({"month": month, "has_data": False}); continue

        nrw    = _nz_sum(mr, 'nrw')
        chem   = _nz_sum(mr, 'chem_cost')
        power  = _nz_sum(mr, 'power_cost')
        billed = _nz_sum(mr, 'amt_billed')
        cash   = _nz_sum(mr, 'cash_collected')
        sales  = _nz_sum(mr, 'total_sales')
        opex   = _nz_sum(mr, 'op_cost')
        staff  = _nz_sum(mr, 'staff_costs')
        _md_ind  = round(sum(r.disconnected_individual for r in lv))
        _md_inst = round(sum(r.disconnected_inst       for r in lv))
        _md_comm = round(sum(r.disconnected_commercial for r in lv))
        _md_cwp  = round(sum(r.disconnected_cwp        for r in lv))
        _md_raw  = round(sum(r.total_disconnected      for r in lv))

        entry = {
            "month": month, "has_data": True,

            # ── Production & NRW ──────────────────────────────────────
            "vol_produced":           round(vol, 1),
            "revenue_water":          round(_nz_sum(mr,'revenue_water'), 1),
            "nrw":                    round(nrw, 1),
            "pct_nrw":                round(nrw/vol*100, 2) if vol else 0,
            "total_vol_billed_pp":    round(_nz_sum(mr,'total_vol_billed_pp'), 1),
            "total_vol_billed_prepaid":round(_nz_sum(mr,'total_vol_billed_prepaid'), 1),

            # ── Treatment chemicals ───────────────────────────────────
            "chlorine_kg":       round(_nz_sum(mr,'chlorine_kg'), 1),
            "alum_kg":           round(_nz_sum(mr,'alum_kg'), 1),
            "soda_ash_kg":       round(_nz_sum(mr,'soda_ash_kg'), 1),
            "algae_floc_litres": round(_nz_sum(mr,'algae_floc_litres'), 1),
            "sud_floc_litres":   round(_nz_sum(mr,'sud_floc_litres'), 1),
            "kmno4_kg":          round(_nz_sum(mr,'kmno4_kg'), 1),
            "chem_cost":         round(chem, 2),
            "chem_cost_per_m3":  round(chem/vol, 2) if vol else 0,

            # ── Power & Energy ────────────────────────────────────────
            "power_kwh":          round(_nz_sum(mr,'power_kwh'), 1),
            "power_cost":         round(power, 2),
            "power_cost_per_m3":  round(power/vol, 2) if vol else 0,
            # supply_hours: cap at 744 (31d×24h) then convert to daily average
            "supply_hours":       _supply_daily(mr),
            "power_fail_hours":   round(_nz_sum(mr,'power_fail_hours')),

            # ── Customers (stock — latest per scheme) ─────────────────
            "total_metered":          round(sum(r.total_metered for r in lv)),
            "total_disconnected":      _md_raw or (_md_ind + _md_inst + _md_comm + _md_cwp),
            "disconnected_individual": _md_ind,
            "disconnected_inst":       _md_inst,
            "disconnected_commercial": _md_comm,
            "disconnected_cwp":        _md_cwp,
            "active_customers":       round(sum(r.active_customers        for r in lv)),
            "active_postpaid":        round(sum(r.active_postpaid         for r in lv)),
            "active_prepaid":         round(sum(r.active_prepaid          for r in lv)),
            "active_post_individual": round(sum(r.active_post_individual  for r in lv)),
            "active_prep_individual": round(sum(r.active_prep_individual  for r in lv)),
            "active_post_inst":       round(sum(r.active_post_inst        for r in lv)),
            "active_prep_inst":       round(sum(r.active_prep_inst        for r in lv)),
            "active_post_commercial": round(sum(r.active_post_commercial  for r in lv)),
            "active_prep_commercial": round(sum(r.active_prep_commercial  for r in lv)),
            "active_post_cwp":        round(sum(r.active_post_cwp         for r in lv)),
            "active_prep_cwp":        round(sum(r.active_prep_cwp         for r in lv)),
            "pop_supply_area":        round(sum(r.pop_supply_area         for r in lv)),
            "perm_staff":             round(sum(r.perm_staff              for r in lv)),
            "temp_staff":             round(sum(r.temp_staff              for r in lv)),
            "pop_supplied":           round(sum(r.pop_supplied            for r in lv)),
            "pct_pop_supplied":       round((sum(r.pop_supplied for r in lv) / sum(r.pop_supply_area for r in lv) * 100), 1) if sum(r.pop_supply_area for r in lv) else None,

            # ── Connections ───────────────────────────────────────────
            "new_connections":         round(_nz_sum(mr,'new_connections')),
            "conn_applied":            round(_nz_sum(mr,'conn_applied')),
            "all_conn_applied":        round(_nz_sum(mr,'all_conn_applied')),
            "prepaid_meters_installed":round(_nz_sum(mr,'prepaid_meters_installed')),
            "prepaid_installed":       round(_nz_sum(mr,'prepaid_meters_installed')),
            "all_conn_bfwd":           round(sum(r.all_conn_bfwd for r in lv)),
            "all_conn_cfwd":           round(sum(r.all_conn_cfwd for r in lv)),
            "conn_fully_paid":         round(_nz_sum(mr,'conn_fully_paid')),

            # ── Connectivity — cap DTC at 365d (data-entry outliers exist) ──
            "days_to_quotation": _nz_avg(mr, 'days_to_quotation', cap=365),
            "days_to_connect":   _nz_avg(mr, 'days_to_connect',   cap=365),
            "connectivity_rate": _nz_avg(mr, 'connectivity_rate'),
            "queries_received":  round(_nz_sum(mr,'queries_received')),
            "time_to_resolve":   _nz_avg(mr, 'time_to_resolve',   cap=365),
            "response_time_avg": _nz_avg(mr, 'response_time_avg', cap=365),

            # ── Stuck meters (stock) ──────────────────────────────────
            "stuck_meters":  round(sum(max(0, r.stuck_meters) for r in lv)),
            "stuck_new":     round(_nz_sum(mr,'stuck_new')),
            "stuck_repaired":round(_nz_sum(mr,'stuck_repaired')),
            "stuck_replaced":round(_nz_sum(mr,'stuck_replaced')),

            # ── Breakdowns ────────────────────────────────────────────
            "pipe_breakdowns":   round(_nz_sum(mr,'pipe_breakdowns')),
            "pipe_pvc":          round(_nz_sum(mr,'pipe_pvc')),
            "pipe_gi":           round(_nz_sum(mr,'pipe_gi')),
            "pipe_di":           round(_nz_sum(mr,'pipe_di')),
            "pipe_hdpe_ac":      round(_nz_sum(mr,'pipe_hdpe_ac')),
            # PVC by size
            "pvc_20mm":          round(_nz_sum(mr,'pvc_20mm')),
            "pvc_25mm":          round(_nz_sum(mr,'pvc_25mm')),
            "pvc_32mm":          round(_nz_sum(mr,'pvc_32mm')),
            "pvc_40mm":          round(_nz_sum(mr,'pvc_40mm')),
            "pvc_50mm":          round(_nz_sum(mr,'pvc_50mm')),
            "pvc_63mm":          round(_nz_sum(mr,'pvc_63mm')),
            "pvc_75mm":          round(_nz_sum(mr,'pvc_75mm')),
            "pvc_90mm":          round(_nz_sum(mr,'pvc_90mm')),
            "pvc_110mm":         round(_nz_sum(mr,'pvc_110mm')),
            "pvc_160mm":         round(_nz_sum(mr,'pvc_160mm')),
            "pvc_200mm":         round(_nz_sum(mr,'pvc_200mm')),
            "pvc_250mm":         round(_nz_sum(mr,'pvc_250mm')),
            "pvc_315mm":         round(_nz_sum(mr,'pvc_315mm')),
            "pump_breakdowns":   round(_nz_sum(mr,'pump_breakdowns')),
            "pump_hours_lost":   round(_nz_sum(mr,'pump_hours_lost')),

            # ── Development lines ─────────────────────────────────────
            "dev_lines_32mm":  round(_nz_sum(mr,'dev_lines_32mm')),
            "dev_lines_50mm":  round(_nz_sum(mr,'dev_lines_50mm')),
            "dev_lines_63mm":  round(_nz_sum(mr,'dev_lines_63mm')),
            "dev_lines_90mm":  round(_nz_sum(mr,'dev_lines_90mm')),
            "dev_lines_110mm": round(_nz_sum(mr,'dev_lines_110mm')),
            "dev_lines_total": round(_nz_sum(mr,'dev_lines_total')),

            # ── Billing & Collections ─────────────────────────────────
            "amt_billed":        round(billed, 2),
            "amt_billed_pp":     round(_nz_sum(mr,'amt_billed_pp'), 2),
            "amt_billed_prepaid":round(_nz_sum(mr,'amt_billed_prepaid'), 2),
            "cash_collected":    round(cash, 2),
            "cash_coll_pp":      round(_nz_sum(mr,'cash_coll_pp'), 2),
            "cash_coll_prepaid": round(_nz_sum(mr,'cash_coll_prepaid'), 2),
            "collection_rate":   round(cash/billed*100, 2) if billed else 0,

            # ── Charges ───────────────────────────────────────────────
            "service_charge": round(_nz_sum(mr,'service_charge'), 2),
            "meter_rental":   round(_nz_sum(mr,'meter_rental'), 2),
            "total_sales":    round(sales, 2),
            "sc_mr_ratio":    round(_nz_sum(mr,'service_charge') /
                                    _nz_sum(mr,'meter_rental'), 3)
                              if _nz_sum(mr,'meter_rental') else 0,

            # ── Expenses ──────────────────────────────────────────────
            "op_cost":       round(opex, 2),
            "staff_costs":   round(staff, 2),
            "wages":         round(_nz_sum(mr,'wages'), 2),
            "fuel_cost":     round(_nz_sum(mr,'fuel_cost'), 2),
            "maintenance":   round(_nz_sum(mr,'maintenance'), 2),
            "other_overhead":round(_nz_sum(mr,'other_overhead'), 2),
            "op_cost_per_m3":round(opex/vol, 2) if vol else 0,

            # ── Debtors (stock) ───────────────────────────────────────
            "private_debtors":round(sum(max(0,r.private_debtors) for r in lv), 2),
            "public_debtors": round(sum(max(0,r.public_debtors)  for r in lv), 2),
            "total_debtors":  round(sum(max(0,r.total_debtors)   for r in lv), 2),
        }
        entry.update(_avg_field_map(mr, CHEM_INTENSITY_FIELDS + ['power_kwh_per_m3', 'staff_per_1000m3_12h'], digits=3))
        entry.update(_sum_field_map(
            mr,
            CUSTOMER_VOLUME_FIELDS + CONNECTION_FLOW_FIELDS + STUCK_FLOW_FIELDS +
            SEGMENT_REVENUE_FIELDS + PIPE_MATERIAL_SIZE_FIELDS +
            ['paid_up_applicants', 'connection_days', 'fuel_used_litres'],
            digits=2,
        ))
        entry.update(_latest_field_map(lv, CONNECTION_STOCK_FIELDS + STUCK_STOCK_FIELDS, digits=2))
        entry.update({
            "op_cost_per_m3_produced": round(_nz_avg(mr, 'op_cost_per_m3_produced'), 2),
            "op_cost_per_m3_billed": round(_nz_avg(mr, 'op_cost_per_m3_billed'), 2),
            "op_cost_per_sales": round(_nz_avg(mr, 'op_cost_per_sales'), 3),
        })
        result.append(entry)
    return result


def _is_canonical_row(r):
    return (
        getattr(r, 'fiscal_year', None) not in (None, '', 'NULL')
        and getattr(r, 'month', None) in FY_MONTHS
        and getattr(r, 'month_no', None) is not None
    )


def _row_score(r):
    score = 0
    if _is_canonical_row(r):
        score += 100
    if getattr(r, 'fiscal_year', None) not in (None, '', 'NULL'):
        score += 10
    if getattr(r, 'month', None) in FY_MONTHS:
        score += 10
    if getattr(r, 'month_no', None) is not None:
        score += 5
    if getattr(r, 'quarter', None):
        score += 1
    return score


def _dedupe_rows(rows):
    """Keep one logical record per (zone, scheme, year, month_no).

    This prevents double counting where the database contains both:
      - legacy rows (month stored as 4/5/6..., fiscal_year NULL)
      - canonical rows (month stored as April/May/June..., fiscal_year set)
    """
    best = {}
    for r in rows:
        key = (r.zone, r.scheme, r.year, r.month_no)
        current = best.get(key)
        if current is None or _row_score(r) > _row_score(current):
            best[key] = r
    return list(best.values())


_NUMERIC_COLS: list[str] | None = None


def _numeric_columns():
    """Names of all numeric Record columns (cached) — id excluded."""
    global _NUMERIC_COLS
    if _NUMERIC_COLS is None:
        _NUMERIC_COLS = [
            c.name for c in Record.__table__.columns
            if c.name != "id" and isinstance(c.type, (Integer, Float, Numeric))
        ]
    return _NUMERIC_COLS


_NULLABLE_SENTINEL_COLS = frozenset({'pipe_breakdowns', 'pump_breakdowns'})


def _coerce_numeric_nulls(rows):
    """Treat NULL numeric metrics as 0 so the many raw sum() aggregations below
    never hit `int + None`. Rows are expunged first so these in-memory fixes are
    never written back to the database (panels are read-only).

    Columns in _NULLABLE_SENTINEL_COLS are intentionally left as None so that
    downstream code can distinguish "not yet entered" from "entered as zero".
    _nz_sum handles None values safely via `or 0`."""
    cols = _numeric_columns()
    for r in rows:
        for name in cols:
            if name in _NULLABLE_SENTINEL_COLS:
                continue
            if getattr(r, name, None) is None:
                setattr(r, name, 0)


# Stock/balance fields (point-in-time snapshots, aggregated via _latest()).
# Unlike flows (production, billing, breakdowns) these are NOT summed across
# months; they are often recorded in a single month and left blank otherwise.
STOCK_BALANCE_FIELDS = [
    'active_customers', 'active_postpaid', 'active_prepaid',
    'active_post_cwp', 'active_prep_cwp',
    'active_post_individual', 'active_prep_individual',
    'active_post_inst', 'active_prep_inst',
    'active_post_commercial', 'active_prep_commercial',
    'total_metered',
    'total_disconnected', 'disconnected_individual', 'disconnected_inst',
    'disconnected_commercial', 'disconnected_cwp',
    'pop_supply_area', 'pop_supplied',
    'perm_staff', 'temp_staff',
    'total_debtors', 'private_debtors', 'public_debtors',
    'stuck_meters', 'all_conn_bfwd', 'all_conn_cfwd',
] + CONNECTION_STOCK_FIELDS + STUCK_STOCK_FIELDS


def _backfill_stock_balances(rows, zones, schemes, year, db):
    """Carry stock/balance snapshots into a month-filtered window.

    Stock fields (active customers, staff, metered, debtors, stuck/connection
    balances, population) are often booked in just one month of the year. When
    the month filter excludes that month, the in-window rows hold no value and
    the headline KPI would wrongly read 0. For each (zone, scheme) whose
    in-window rows have no value for a stock field, we look up the latest
    NON-ZERO value across the full fiscal year (same zone/scheme filters, no
    month filter) and write it onto that key's latest in-window row, so the
    downstream _latest()/_by_zone() aggregations report the true balance.
    Flow fields are never touched.
    """
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r.zone, r.scheme)].append(r)
    if not by_key:
        return
    fy = _filter(db.query(Record), csv_list(zones), csv_list(schemes), None, year).all()
    fy = _dedupe_rows(fy)
    for r in fy:
        db.expunge(r)
    _coerce_numeric_nulls(fy)
    fy_by_key = defaultdict(list)
    for r in fy:
        fy_by_key[(r.zone, r.scheme)].append(r)
    for key, krows in by_key.items():
        krows.sort(key=_lk)
        latest_in_window = krows[-1]
        fyrows = sorted(fy_by_key.get(key, []), key=_lk)
        if not fyrows:
            continue
        for field in STOCK_BALANCE_FIELDS:
            if any((getattr(r, field, 0) or 0) for r in krows):
                continue  # window already has a value — keep it
            val = 0
            for r in reversed(fyrows):
                v = getattr(r, field, 0) or 0
                if v:
                    val = v
                    break
            if val:
                setattr(latest_in_window, field, val)


def _crossfy_stock_backfill(rows, zones, schemes, year, db):
    """Carry stock/balance values from the previous FY into the current window.

    At the start of a new fiscal year the opening balance columns (e.g.
    all_conn_bfwd, all_conn_cfwd, stuck_meters) are often not yet entered in
    the zone workbooks.  Without this pass, those fields collapse to 0 even
    though the prior FY's closing values are the correct opening estimates.

    For each (zone, scheme) whose current-FY rows have no non-zero value for a
    stock field, the latest non-zero value from the previous FY is written onto
    that key's most-recent in-window row — so downstream aggregations surface
    the best available balance rather than a misleading zero.

    Flow fields are never touched (only STOCK_BALANCE_FIELDS are considered).
    """
    if not rows or not year:
        return
    by_key = defaultdict(list)
    for r in rows:
        by_key[(r.zone, r.scheme)].append(r)
    if not by_key:
        return

    prev = _filter(db.query(Record), csv_list(zones), csv_list(schemes), None, year - 1).all()
    if not prev:
        return
    prev = _dedupe_rows(prev)
    for r in prev:
        db.expunge(r)
    _coerce_numeric_nulls(prev)
    prev_by_key = defaultdict(list)
    for r in prev:
        prev_by_key[(r.zone, r.scheme)].append(r)

    for key, krows in by_key.items():
        krows.sort(key=_lk)
        latest_in_window = krows[-1]
        prevrows = sorted(prev_by_key.get(key, []), key=_lk)
        if not prevrows:
            continue
        for field in STOCK_BALANCE_FIELDS:
            if any((getattr(r, field, 0) or 0) for r in krows):
                continue  # current FY already has a value — keep it
            for r in reversed(prevrows):
                v = getattr(r, field, 0) or 0
                if v:
                    setattr(latest_in_window, field, v)
                    break


def _base(zones, schemes, months, year, db):
    rows = _filter(
        db.query(Record),
        csv_list(zones), csv_list(schemes), csv_list(months), year,
    ).all()
    rows = _dedupe_rows(rows)
    for r in rows:
        db.expunge(r)
    _coerce_numeric_nulls(rows)
    # When a month filter is active, carry forward stock balances recorded
    # outside the window so snapshot KPIs don't collapse to 0.
    if months:
        _backfill_stock_balances(rows, zones, schemes, year, db)
    # When the current FY's opening balance columns are not yet entered,
    # carry the previous FY's closing values forward across the FY boundary.
    if year:
        _crossfy_stock_backfill(rows, zones, schemes, year, db)
    return rows, _by_zone(rows), _monthly(rows)


# ── Panel endpoints — all return "monthly": mo (complete data) ─────────────

@router.get("/production")
def panel_production(zones:Optional[str]=None,schemes:Optional[str]=None,
                     months:Optional[str]=None,year:Optional[int]=None,
                     db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    vol=_nz_sum(rows,'vol_produced'); nrw=_nz_sum(rows,'nrw')
    rev_water=_nz_sum(rows,'revenue_water')
    lv=_latest(rows)
    pop=sum(r.pop_supplied for r in lv if r.pop_supplied)
    active=sum(r.active_customers for r in lv if r.active_customers)
    # IWA Op18: specific consumption = avg daily production per capita (L/capita/day)
    months_with_data=sum(1 for m in mo if m.get('has_data'))
    days_in_period=months_with_data*30.44 if months_with_data else 1
    specific_consumption=round(vol/pop/days_in_period*1000,1) if (pop and vol) else None
    # Revenue water per connection (m³/connection/month)
    rev_per_conn=round(rev_water/active/months_with_data,1) if (active and months_with_data and rev_water) else None
    return {
        "kpi":{"vol_produced":round(vol,1),
               "revenue_water":round(rev_water,1),
               "nrw":round(nrw,1),
               "nrw_pct":round(nrw/vol*100,2) if vol else 0,
               "specific_consumption":specific_consumption,
               "rev_water_per_conn":rev_per_conn},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "vol_produced":z["vol_produced"],"nrw_pct":z["nrw_pct"]} for z in bz],
        "monthly":mo,
    }

@router.get("/wt-ei")
def panel_wt_ei(zones:Optional[str]=None,schemes:Optional[str]=None,
                months:Optional[str]=None,year:Optional[int]=None,
                db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    vol=_nz_sum(rows,'vol_produced')
    chem=_nz_sum(rows,'chem_cost'); power=_nz_sum(rows,'power_cost')
    kwh=_nz_sum(rows,'power_kwh')
    sh_daily = _supply_daily(rows)   # avg daily supply hours (unit-normalised)
    return {
        "kpi":{
            "chem_cost":round(chem,2),"chem_per_m3":round(chem/vol,2) if vol else 0,
            "chlorine_kg":round(_nz_sum(rows,'chlorine_kg'),1),
            "alum_kg":round(_nz_sum(rows,'alum_kg'),1),
            "soda_ash_kg":round(_nz_sum(rows,'soda_ash_kg'),1),
            "algae_floc_litres":round(_nz_sum(rows,'algae_floc_litres'),1),
            "sud_floc_litres":round(_nz_sum(rows,'sud_floc_litres'),1),
            "kmno4_kg":round(_nz_sum(rows,'kmno4_kg'),1),
            "power_kwh":round(kwh,1),"power_cost":round(power,2),
            "power_per_m3":round(power/vol,2) if vol else 0,
            "power_kwh_per_m3":round(kwh/vol, 3) if vol else 0,
            "chlorine_kg_per_m3":round(_nz_avg(rows,'chlorine_kg_per_m3'),3),
            "alum_kg_per_m3":round(_nz_avg(rows,'alum_kg_per_m3'),3),
            "soda_ash_kg_per_m3":round(_nz_avg(rows,'soda_ash_kg_per_m3'),3),
            "algae_floc_per_m3":round(_nz_avg(rows,'algae_floc_per_m3'),3),
            "sud_floc_per_m3":round(_nz_avg(rows,'sud_floc_per_m3'),3),
            "kmno4_per_m3":round(_nz_avg(rows,'kmno4_per_m3'),3),
            "supply_hours_avg": sh_daily,
            "power_fail_hours":round(_nz_sum(rows,'power_fail_hours')),
        },
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "chem_cost":z["chem_cost"],"power_cost":z["power_cost"],
                    "power_kwh":z["power_kwh"],"chlorine_kg":z["chlorine_kg"],
                    "power_kwh_per_m3":z["power_kwh_per_m3"],
                    "chlorine_kg_per_m3":z["chlorine_kg_per_m3"],
                    "alum_kg_per_m3":z["alum_kg_per_m3"],
                    "soda_ash_kg_per_m3":z["soda_ash_kg_per_m3"]} for z in bz],
        "monthly":mo,
    }

@router.get("/customers")
def panel_customers(zones:Optional[str]=None,schemes:Optional[str]=None,
                    months:Optional[str]=None,year:Optional[int]=None,
                    db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    lv=_latest(rows)
    _disc_ind  = round(sum(r.disconnected_individual  for r in lv))
    _disc_inst = round(sum(r.disconnected_inst        for r in lv))
    _disc_comm = round(sum(r.disconnected_commercial  for r in lv))
    _disc_cwp  = round(sum(r.disconnected_cwp         for r in lv))
    _disc_raw  = round(sum(r.total_disconnected       for r in lv))
    return {
        "kpi":{"total_metered":round(sum(r.total_metered for r in lv)),
               "total_disconnected":_disc_raw or (_disc_ind + _disc_inst + _disc_comm + _disc_cwp),
               "disconnected_individual":_disc_ind,
               "disconnected_inst":_disc_inst,
               "disconnected_commercial":_disc_comm,
               "disconnected_cwp":_disc_cwp,
               "active_customers":round(sum(r.active_customers for r in lv)),
               "active_postpaid":round(sum(r.active_postpaid   for r in lv)),
               "active_prepaid":round(sum(r.active_prepaid     for r in lv)),
               "active_post_cwp":round(sum(r.active_post_cwp   for r in lv)),
               "active_prep_cwp":round(sum(r.active_prep_cwp   for r in lv)),
               "pop_supply_area":round(sum(r.pop_supply_area   for r in lv)),
               "pop_supplied":round(sum(r.pop_supplied          for r in lv)),
               "pct_pop_supplied":round((sum(r.pop_supplied for r in lv) / sum(r.pop_supply_area for r in lv) * 100),1) if sum(r.pop_supply_area for r in lv) else 0,
               "perm_staff":round(sum(r.perm_staff              for r in lv)),
               "temp_staff":round(sum(r.temp_staff              for r in lv)),
               "vol_billed_indiv_pp":round(_nz_sum(rows,'vol_billed_indiv_pp'),1),
               "vol_billed_inst_pp":round(_nz_sum(rows,'vol_billed_inst_pp'),1),
               "vol_billed_comm_pp":round(_nz_sum(rows,'vol_billed_comm_pp'),1),
               "vol_billed_cwp_pp":round(_nz_sum(rows,'vol_billed_cwp_pp'),1),
               "vol_billed_indiv_prepaid":round(_nz_sum(rows,'vol_billed_indiv_prepaid'),1),
               "vol_billed_inst_prepaid":round(_nz_sum(rows,'vol_billed_inst_prepaid'),1),
               "vol_billed_comm_prepaid":round(_nz_sum(rows,'vol_billed_comm_prepaid'),1),
               "vol_billed_cwp_prepaid":round(_nz_sum(rows,'vol_billed_cwp_prepaid'),1)},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "total_metered":z["total_metered"],
                    "total_disconnected":z["total_disconnected"],
                    "disconnected_individual":z["disconnected_individual"],
                    "disconnected_inst":z["disconnected_inst"],
                    "disconnected_commercial":z["disconnected_commercial"],
                    "disconnected_cwp":z["disconnected_cwp"],
                    "active_customers":z["active_customers"],
                    "active_postpaid":z["active_postpaid"],
                    "active_prepaid":z["active_prepaid"],
                    "active_post_cwp":z["active_post_cwp"],
                    "active_prep_cwp":z["active_prep_cwp"],
                    "pop_supply_area":z["pop_supply_area"],
                    "pop_supplied":z["pop_supplied"],
                    "pct_pop_supplied":z["pct_pop_supplied"]} for z in bz],
        "monthly":mo,
    }

@router.get("/connections")
def panel_connections(zones:Optional[str]=None,schemes:Optional[str]=None,
                      months:Optional[str]=None,year:Optional[int]=None,
                      db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    lv=_latest(rows)
    return {
        "kpi":{"new_connections":round(_nz_sum(rows,'new_connections')),
               "conn_applied":round(_nz_sum(rows,'conn_applied')),
               "all_conn_applied":round(_nz_sum(rows,'all_conn_applied')),
               "all_conn_bfwd":round(sum(r.all_conn_bfwd for r in lv)),
               "all_conn_cfwd":round(sum(r.all_conn_cfwd for r in lv)),
               "prepaid_meters_installed":round(_nz_sum(rows,'prepaid_meters_installed')),
               "prepaid_installed":round(_nz_sum(rows,'prepaid_meters_installed'))},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "new_connections":z["new_connections"],
                    "conn_applied":z["conn_applied"],
                    "all_conn_applied":z["all_conn_applied"]} for z in bz],
        "monthly":mo,
    }

@router.get("/stuck")
def panel_stuck(zones:Optional[str]=None,schemes:Optional[str]=None,
                months:Optional[str]=None,year:Optional[int]=None,
                db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    lv=_latest(rows)
    cf=sum(max(0,r.stuck_meters) for r in lv)
    new=_nz_sum(rows,'stuck_new'); rep=_nz_sum(rows,'stuck_repaired')
    repl=_nz_sum(rows,'stuck_replaced')
    active=sum(r.active_customers for r in lv) or 1

    # Previous FY's March C/F → opening B/F for April of the current FY
    prev_fy_march_cf = None
    if year:
        prev_rows = _filter(
            db.query(Record),
            csv_list(zones), csv_list(schemes), ['March'], year - 1,
        ).all()
        if prev_rows:
            prev_rows = _dedupe_rows(prev_rows)
            _coerce_numeric_nulls(prev_rows)
            prev_lv = _latest(prev_rows)
            v = sum(max(0, r.stuck_meters) for r in prev_lv)
            if v:
                prev_fy_march_cf = round(v)

    return {
        "kpi":{"stuck_meters":round(cf),"stuck_new":round(new),
               "stuck_repaired":round(rep),"stuck_replaced":round(repl),
               "per_1k_customers":round(cf/active*1000,1),
               "repair_rate":round(rep/(new+rep)*100,1) if (new+rep) else 0},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "stuck_meters":z["stuck_meters"],"stuck_new":z["stuck_new"],
                    "stuck_repaired":z["stuck_repaired"]} for z in bz],
        "monthly":mo,
        "prev_fy_march_cf":prev_fy_march_cf,
    }

@router.get("/connectivity")
def panel_connectivity(zones:Optional[str]=None,schemes:Optional[str]=None,
                       months:Optional[str]=None,year:Optional[int]=None,
                       db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    return {
        "kpi":{"conn_applied":round(_nz_sum(rows,'conn_applied')),
               "conn_fully_paid":round(_nz_sum(rows,'conn_fully_paid')),
               "paid_up_applicants":round(_nz_sum(rows,'paid_up_applicants')),
               "days_to_quotation":_nz_avg(rows,'days_to_quotation',cap=365),
               "days_to_connect":_nz_avg(rows,'days_to_connect',cap=365),
               "connection_days":_nz_avg(rows,'connection_days',cap=365),
               "connectivity_rate":_nz_avg(rows,'connectivity_rate'),
               "queries_received":round(_nz_sum(rows,'queries_received')),
               "time_to_resolve":_nz_avg(rows,'time_to_resolve',cap=365),
               "response_time_avg":_nz_avg(rows,'response_time_avg',cap=365)},
        "monthly":mo,
    }

@router.get("/breakdowns")
def panel_breakdowns(zones:Optional[str]=None,schemes:Optional[str]=None,
                     months:Optional[str]=None,year:Optional[int]=None,
                     db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    # Fallback: derive pipe_breakdowns from material sub-totals when total DB field is 0.
    # Mirrors the logic in panel_pipe_materials; handles missing "TOTAL Pipe Breakdowns" cells.
    pipe_db = _nz_sum(rows,'pipe_breakdowns')
    pipe = pipe_db or (_nz_sum(rows,'pipe_pvc') + _nz_sum(rows,'pipe_gi') +
                       _nz_sum(rows,'pipe_di') + _nz_sum(rows,'pipe_hdpe_ac'))
    pump=_nz_sum(rows,'pump_breakdowns')
    for z in bz:
        if not z.get('pipe_breakdowns'):
            comp = z.get('pipe_pvc',0)+z.get('pipe_gi',0)+z.get('pipe_di',0)+z.get('pipe_hdpe_ac',0)
            if comp:
                z['pipe_breakdowns'] = comp
    for m in mo:
        if not m.get('pipe_breakdowns'):
            comp = m.get('pipe_pvc',0)+m.get('pipe_gi',0)+m.get('pipe_di',0)+m.get('pipe_hdpe_ac',0)
            if comp:
                m['pipe_breakdowns'] = comp
    lv=_latest(rows); active=sum(r.active_customers for r in lv) or 1
    pvc_sizes=['pvc_20mm','pvc_25mm','pvc_32mm','pvc_40mm','pvc_50mm','pvc_63mm',
               'pvc_75mm','pvc_90mm','pvc_110mm','pvc_160mm','pvc_200mm','pvc_250mm','pvc_315mm']
    pvc_kpis={s:round(_nz_sum(rows,s)) for s in pvc_sizes}
    pvc_total=sum(pvc_kpis.values())
    return {
        "kpi":{
            "pipe_breakdowns":round(pipe),"pump_breakdowns":round(pump),
            "total":round(pipe+pump),
            "per_1k_customers":round((pipe+pump)/active*1000,1),
            "pump_hours_lost":round(_nz_sum(rows,'pump_hours_lost')),
            "pvc_total":round(_nz_sum(rows,'pipe_pvc')),
            **pvc_kpis,
        },
        "by_zone":[{
            "zone":z["zone"],"color":z["color"],
            "pipe_breakdowns":z["pipe_breakdowns"],
            "pump_breakdowns":z["pump_breakdowns"],
            "pipe_pvc":z["pipe_pvc"],
            "pipe_gi":z["pipe_gi"],
            "pipe_di":z["pipe_di"],
            "pipe_hdpe_ac":z["pipe_hdpe_ac"],
            **{s:z.get(s,0) for s in pvc_sizes},
        } for z in bz],
        "monthly":mo,
    }

@router.get("/pipelines")
def panel_pipelines(zones:Optional[str]=None,schemes:Optional[str]=None,
                    months:Optional[str]=None,year:Optional[int]=None,
                    db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    return {
        "kpi":{"dev_lines_total":round(_nz_sum(rows,'dev_lines_total')),
               "dev_lines_32mm": round(_nz_sum(rows,'dev_lines_32mm')),
               "dev_lines_50mm": round(_nz_sum(rows,'dev_lines_50mm')),
               "dev_lines_63mm": round(_nz_sum(rows,'dev_lines_63mm')),
               "dev_lines_90mm": round(_nz_sum(rows,'dev_lines_90mm')),
               "dev_lines_110mm":round(_nz_sum(rows,'dev_lines_110mm'))},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "dev_lines_total":z["dev_lines_total"]} for z in bz],
        "size_split":[
            {"label":"32mm", "value":round(_nz_sum(rows,'dev_lines_32mm')), "color":"#0077b6"},
            {"label":"50mm", "value":round(_nz_sum(rows,'dev_lines_50mm')), "color":"#0d9488"},
            {"label":"63mm", "value":round(_nz_sum(rows,'dev_lines_63mm')), "color":"#16a34a"},
            {"label":"90mm", "value":round(_nz_sum(rows,'dev_lines_90mm')), "color":"#d97706"},
            {"label":"110mm","value":round(_nz_sum(rows,'dev_lines_110mm')),"color":"#7c3aed"},
        ],
        "monthly":mo,
    }

@router.get("/billed")
def panel_billed(zones:Optional[str]=None,schemes:Optional[str]=None,
                 months:Optional[str]=None,year:Optional[int]=None,
                 db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    pp=_nz_sum(rows,'amt_billed_pp'); pre=_nz_sum(rows,'amt_billed_prepaid')
    total=pp+pre
    return {
        "kpi":{"amt_billed":round(total,2),"amt_billed_pp":round(pp,2),
               "amt_billed_prepaid":round(pre,2),
               "pp_pct":round(pp/total*100,1) if total else 0,
               "prepaid_pct":round(pre/total*100,1) if total else 0,
               "total_sales":round(_nz_sum(rows,'total_sales'),2),
               **_sum_field_map(rows, [
                   'amt_billed_indiv_pp','amt_billed_cwp_pp','amt_billed_inst_pp','amt_billed_comm_pp',
                   'amt_billed_indiv_prepaid','amt_billed_cwp_prepaid','amt_billed_inst_prepaid','amt_billed_comm_prepaid',
               ], digits=2)},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "amt_billed":z["amt_billed"],"amt_billed_pp":z["amt_billed_pp"],
                    "amt_billed_prepaid":z["amt_billed_prepaid"]} for z in bz],
        "monthly":mo,
    }

@router.get("/collections")
def panel_collections(zones:Optional[str]=None,schemes:Optional[str]=None,
                      months:Optional[str]=None,year:Optional[int]=None,
                      db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    cash=_nz_sum(rows,'cash_collected'); billed=_nz_sum(rows,'amt_billed')
    return {
        "kpi":{"cash_collected":round(cash,2),"amt_billed":round(billed,2),
               "collection_rate":round(cash/billed*100,2) if billed else 0,
               "collection_per_sales":round(_nz_avg(rows,'collection_per_sales'),3),
               "billing_gap":round(abs(billed-cash),2),
               "cash_coll_pp":round(_nz_sum(rows,'cash_coll_pp'),2),
               "cash_coll_prepaid":round(_nz_sum(rows,'cash_coll_prepaid'),2),
               **_sum_field_map(rows, [
                   'cash_coll_indiv_pp','cash_coll_cwp_pp','cash_coll_comm_pp','cash_coll_inst_pp',
                   'cash_coll_indiv_prepaid','cash_coll_cwp_prepaid','cash_coll_comm_prepaid','cash_coll_inst_prepaid',
               ], digits=2)},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "cash_collected":z["cash_collected"],"amt_billed":z["amt_billed"],
                    "collection_rate":z["collection_rate"]} for z in bz],
        "monthly":mo,
    }

@router.get("/charges")
def panel_charges(zones:Optional[str]=None,schemes:Optional[str]=None,
                  months:Optional[str]=None,year:Optional[int]=None,
                  db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    sc=_nz_sum(rows,'service_charge'); mr=_nz_sum(rows,'meter_rental')
    ts=_nz_sum(rows,'total_sales')
    return {
        "kpi":{"service_charge":round(sc,2),"meter_rental":round(mr,2),
               "total_sales":round(ts,2),
               "sc_pct":round(sc/ts*100,1) if ts else 0,
               "mr_pct":round(mr/ts*100,1) if ts else 0,
               "sc_mr_ratio":round(sc/mr,3) if mr else 0,
               **_sum_field_map(rows, [
                   'service_charge_individual','service_charge_cwp','service_charge_institutions','service_charge_commercial',
                   'meter_rental_individual','meter_rental_cwp','meter_rental_institutions','meter_rental_commercial',
               ], digits=2)},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "service_charge":z["service_charge"],"meter_rental":z["meter_rental"],
                    "total_sales":z["total_sales"]} for z in bz],
        "monthly":mo,
    }

@router.get("/expenses")
def panel_expenses(zones:Optional[str]=None,schemes:Optional[str]=None,
                   months:Optional[str]=None,year:Optional[int]=None,
                   db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    op=_nz_sum(rows,'op_cost'); chem=_nz_sum(rows,'chem_cost')
    power=_nz_sum(rows,'power_cost'); fuel=_nz_sum(rows,'fuel_cost')
    staff=_nz_sum(rows,'staff_costs'); wages=_nz_sum(rows,'wages')
    maint=_nz_sum(rows,'maintenance'); kwh=_nz_sum(rows,'power_kwh')
    other=_nz_sum(rows,'other_overhead')
    return {
        "kpi":{"op_cost":round(op,2),"chem_cost":round(chem,2),
               "power_cost":round(power,2),"power_kwh":round(kwh,1),
               "fuel_cost":round(fuel,2),"staff_costs":round(staff,2),
               "wages":round(wages,2),"maintenance":round(maint,2),
               "distances_km":round(_nz_sum(rows,'distances_km'),1),
               "fuel_used_litres":round(_nz_sum(rows,'fuel_used_litres'),1),
               "perm_staff":round(sum(r.perm_staff for r in _latest(rows))),
               "temp_staff":round(sum(r.temp_staff for r in _latest(rows))),
               "staff_per_1000m3_12h":round(_nz_avg(rows,'staff_per_1000m3_12h'),3),
               "op_cost_per_m3_produced":round(_nz_avg(rows,'op_cost_per_m3_produced'),2),
               "op_cost_per_m3_billed":round(_nz_avg(rows,'op_cost_per_m3_billed'),2),
               "op_cost_per_sales":round(_nz_avg(rows,'op_cost_per_sales'),3)},
        "by_zone":[{"zone":z["zone"],"color":z["color"],"op_cost":z["op_cost"],
                    "chem_cost":z["chem_cost"],"power_cost":z["power_cost"],
                    "fuel_used_litres":z["fuel_used_litres"],
                    "distances_km":z["distances_km"],
                    "staff_per_1000m3_12h":z["staff_per_1000m3_12h"]} for z in bz],
        "cost_split":[
            {"label":"Staff",       "value":round(staff,2), "color":"#0077b6"},
            {"label":"Wages",       "value":round(wages,2), "color":"#4DAFEE"},
            {"label":"Power",       "value":round(power,2), "color":"#d97706"},
            {"label":"Chemicals",   "value":round(chem,2),  "color":"#7c3aed"},
            {"label":"Fuel",        "value":round(fuel,2),  "color":"#dc2626"},
            {"label":"Maintenance", "value":round(maint,2), "color":"#16a34a"},
            {"label":"Other",       "value":round(max(0,op-staff-wages-power-chem-fuel-maint),2),
             "color":"#64748b"},
        ],
        "monthly":mo,
    }

@router.get("/debtors")
def panel_debtors(zones:Optional[str]=None,schemes:Optional[str]=None,
                  months:Optional[str]=None,year:Optional[int]=None,
                  db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    # Use last month where debtors were non-zero (guards against months
    # where production/billing data exists but debtors were not entered)
    lv=_latest_nonzero(rows,'total_debtors')
    total=sum(max(0,r.total_debtors)   for r in lv)
    priv =sum(max(0,r.private_debtors) for r in lv)
    pub  =sum(max(0,r.public_debtors)  for r in lv)
    billed=_nz_sum(rows,'amt_billed')
    return {
        "kpi":{"total_debtors":round(total,2),"private_debtors":round(priv,2),
               "public_debtors":round(pub,2),
               "private_pct":round(priv/total*100,1) if total else 0,
               "debtors_to_billed":round(total/billed*100,1) if billed else 0},
        "by_zone":[{"zone":z["zone"],"color":z["color"],
                    "total_debtors":z["total_debtors"],
                    "private_debtors":z["private_debtors"],
                    "public_debtors":z["public_debtors"]} for z in bz],
        "monthly":mo,
    }


@router.get("/segment-revenue")
def panel_segment_revenue(zones:Optional[str]=None,schemes:Optional[str]=None,
                          months:Optional[str]=None,year:Optional[int]=None,
                          db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    billed_total=_nz_sum(rows,'amt_billed')
    collected_total=_nz_sum(rows,'cash_collected')
    return {
        "kpi":{
            "amt_billed":round(billed_total,2),
            "cash_collected":round(collected_total,2),
            "service_charge":round(_nz_sum(rows,'service_charge'),2),
            "meter_rental":round(_nz_sum(rows,'meter_rental'),2),
            "collection_rate":round(collected_total/billed_total*100,2) if billed_total else 0,
        },
        "by_zone":[
            {"zone":z["zone"],"color":z["color"],
             "amt_billed":z["amt_billed"],"cash_collected":z["cash_collected"],
             "service_charge":z["service_charge"],"meter_rental":z["meter_rental"]}
            for z in bz
        ],
        "monthly":mo,
    }


@router.get("/workforce")
def panel_workforce(zones:Optional[str]=None,schemes:Optional[str]=None,
                    months:Optional[str]=None,year:Optional[int]=None,
                    db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    latest=_latest(rows)
    return {
        "kpi":{
            "perm_staff":round(sum(r.perm_staff for r in latest)),
            "temp_staff":round(sum(r.temp_staff for r in latest)),
            "fuel_used_litres":round(_nz_sum(rows,'fuel_used_litres'),1),
            "fuel_cost":round(_nz_sum(rows,'fuel_cost'),2),
            "distances_km":round(_nz_sum(rows,'distances_km'),1),
            "maintenance":round(_nz_sum(rows,'maintenance'),2),
            "staff_per_1000m3_12h":round(_nz_avg(rows,'staff_per_1000m3_12h'),3),
            "op_cost_per_m3_produced":round(_nz_avg(rows,'op_cost_per_m3_produced'),2),
            "op_cost_per_m3_billed":round(_nz_avg(rows,'op_cost_per_m3_billed'),2),
            "op_cost_per_sales":round(_nz_avg(rows,'op_cost_per_sales'),3),
        },
        "by_zone":[
            {"zone":z["zone"],"color":z["color"],
             "perm_staff":z["perm_staff"],"temp_staff":z["temp_staff"],
             "fuel_used_litres":z["fuel_used_litres"],"fuel_cost":z["fuel_cost"],
             "distances_km":z["distances_km"],"maintenance":z["maintenance"],
             "staff_per_1000m3_12h":z["staff_per_1000m3_12h"]}
            for z in bz
        ],
        "monthly":mo,
    }


@router.get("/class-connections")
def panel_class_connections(zones:Optional[str]=None,schemes:Optional[str]=None,
                            months:Optional[str]=None,year:Optional[int]=None,
                            db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    latest=_latest(rows)
    _indiv = round(_nz_sum(rows,'conn_indiv_total_done'))
    _inst  = round(_nz_sum(rows,'conn_inst_total_done'))
    _comm  = round(_nz_sum(rows,'conn_comm_total_done'))
    _cwp   = round(_nz_sum(rows,'conn_cwp_total_done'))
    return {
        "kpi":{
            "all_conn_applied":round(_nz_sum(rows,'all_conn_applied')),
            # Compute total from class breakdown so it always reconciles with the
            # four cards shown above it (vs. the independently-entered ALL Conn TOTAL Done).
            "new_connections": _indiv + _inst + _comm + _cwp,
            "conn_indiv_total_done":_indiv,
            "conn_inst_total_done":_inst,
            "conn_comm_total_done":_comm,
            "conn_cwp_total_done":_cwp,
            "conn_indiv_cfwd":round(sum(r.conn_indiv_cfwd for r in latest)),
            "conn_inst_cfwd":round(sum(r.conn_inst_cfwd for r in latest)),
            "conn_comm_cfwd":round(sum(r.conn_comm_cfwd for r in latest)),
            "conn_cwp_cfwd":round(sum(r.conn_cwp_cfwd for r in latest)),
        },
        "by_zone":[
            {"zone":z["zone"],"color":z["color"],
             "conn_indiv_total_done":z["conn_indiv_total_done"],
             "conn_inst_total_done":z["conn_inst_total_done"],
             "conn_comm_total_done":z["conn_comm_total_done"],
             "conn_cwp_total_done":z["conn_cwp_total_done"]}
            for z in bz
        ],
        "monthly":mo,
    }


@router.get("/stuck-classes")
def panel_stuck_classes(zones:Optional[str]=None,schemes:Optional[str]=None,
                        months:Optional[str]=None,year:Optional[int]=None,
                        db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    latest=_latest(rows)
    return {
        "kpi":{
            "all_stuck_cfwd":round(sum(r.all_stuck_cfwd for r in latest)),
            "stuck_indiv_cfwd":round(sum(r.stuck_indiv_cfwd for r in latest)),
            "stuck_inst_cfwd":round(sum(r.stuck_inst_cfwd for r in latest)),
            "stuck_comm_cfwd":round(sum(r.stuck_comm_cfwd for r in latest)),
            "stuck_cwp_cfwd":round(sum(r.stuck_cwp_cfwd for r in latest)),
            "stuck_indiv_repaired":round(_nz_sum(rows,'stuck_indiv_repaired')),
            "stuck_inst_repaired":round(_nz_sum(rows,'stuck_inst_repaired')),
            "stuck_comm_repaired":round(_nz_sum(rows,'stuck_comm_repaired')),
            "stuck_cwp_repaired":round(_nz_sum(rows,'stuck_cwp_repaired')),
        },
        "by_zone":[
            {"zone":z["zone"],"color":z["color"],
             "stuck_indiv_cfwd":z["stuck_indiv_cfwd"],
             "stuck_inst_cfwd":z["stuck_inst_cfwd"],
             "stuck_comm_cfwd":z["stuck_comm_cfwd"],
             "stuck_cwp_cfwd":z["stuck_cwp_cfwd"]}
            for z in bz
        ],
        "monthly":mo,
    }


@router.get("/pipe-materials")
def panel_pipe_materials(zones:Optional[str]=None,schemes:Optional[str]=None,
                         months:Optional[str]=None,year:Optional[int]=None,
                         db:Session=Depends(get_db)):
    rows,bz,mo=_base(zones,schemes,months,year,db)
    pipe_pvc    = round(_nz_sum(rows,'pipe_pvc'))
    pipe_gi     = round(_nz_sum(rows,'pipe_gi'))
    pipe_di     = round(_nz_sum(rows,'pipe_di'))
    pipe_hdpe_ac= round(_nz_sum(rows,'pipe_hdpe_ac'))
    pipe_db     = round(_nz_sum(rows,'pipe_breakdowns'))
    # If the DB total is absent, compute from material sub-totals
    pipe_breakdowns = pipe_db or (pipe_pvc + pipe_gi + pipe_di + pipe_hdpe_ac)
    return {
        "kpi":{
            "pipe_breakdowns": pipe_breakdowns,
            "pipe_pvc":        pipe_pvc,
            "pipe_gi":         pipe_gi,
            "pipe_di":         pipe_di,
            "pipe_hdpe_ac":    pipe_hdpe_ac,
            **_sum_field_map(rows, PIPE_MATERIAL_SIZE_FIELDS, digits=0),
        },
        "by_zone":[
            {"zone":z["zone"],"color":z["color"],
             "pipe_pvc":z["pipe_pvc"],"pipe_gi":z["pipe_gi"],
             "pipe_di":z["pipe_di"],"pipe_hdpe_ac":z["pipe_hdpe_ac"]}
            for z in bz
        ],
        "monthly":mo,
    }


# ═══════════════════════════════════════════════════════════════════════════
# EXECUTIVE DASHBOARD — derived KPIs (IWA / IBNET aligned)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/executive")
def panel_executive(zones: Optional[str] = None, schemes: Optional[str] = None,
                    months: Optional[str] = None, year: Optional[int] = None,
                    db: Session = Depends(get_db)):
    rows, bz, mo = _base(zones, schemes, months, year, db)
    if not rows:
        return {"financial": {}, "nrw": {}, "service": {}, "zones": [], "trends": {}}

    lv = _latest(rows)
    data_months = [m for m in mo if m.get("has_data")]
    n_months = len(data_months)

    # ── Aggregates ────────────────────────────────────────────────
    revenue   = _nz_sum(rows, 'amt_billed')
    cash      = _nz_sum(rows, 'cash_collected')
    opex      = _nz_sum(rows, 'op_cost')
    vol_prod  = _nz_sum(rows, 'vol_produced')
    nrw_vol   = _nz_sum(rows, 'nrw')
    total_dbt = sum(max(0, r.total_debtors) for r in lv)
    active    = sum(max(0, r.active_customers) for r in lv)
    metered   = sum(max(0, r.total_metered) for r in lv)
    stuck     = sum(max(0, r.stuck_meters) for r in lv)
    queries   = _nz_sum(rows, 'queries_received')
    power_kwh = _nz_sum(rows, 'power_kwh')
    supply_daily = _supply_daily(rows)
    _pipe_has_data  = any(getattr(r,'pipe_breakdowns',None) is not None for r in rows)
    _pump_has_data  = any(getattr(r,'pump_breakdowns',None) is not None for r in rows)
    pipe_breakdowns = _nz_sum(rows, 'pipe_breakdowns') if _pipe_has_data else None
    pump_breakdowns = _nz_sum(rows, 'pump_breakdowns') if _pump_has_data else None
    vol_billed = (_nz_sum(rows, 'total_vol_billed_pp')
                  + _nz_sum(rows, 'total_vol_billed_prepaid'))
    avg_tariff = round(revenue / vol_billed, 2) if vol_billed else 0

    # ── 1. Financial Health Ratios ────────────────────────────────
    op_ratio    = round(opex / revenue, 2) if revenue else 0
    monthly_rev = revenue / n_months if n_months else 0
    dso         = round(total_dbt / monthly_rev * 30, 0) if monthly_rev else 0
    rev_per_conn = round(revenue / active, 0) if active else 0
    net_margin  = round((revenue - opex) / revenue * 100, 1) if revenue else 0

    financial = {
        "op_ratio": op_ratio,
        "op_ratio_flag": "GOOD" if op_ratio < 0.8 else ("WATCH" if op_ratio < 1.0 else "HIGH"),
        "dso": dso,
        "dso_flag": "GOOD" if dso < 60 else ("WATCH" if dso < 90 else "HIGH"),
        "rev_per_conn": rev_per_conn,
        "net_margin": net_margin,
        "net_margin_flag": "GOOD" if net_margin > 50 else ("WATCH" if net_margin > 20 else "LOW"),
        "collection_rate": round(cash / revenue * 100, 1) if revenue else 0,
        "collection_rate_flag": "GOOD" if (cash / revenue * 100 if revenue else 0) >= 90 else ("WATCH" if (cash / revenue * 100 if revenue else 0) >= 75 else "HIGH"),
        "cash_collected": round(cash, 2),
        "amt_billed": round(revenue, 2),
    }

    # ── 2. NRW Intelligence ───────────────────────────────────────
    nrw_pct      = round(nrw_vol / vol_prod * 100, 1) if vol_prod else 0
    nrw_cost     = round(nrw_vol * avg_tariff, 0)
    nrw_per_conn = round(nrw_cost / active * 12 / max(n_months, 1), 0) if active else 0

    nrw_intel = {
        "nrw_vol": round(nrw_vol, 0),
        "vol_produced": round(vol_prod, 0),
        "nrw_pct": nrw_pct,
        "nrw_cost": nrw_cost,
        "nrw_per_conn_yr": nrw_per_conn,
        "avg_tariff": avg_tariff,
        "bnm_pct": 20.0,
    }

    # ── 3. Service Quality & Asset Health ─────────────────────────
    energy_int   = round(power_kwh / vol_prod, 2) if vol_prod else 0
    meter_read   = round((metered - stuck) / metered * 100, 1) if metered else 0
    comp_1000    = round(queries / active * 1000, 0) if active else 0

    service = {
        "energy_intensity": energy_int,
        "meter_read_rate": meter_read,
        "stuck_meters": int(stuck),
        "stuck_pct": round(stuck / metered * 100, 1) if metered else 0,
        "complaints_1000": int(comp_1000),
        "complaints_flag": "LOW" if comp_1000 < 30 else ("MONITOR" if comp_1000 < 60 else "HIGH"),
        "supply_hours_avg": supply_daily,
    }

    # ── 4. Zone Snapshot (enhanced) ───────────────────────────────
    zone_rows = defaultdict(list)
    for r in rows:
        zone_rows[r.zone].append(r)

    zone_snap = []
    for z in bz:
        zn = z["zone"]
        zr = zone_rows.get(zn, [])
        z_rev = z.get("amt_billed", 0) or 0
        z_opex = z.get("op_cost", 0) or 0
        z_active = z.get("active_customers", 0) or 0
        z_dbt = z.get("total_debtors", 0) or 0
        z_nm = len(set(_lk(r) for r in zr))
        z_mr = z_rev / z_nm if z_nm else 0
        z_dso = round(z_dbt / z_mr * 30, 0) if z_mr else 0

        # sparkline NRW trend
        md = defaultdict(list)
        for r in zr:
            md[_lk(r)].append(r)
        nrw_trend = []
        for key in sorted(md.keys()):
            mr = md[key]
            v = _nz_sum(mr, 'vol_produced')
            n = _nz_sum(mr, 'nrw')
            nrw_trend.append(round(n / v * 100, 1) if v else 0)

        zone_snap.append({
            "zone": zn, "color": z.get("color", "#64748b"),
            "schemes": len(set(r.scheme for r in zr)),
            "nrw_pct": z.get("nrw_pct", 0),
            "collection_rate": z.get("collection_rate", 0),
            "dso": z_dso,
            "op_ratio": round(z_opex / z_rev, 2) if z_rev else 0,
            "rev_per_conn": round(z_rev / z_active, 0) if z_active else 0,
            "active_customers": round(z_active),
            "breakdowns_total": None if z.get("pipe_breakdowns") is None else round((z.get("pipe_breakdowns") or 0) + (z.get("pump_breakdowns") or 0)),
            "nrw_trend": nrw_trend,
        })

    # ── 5. Trend series ───────────────────────────────────────────
    trends = {
        "labels":    [m["month"] for m in data_months],
        "production": [m.get("vol_produced", 0) for m in data_months],
        "billed":    [m.get("amt_billed", 0) for m in data_months],
        "collected": [m.get("cash_collected", 0) for m in data_months],
        "nrw_pct":   [m.get("pct_nrw", 0) for m in data_months],
        "zone_nrw": [{"zone": z["zone"], "color": z.get("color", "#64748b"),
                      "nrw_pct": z.get("nrw_pct", 0)} for z in bz],
    }

    return {
        "financial": financial,
        "nrw": nrw_intel,
        "service": service,
        "portfolio": {
            "active_customers": round(active),
            "supply_hours_avg": supply_daily,
            "total_breakdowns": None if pipe_breakdowns is None else round((pipe_breakdowns or 0) + (pump_breakdowns or 0)),
            "queries_received": round(queries),
            "zones_covered": len(zone_snap),
            "schemes_covered": len({(r.zone, r.scheme) for r in lv}),
            "months_with_data": n_months,
        },
        "zones": zone_snap,
        "trends": trends,
        "record_count": len(rows),
    }

# ══ SP-aligned quick-win departmental panels ═══════════════════════════════
# Each reuses _base() (same FY/zone/scheme/month scoping and the full monthly
# series) and exposes a tailored KPI block + by_zone slice for its page.

@router.get("/nrw")
def panel_nrw(zones: Optional[str] = None, schemes: Optional[str] = None,
              months: Optional[str] = None, year: Optional[int] = None,
              db: Session = Depends(get_db)):
    rows, bz, mo = _base(zones, schemes, months, year, db)
    prod = _nz_sum(rows, "vol_produced")
    sold = _nz_sum(rows, "revenue_water")
    nrw = _nz_sum(rows, "nrw")
    pct = round(nrw / prod * 100, 2) if prod else 0
    # Economic NRW: volume lost × avg revenue per m³ (total_sales / revenue_water)
    total_sales = _nz_sum(rows, "total_sales")
    avg_tariff = total_sales / sold if sold else 0
    economic_nrw = round(nrw * avg_tariff, 2) if (nrw and avg_tariff) else None
    return {
        "kpi": {
            "vol_produced": round(prod), "water_sold": round(sold),
            "nrw_volume": round(nrw), "pct_nrw": pct,
            "target_nrw": 25.0, "gap_to_target": round(pct - 25.0, 1),
            "economic_nrw": economic_nrw, "avg_tariff_per_m3": round(avg_tariff, 2),
        },
        "by_zone": [{"zone": z["zone"], "color": z["color"],
                     "nrw_pct": z["nrw_pct"], "vol_produced": z["vol_produced"],
                     "nrw": z["nrw"]} for z in bz],
        "monthly": mo,
    }


@router.get("/metering")
def panel_metering(zones: Optional[str] = None, schemes: Optional[str] = None,
                   months: Optional[str] = None, year: Optional[int] = None,
                   db: Session = Depends(get_db)):
    rows, bz, mo = _base(zones, schemes, months, year, db)
    lv = _latest(rows)
    post = sum(r.active_postpaid for r in lv)
    pre  = sum(r.active_prepaid  for r in lv)
    tot  = post + pre
    metered = sum(r.total_metered for r in lv)
    return {
        "kpi": {
            "active_postpaid":       round(post),
            "active_prepaid":        round(pre),
            "prepaid_share":         round(pre / tot * 100, 1) if tot else 0,
            "prepaid_installed":     round(_nz_sum(rows, "prepaid_meters_installed")),
            "total_metered":         round(metered),
            "metering_ratio":        min(100.0, round(metered / tot * 100, 1)) if tot else 0,
            "active_customers":      round(tot),
            "active_post_individual":round(sum(r.active_post_individual for r in lv)),
            "active_post_inst":      round(sum(r.active_post_inst       for r in lv)),
            "active_post_commercial":round(sum(r.active_post_commercial for r in lv)),
            "active_post_cwp":       round(sum(r.active_post_cwp        for r in lv)),
            "active_prep_individual":round(sum(r.active_prep_individual for r in lv)),
            "active_prep_inst":      round(sum(r.active_prep_inst       for r in lv)),
            "active_prep_commercial":round(sum(r.active_prep_commercial for r in lv)),
            "active_prep_cwp":       round(sum(r.active_prep_cwp        for r in lv)),
        },
        "by_zone": [{"zone": z["zone"], "color": z["color"],
                     "active_postpaid": z["active_postpaid"],
                     "active_prepaid":  z["active_prepaid"]} for z in bz],
        "monthly": mo,
    }


@router.get("/profitability")
def panel_profitability(zones: Optional[str] = None, schemes: Optional[str] = None,
                        months: Optional[str] = None, year: Optional[int] = None,
                        db: Session = Depends(get_db)):
    rows, bz, mo = _base(zones, schemes, months, year, db)
    rev = _nz_sum(rows, "total_sales")
    opex = _nz_sum(rows, "op_cost")
    billed = _nz_sum(rows, "amt_billed")
    cash = _nz_sum(rows, "cash_collected")
    profit = rev - opex
    return {
        "kpi": {
            "total_sales": round(rev, 2), "op_cost": round(opex, 2),
            "operating_profit": round(profit, 2),
            "op_margin": round(profit / rev * 100, 1) if rev else 0,
            "op_ratio": round(opex / rev * 100, 1) if rev else 0,
            "amt_billed": round(billed, 2), "cash_collected": round(cash, 2),
            "collection_rate": round(cash / billed * 100, 1) if billed else 0,
        },
        "by_zone": [{"zone": z["zone"], "color": z["color"],
                     "total_sales": z["total_sales"], "op_cost": z["op_cost"],
                     "operating_profit": round(z["total_sales"] - z["op_cost"], 2)} for z in bz],
        "monthly": mo,
    }


@router.get("/disconnections")
def panel_disconnections(zones: Optional[str] = None, schemes: Optional[str] = None,
                         months: Optional[str] = None, year: Optional[int] = None,
                         db: Session = Depends(get_db)):
    rows, bz, mo = _base(zones, schemes, months, year, db)
    lv = _latest(rows)
    disc_ind  = round(sum(r.disconnected_individual  for r in lv))
    disc_inst = round(sum(r.disconnected_inst        for r in lv))
    disc_comm = round(sum(r.disconnected_commercial  for r in lv))
    disc_cwp  = round(sum(r.disconnected_cwp         for r in lv))
    disc_raw  = round(sum(r.total_disconnected       for r in lv))
    # If the DB total is absent, derive it from the breakdown columns
    disc = disc_raw or (disc_ind + disc_inst + disc_comm + disc_cwp)
    active = sum(r.active_customers for r in lv)
    return {
        "kpi": {
            "total_disconnected":     disc,
            "disconnected_individual": disc_ind,
            "disconnected_inst":       disc_inst,
            "disconnected_commercial": disc_comm,
            "disconnected_cwp":        disc_cwp,
            "active_customers": round(active),
            "disconnection_rate": round(disc / (active + disc) * 100, 1) if (active + disc) else 0,
        },
        "by_zone": [{"zone": z["zone"], "color": z["color"],
                     "total_disconnected": z["total_disconnected"]} for z in bz],
        "monthly": mo,
    }


@router.get("/staff-productivity")
def panel_staff_productivity(zones: Optional[str] = None, schemes: Optional[str] = None,
                             months: Optional[str] = None, year: Optional[int] = None,
                             db: Session = Depends(get_db)):
    rows, bz, mo = _base(zones, schemes, months, year, db)
    lv = _latest(rows)
    perm = sum(r.perm_staff for r in lv)
    temp = sum(r.temp_staff for r in lv)
    total = perm + temp
    active = sum(r.active_customers for r in lv)
    prod = _nz_sum(rows, "vol_produced")
    return {
        "kpi": {
            "perm_staff": round(perm), "temp_staff": round(temp), "total_staff": round(total),
            "staff_per_1000conn": round(total / active * 1000, 1) if active else 0,
            # Use the captured, normalised SP indicator (staff per 1,000 m³ /12h)
            # rather than a raw annual ratio so it is comparable to the SP target.
            "staff_per_1000m3": round(_nz_avg(rows, "staff_per_1000m3_12h"), 2),
            "staff_cost": round(_nz_sum(rows, "staff_costs") + _nz_sum(rows, "wages"), 2),
            "target_per_1000conn": 13, "target_per_1000m3": 8,
        },
        "by_zone": [{"zone": z["zone"], "color": z["color"],
                     "staff_per_1000m3_12h": z.get("staff_per_1000m3_12h", 0)} for z in bz],
        "monthly": mo,
    }


@router.get("/supply-continuity")
def panel_supply_continuity(zones: Optional[str] = None, schemes: Optional[str] = None,
                            months: Optional[str] = None, year: Optional[int] = None,
                            db: Session = Depends(get_db)):
    rows, bz, mo = _base(zones, schemes, months, year, db)
    daily = _supply_daily(rows)
    zd = defaultdict(list)
    for r in rows:
        zd[r.zone].append(r)
    zone_supply = [{"zone": z, "color": ZONE_COLORS.get(z, "#64748b"),
                    "supply_hours": _supply_daily(zr)} for z, zr in sorted(zd.items())]
    return {
        "kpi": {
            "supply_hours": daily, "target_hours": 21,
            "gap_to_target": round(daily - 21, 1),
            "power_fail_hours": round(_nz_sum(rows, "power_fail_hours")),
            "continuity_pct": round(daily / 24 * 100, 1),
        },
        "by_zone": zone_supply,
        "monthly": mo,
    }
