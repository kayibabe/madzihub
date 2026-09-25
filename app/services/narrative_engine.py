"""
services/narrative_engine.py
==============================
Phase 2 AI Agent — generates a plain-English executive narrative from
live KPI data using the Groq API. Disabled unless the tenant sets ai.enabled.

Called by GET /api/insights/narrative
"""
from __future__ import annotations
import os, json, logging
from typing import Any
from sqlalchemy.orm import Session

from app.core.tenant import tenant as _tenant

log = logging.getLogger(__name__)

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KEY_FILE  = os.path.join(BASE_DIR, "data", "groq.key")

# ── Groq client (lazy init) ────────────────────────────────────────────────
_groq_client = None

def _get_client():
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    try:
        from groq import Groq
        key = open(KEY_FILE).read().strip()
        if not key:
            raise ValueError("groq.key is empty")
        _groq_client = Groq(api_key=key)
        return _groq_client
    except FileNotFoundError:
        raise RuntimeError(
            "Groq API key not found. Create data/groq.key with your key from console.groq.com"
        )
    except ImportError:
        raise RuntimeError(
            "groq package not installed. Run: pip install groq"
        )


def _build_context(db: Session, year: int) -> dict[str, Any]:
    """Gather all KPI data needed for the narrative prompt."""
    from sqlalchemy import or_, and_
    from app.database import Record
    from app.routers.panels import _base, _monthly, _latest, _nz_sum, _nz_avg, FY_MONTHS
    from app.services.assessment import ratio as assessed_ratio, divide

    rows, bz, mo = _base(None, None, None, year, db)
    if not rows:
        return {}

    lv      = _latest(rows)
    vol     = _nz_sum(rows, 'vol_produced')
    nrw_v   = _nz_sum(rows, 'nrw')
    cash    = _nz_sum(rows, 'cash_collected')
    billed  = _nz_sum(rows, 'amt_billed')
    opex    = _nz_sum(rows, 'op_cost')
    active  = sum(max(0, r.active_customers or 0) for r in lv)
    metered = sum(max(0, r.total_metered   or 0) for r in lv)
    stuck   = sum(max(0, r.stuck_meters   or 0) for r in lv)
    debtors = sum(max(0, r.total_debtors  or 0) for r in lv)
    pipe_bd = _nz_sum(rows, 'pipe_breakdowns')
    conns   = _nz_sum(rows, 'new_connections')
    dtc     = _nz_avg(rows, 'days_to_connect', cap=365)

    nrw_pct  = assessed_ratio(rows, 'nrw', 'vol_produced')
    coll_pct = assessed_ratio(rows, 'cash_collected', 'amt_billed')
    op_ratio = assessed_ratio(rows, 'op_cost', 'amt_billed', scale=1, digits=2)

    # MoM trend for NRW
    has_data = [m for m in mo if m.get('has_data')]
    nrw_trend = "not assessed"
    if len(has_data) >= 4 and all(m.get('pct_nrw') is not None for m in has_data):
        nrw_trend = "stable"
        mid  = len(has_data) // 2
        h1   = sum(m['pct_nrw'] for m in has_data[:mid]) / mid
        h2   = sum(m['pct_nrw'] for m in has_data[mid:]) / (len(has_data) - mid)
        diff = round(h2 - h1, 1)
        if diff > 1.5:   nrw_trend = f"worsening (+{diff}pp H2 vs H1)"
        elif diff < -1.5: nrw_trend = f"improving ({diff}pp H2 vs H1)"

    # Zone summary
    zones = []
    for z in bz:
        zones.append({
            "zone":             z["zone"],
            "nrw_pct":          None if z.get('nrw_pct') is None else round(z['nrw_pct'], 1),
            "collection_rate":  z.get('collection_rate'),
            "pipe_breakdowns":  z.get('pipe_breakdowns'),
            "stuck_meters":     z.get('stuck_meters', 0),
            "total_debtors_M":  round(z.get('total_debtors', 0) / 1e6, 1),
        })

    return {
        "fiscal_year":       f"FY {year-1}/{str(year)[-2:]}",
        "months_analysed":   len(has_data),
        "nrw_pct":           nrw_pct,
        "nrw_target":        _tenant.target("nrw_pct", 27.0),
        "nrw_trend":         nrw_trend,
        "collection_rate":   coll_pct,
        "coll_benchmark":    90.0,
        "operating_ratio":   op_ratio,
        "active_customers":  active,
        "new_connections":   int(conns),
        "stuck_meters":      stuck,
        "stuck_pct":         divide(stuck, metered),
        "pipe_breakdowns":   int(pipe_bd),
        "days_to_connect":   round(dtc, 1),
        "total_debtors_M":   round(debtors / 1e6, 1),
        "total_billed_M":    round(billed / 1e6, 1),
        "cash_collected_M":  round(cash / 1e6, 1),
        "opex_M":            round(opex / 1e6, 1),
        "zones":             zones,
    }


def _v(value, spec="", suffix=""):
    """Format a metric for the prompt; missing values are stated as not assessed, never 0."""
    return "not assessed" if value is None else f"{value:{spec}}{suffix}"


def _build_prompt(ctx: dict) -> str:
    zones_text = "\n".join(
        f"  • {z['zone']}: NRW {_v(z['nrw_pct'], suffix='%')}, Collection {_v(z['collection_rate'], suffix='%')}, "
        f"Pipe failures {_v(z['pipe_breakdowns'], ',.0f')}, Debtors {_tenant.currency.code} {z['total_debtors_M']:.0f}M"
        for z in ctx.get("zones", [])
    )

    ident = _tenant.identity
    where = f" in {ident.country}" if ident.country else ""
    cur = _tenant.currency.code
    return f"""You are a senior performance analyst for the {ident.name} ({ident.short_name}){where}.
Write a concise, professional executive narrative (4–6 sentences) summarising this period's operational performance.

FISCAL YEAR: {ctx['fiscal_year']} ({ctx['months_analysed']} months of data)

KEY METRICS:
- NRW Rate: {_v(ctx['nrw_pct'], suffix='%')} ({ident.short_name} target: <{ctx['nrw_target']}%) — trend: {ctx['nrw_trend']}
- Collection Rate: {_v(ctx['collection_rate'], suffix='%')} (IBNET benchmark: >{ctx['coll_benchmark']}%)
- Operating Ratio: {_v(ctx['operating_ratio'])} (World Bank target: <0.80)
- Active Customers: {ctx['active_customers']:,.0f}
- New Connections: {ctx['new_connections']:,}
- Stuck Meters: {ctx['stuck_meters']:,.0f} ({_v(ctx['stuck_pct'], suffix='% of metered connections')})
- Pipe Breakdowns: {ctx['pipe_breakdowns']:,}
- Avg Days to Connect: {ctx['days_to_connect']} days (target: <30)
- Total Debtors: {cur} {ctx['total_debtors_M']:.0f}M
- Cash Collected: {cur} {ctx['cash_collected_M']:.0f}M vs Billed {cur} {ctx['total_billed_M']:.0f}M

ZONE PERFORMANCE:
{zones_text}

Instructions:
- Write in third person, board-ready tone
- Lead with the most critical issue
- Acknowledge positives where they exist
- End with one forward-looking recommendation
- Do NOT use bullet points — flowing prose only
- Where a metric is "not assessed", say that data is missing; never infer its performance
- Maximum 120 words"""


def generate_narrative(db: Session, year: int = None) -> dict[str, Any]:
    """Returns {'narrative': str, 'model': str, 'tokens_used': int}"""
    if year is None:
        from datetime import date
        now = date.today()
        from app.utils import fy_end_year
        year = fy_end_year(now.year, now.month)

    if not _tenant.ai.enabled:
        # Off unless the installation opts in: narratives send KPI data to an external provider.
        return {"narrative": None, "error": "AI narratives are disabled for this installation (tenant ai.enabled = false)."}
    if _tenant.ai.provider != "groq":
        return {"narrative": None, "error": f"AI provider '{_tenant.ai.provider}' is not supported yet."}

    try:
        client  = _get_client()
        ctx     = _build_context(db, year)
        if not ctx:
            return {"narrative": "No data available for the selected fiscal year.", "model": None}

        prompt  = _build_prompt(ctx)
        resp    = client.chat.completions.create(
            model=_tenant.ai.model,
            messages=[
                {"role": "system", "content":
                 "You are a water utility performance analyst. Write concise, accurate, professional summaries."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.4,  # low temp = consistent, factual output
        )
        narrative = resp.choices[0].message.content.strip()
        return {
            "narrative":   narrative,
            "model":       resp.model,
            "tokens_used": resp.usage.total_tokens,
            "fiscal_year": ctx["fiscal_year"],
            "context":     ctx,
        }

    except Exception as e:
        log.error("Narrative generation failed: %s", e)
        return {
            "narrative": None,
            "error":     str(e),
        }
