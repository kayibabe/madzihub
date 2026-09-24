"""
services/insights_engine.py
============================
Phase 1 Anomaly & Alert Engine — pure Python, zero external API calls.

Analyses the current fiscal-year data and produces a structured list of
alerts grouped by severity (critical / warning / info) and category.

Called by GET /api/insights/summary (registered in main.py).
"""
from __future__ import annotations
import statistics
from typing import Any
from sqlalchemy.orm import Session
from app.database import Record


# ── Thresholds ─────────────────────────────────────────────────────────────
# All derived from SRWB targets, IBNET/IWA benchmarks, and observed data.

THRESHOLDS = {
    # NRW
    "nrw_target":        27.0,   # SRWB corporate target
    "nrw_warn":          35.0,   # Action threshold
    # Collection rate
    "coll_good":         90.0,   # IBNET benchmark
    "coll_warn":         75.0,   # Serious shortfall
    # Days to connect
    "dtc_warn":          30.0,   # World Bank SLA
    "dtc_critical":      60.0,
    # Stuck meter rate (% of active customers)
    "stuck_pct_warn":    8.0,    # 8% unread = significant billing risk
    # MoM change triggers (%)
    "mom_bd_spike":      20.0,   # Pipe breakdowns rise >20%
    "mom_nrw_rise":       5.0,   # NRW rate rises >5 percentage points
    "mom_coll_drop":     15.0,   # Collection rate drops >15 pp
    "mom_debtors_rise":  20.0,   # Debtors grow >20%
    # Zone-level
    "zone_coll_warn":    80.0,   # Zone collection rate below 80%
    "zone_nrw_critical": 35.0,   # Zone NRW above action threshold
    # Debtors (% of annual billing)
    "debtors_pct_warn":  50.0,   # Debtors > 50% of annual billing = risk
}


def _nz_sum(rows, field):
    return sum((getattr(r, field, 0) or 0) for r in rows)


def _nz_avg(rows, field, cap=None):
    vals = [(getattr(r, field, 0) or 0) for r in rows
            if (getattr(r, field, 0) or 0) > 0]
    if cap:
        vals = [v for v in vals if v <= cap]
    return sum(vals) / len(vals) if vals else 0


def _latest(rows):
    lv = {}
    for r in rows:
        k = (r.zone, r.scheme)
        if k not in lv or (r.year, r.month_no) > (lv[k].year, lv[k].month_no):
            lv[k] = r
    return list(lv.values())


def _month_rows(rows, month_name):
    return [r for r in rows if r.month == month_name]


def generate_alerts(db: Session, year: int = None) -> dict[str, Any]:
    """
    Main entry point. Returns:
    {
      "alerts": [...],          # all alerts sorted by severity
      "summary": {...},         # counts per severity
      "kpi_snapshot": {...},    # key figures used in calculations
    }
    """
    from sqlalchemy import or_, and_
    from app.database import Record

    if year is None:
        from datetime import date
        now = date.today()
        year = now.year + 1 if now.month >= 4 else now.year

    q = db.query(Record).filter(or_(
        and_(Record.year == year - 1, Record.month_no >= 4),
        and_(Record.year == year,     Record.month_no <= 3),
    ))
    rows = q.all()

    if not rows:
        return {"alerts": [], "summary": {"critical": 0, "warning": 0, "info": 0},
                "kpi_snapshot": {}}

    alerts: list[dict] = []

    # ── Helpers ────────────────────────────────────────────────────────────
    def alert(severity, category, title, detail, zone=None, metric=None, value=None):
        alerts.append({
            "severity": severity,       # "critical" | "warning" | "info"
            "category": category,       # "nrw" | "financial" | "operations" | "service"
            "title": title,
            "detail": detail,
            "zone": zone,
            "metric": metric,
            "value": value,
        })

    T = THRESHOLDS
    lv = _latest(rows)

    # ── Sort rows by month for MoM analysis ───────────────────────────────
    FY_ORDER = ["April","May","June","July","August","September",
                "October","November","December","January","February","March"]

    from collections import defaultdict
    monthly_agg: dict[str, dict] = {}
    for month in FY_ORDER:
        mr = [r for r in rows if r.month == month]
        if not mr:
            continue
        vol = _nz_sum(mr, 'vol_produced') or 1
        nrw = _nz_sum(mr, 'nrw')
        billed = _nz_sum(mr, 'amt_billed')
        cash   = _nz_sum(mr, 'cash_collected')
        pipe   = _nz_sum(mr, 'pipe_breakdowns')
        active = sum(r.active_customers or 0 for r in _latest(mr))
        stuck  = sum(max(0, r.stuck_meters or 0) for r in _latest(mr))
        dbt    = sum(max(0, r.total_debtors or 0) for r in _latest(mr))
        dtc    = _nz_avg(mr, 'days_to_connect', cap=365)

        monthly_agg[month] = {
            "pct_nrw":        round(nrw / vol * 100, 1) if vol else 0,
            "collection_rate":round(cash / billed * 100, 1) if billed else 0,
            "pipe_breakdowns":pipe,
            "active_customers":active,
            "stuck_meters":   stuck,
            "total_debtors":  dbt,
            "days_to_connect":dtc,
            "amt_billed":     billed,
        }

    months_with_data = [m for m in FY_ORDER if m in monthly_agg]
    if not months_with_data:
        return {"alerts": [], "summary": {"critical": 0, "warning": 0, "info": 0},
                "kpi_snapshot": {}}

    latest_month   = months_with_data[-1]
    cur            = monthly_agg[latest_month]
    prev_month     = months_with_data[-2] if len(months_with_data) >= 2 else None
    prev           = monthly_agg[prev_month] if prev_month else None

    # YTD aggregates
    vol_ytd    = _nz_sum(rows, 'vol_produced')
    nrw_ytd    = _nz_sum(rows, 'nrw')
    nrw_pct    = round(nrw_ytd / vol_ytd * 100, 1) if vol_ytd else 0
    cash_ytd   = _nz_sum(rows, 'cash_collected')
    billed_ytd = _nz_sum(rows, 'amt_billed')
    coll_rate  = round(cash_ytd / billed_ytd * 100, 1) if billed_ytd else 0
    active_now = sum(max(0, r.active_customers or 0) for r in lv)
    stuck_now  = sum(max(0, r.stuck_meters   or 0) for r in lv)
    dbt_now    = sum(max(0, r.total_debtors  or 0) for r in lv)
    dtc_avg    = _nz_avg(rows, 'days_to_connect', cap=365)
    stuck_pct  = round(stuck_now / active_now * 100, 1) if active_now else 0

    kpi_snapshot = {
        "nrw_pct": nrw_pct,
        "collection_rate": coll_rate,
        "active_customers": active_now,
        "stuck_meters": stuck_now,
        "stuck_pct": stuck_pct,
        "days_to_connect": round(dtc_avg, 1),
        "total_debtors_M": round(dbt_now / 1e6, 1),
        "latest_month": latest_month,
        "months_analysed": len(months_with_data),
    }

    # ══════════════════════════════════════════════════════════════════════
    # RULE SET
    # ══════════════════════════════════════════════════════════════════════

    # ── 1. NRW ────────────────────────────────────────────────────────────
    if nrw_pct > T["nrw_warn"]:
        alert("critical","nrw",
              f"NRW Critical — {nrw_pct}% exceeds 35% action threshold",
              f"YTD NRW rate of {nrw_pct}% is {nrw_pct - T['nrw_target']:.1f}pp above the SRWB "
              f"target of {T['nrw_target']}% and above the 35% action threshold. "
              f"Immediate investigation required.",
              metric="pct_nrw", value=nrw_pct)
    elif nrw_pct > T["nrw_target"]:
        alert("warning","nrw",
              f"NRW Above Target — {nrw_pct}% (target: {T['nrw_target']}%)",
              f"YTD NRW of {nrw_pct}% is {nrw_pct - T['nrw_target']:.1f}pp above the SRWB "
              f"27% target. Review pipe breakdown hotspots and meter reading coverage.",
              metric="pct_nrw", value=nrw_pct)

    # MoM NRW rise
    if prev and cur["pct_nrw"] - prev["pct_nrw"] > T["mom_nrw_rise"]:
        rise = cur["pct_nrw"] - prev["pct_nrw"]
        alert("warning","nrw",
              f"NRW Rising — up {rise:.1f}pp in {latest_month}",
              f"NRW rate increased from {prev['pct_nrw']}% ({prev_month}) to "
              f"{cur['pct_nrw']}% ({latest_month}), a month-on-month rise of {rise:.1f}pp.",
              metric="pct_nrw", value=cur["pct_nrw"])

    # ── 2. Collection Rate ────────────────────────────────────────────────
    if coll_rate < T["coll_warn"]:
        alert("critical","financial",
              f"Collection Rate Critical — {coll_rate}% (benchmark: >{T['coll_good']}%)",
              f"YTD collection rate of {coll_rate}% is severely below the IBNET "
              f"benchmark of {T['coll_good']}%. Cash flow risk is high.",
              metric="collection_rate", value=coll_rate)
    elif coll_rate < T["coll_good"]:
        alert("warning","financial",
              f"Collection Rate Below Benchmark — {coll_rate}%",
              f"Collection rate of {coll_rate}% is below the IBNET {T['coll_good']}% benchmark. "
              f"Review billing accuracy and debtor follow-up activity.",
              metric="collection_rate", value=coll_rate)

    # MoM collection drop
    if prev and prev["collection_rate"] > 0:
        coll_drop = prev["collection_rate"] - cur["collection_rate"]
        if coll_drop > T["mom_coll_drop"]:
            alert("warning","financial",
                  f"Collection Rate Drop — down {coll_drop:.1f}pp in {latest_month}",
                  f"Collection rate fell from {prev['collection_rate']}% ({prev_month}) to "
                  f"{cur['collection_rate']}% ({latest_month}). Investigate billing cycle or payment issues.",
                  metric="collection_rate", value=cur["collection_rate"])

    # ── 3. Pipe Breakdowns MoM spike ─────────────────────────────────────
    if prev and prev["pipe_breakdowns"] > 0:
        bd_chg = (cur["pipe_breakdowns"] - prev["pipe_breakdowns"]) / prev["pipe_breakdowns"] * 100
        if bd_chg > T["mom_bd_spike"]:
            alert("warning","operations",
                  f"Pipe Breakdowns Spike — +{bd_chg:.0f}% in {latest_month}",
                  f"Pipe breakdowns rose from {prev['pipe_breakdowns']:,.0f} ({prev_month}) to "
                  f"{cur['pipe_breakdowns']:,.0f} ({latest_month}), a {bd_chg:.0f}% increase. "
                  f"Check for seasonal pressure changes or network age issues.",
                  metric="pipe_breakdowns", value=cur["pipe_breakdowns"])

    # ── 4. Stuck Meters ───────────────────────────────────────────────────
    if stuck_pct > T["stuck_pct_warn"]:
        unbilled = round(stuck_now * (billed_ytd / max(active_now, 1)) / len(months_with_data) / 1e6, 1)
        alert("warning","operations",
              f"Stuck Meters — {stuck_pct}% of accounts ({stuck_now:,} meters)",
              f"{stuck_now:,} meters are stuck ({stuck_pct}% of {active_now:,} active accounts). "
              f"Estimated monthly billing at risk: approx MWK {unbilled}M.",
              metric="stuck_meters", value=stuck_now)

    # ── 5. Days to Connect ────────────────────────────────────────────────
    if dtc_avg > T["dtc_critical"]:
        alert("critical","service",
              f"Connection Delays Critical — avg {dtc_avg:.0f} days (SLA: {T['dtc_warn']} days)",
              f"Average connection time of {dtc_avg:.0f} days is more than double the "
              f"World Bank {T['dtc_warn']}-day target. Review contractor capacity and permitting.",
              metric="days_to_connect", value=round(dtc_avg, 1))
    elif dtc_avg > T["dtc_warn"]:
        alert("warning","service",
              f"Connection Delays — avg {dtc_avg:.0f} days (target: <{T['dtc_warn']} days)",
              f"Average of {dtc_avg:.0f} days to connect paid-up customers exceeds the "
              f"{T['dtc_warn']}-day World Bank target.",
              metric="days_to_connect", value=round(dtc_avg, 1))

    # ── 6. Debtors growth ────────────────────────────────────────────────
    if prev and prev["total_debtors"] > 0:
        dbt_chg = (cur["total_debtors"] - prev["total_debtors"]) / prev["total_debtors"] * 100
        if dbt_chg > T["mom_debtors_rise"]:
            alert("warning","financial",
                  f"Debtors Rising — +{dbt_chg:.0f}% in {latest_month}",
                  f"Total debtors grew {dbt_chg:.0f}% month-on-month "
                  f"(MWK {cur['total_debtors']/1e6:.0f}M vs MWK {prev['total_debtors']/1e6:.0f}M). "
                  f"Accelerate recovery activity.",
                  metric="total_debtors", value=round(cur["total_debtors"] / 1e6, 1))

    # ── 7. Zone-level alerts ──────────────────────────────────────────────
    from collections import defaultdict
    zone_rows = defaultdict(list)
    for r in rows:
        zone_rows[r.zone].append(r)

    for zone, zrows in zone_rows.items():
        zvol   = _nz_sum(zrows, 'vol_produced') or 1
        znrw   = _nz_sum(zrows, 'nrw')
        zbilled= _nz_sum(zrows, 'amt_billed')
        zcash  = _nz_sum(zrows, 'cash_collected')
        znrw_pct  = round(znrw / zvol * 100, 1) if zvol else 0
        zcoll_pct = round(zcash / zbilled * 100, 1) if zbilled else 0
        zlv = _latest(zrows)
        zstuck = sum(max(0, r.stuck_meters or 0) for r in zlv)
        zactive= sum(max(0, r.active_customers or 0) for r in zlv) or 1
        zstuck_pct = round(zstuck / zactive * 100, 1)

        # Zone NRW critical
        if znrw_pct > T["zone_nrw_critical"]:
            alert("critical","nrw",
                  f"{zone} Zone — NRW Critical at {znrw_pct}%",
                  f"{zone} zone NRW of {znrw_pct}% exceeds the 35% action threshold. "
                  f"Priority zone for loss reduction intervention.",
                  zone=zone, metric="pct_nrw", value=znrw_pct)
        elif znrw_pct > T["nrw_target"]:
            alert("warning","nrw",
                  f"{zone} Zone — NRW Above Target at {znrw_pct}%",
                  f"{zone} zone NRW of {znrw_pct}% exceeds the SRWB 27% target.",
                  zone=zone, metric="pct_nrw", value=znrw_pct)

        # Zone collection rate
        if zcoll_pct < T["zone_coll_warn"]:
            sev = "critical" if zcoll_pct < T["coll_warn"] else "warning"
            alert(sev,"financial",
                  f"{zone} Zone — Collection Rate {zcoll_pct}%",
                  f"{zone} zone collection rate of {zcoll_pct}% is below the {T['zone_coll_warn']}% "
                  f"minimum. Debtors in this zone require targeted follow-up.",
                  zone=zone, metric="collection_rate", value=zcoll_pct)

        # Zone stuck meters
        if zstuck_pct > T["stuck_pct_warn"] * 1.5:  # 12% — elevated threshold for zone
            alert("warning","operations",
                  f"{zone} Zone — High Stuck Meter Rate ({zstuck_pct}%)",
                  f"{zstuck:,} stuck meters in {zone} zone ({zstuck_pct}% of accounts). "
                  f"Billing integrity at risk — prioritise meter replacement programme.",
                  zone=zone, metric="stuck_meters", value=zstuck)

    # ── 8. Trend analysis — is NRW improving or worsening? ───────────────
    if len(months_with_data) >= 4:
        nrw_series = [monthly_agg[m]["pct_nrw"] for m in months_with_data]
        # Compare first half vs second half average
        mid = len(nrw_series) // 2
        first_half  = sum(nrw_series[:mid]) / mid
        second_half = sum(nrw_series[mid:]) / (len(nrw_series) - mid)
        trend_chg = second_half - first_half
        if trend_chg > 1.5:
            alert("warning","nrw",
                  f"NRW Worsening Trend — up {trend_chg:.1f}pp over the year",
                  f"NRW averaged {first_half:.1f}% in the first half of the year and "
                  f"{second_half:.1f}% in the second half, indicating a deteriorating trend.",
                  metric="pct_nrw")
        elif trend_chg < -1.5:
            alert("info","nrw",
                  f"NRW Improving Trend — down {abs(trend_chg):.1f}pp over the year",
                  f"NRW averaged {first_half:.1f}% in the first half and {second_half:.1f}% "
                  f"in the second half. The improving trend should be sustained.",
                  metric="pct_nrw")

    # ── Sort: critical first, then warning, then info ─────────────────────
    SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (SEV_ORDER.get(a["severity"], 9), a["category"]))

    summary = {
        "critical": sum(1 for a in alerts if a["severity"] == "critical"),
        "warning":  sum(1 for a in alerts if a["severity"] == "warning"),
        "info":     sum(1 for a in alerts if a["severity"] == "info"),
        "total":    len(alerts),
    }

    return {
        "alerts": alerts,
        "summary": summary,
        "kpi_snapshot": kpi_snapshot,
    }
