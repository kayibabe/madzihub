"""Import the tenant's YAML strategic plan (tenant.yaml → strategic_plan) into the plan tables.

Creates one draft plan: a pillar per focus area, an indicator per KPI and the annual
targets. KPIs whose ``actual_key`` matches a catalogue measure are automatic (values
come from connected systems); the others are collected manually in reporting cycles.
Running it again for the same plan code changes nothing.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from app.integration.models import Metric
from app.integration.pipeline import PLAN_KEY_ALIASES
from app.modules.strategy import service
from app.modules.strategy.models import Indicator, Plan, PlanNode
from app.platform.scope import Scope

PLAN_CODE = "tenant-plan"


def _slug(text: str, n: int = 30) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").upper()[:n] or "X"


def import_tenant_plan(db: Session, scope: Scope, tenant=None) -> dict:
    from app.core.tenant import tenant as _tenant
    from app.utils import FY_START_MONTH, fy_calendar_year

    scope.require_function("strategy_manager")
    tenant = tenant or _tenant
    sp = tenant.strategic_plan
    if not sp.kpis:
        return {"created": False, "reason": "The tenant configuration has no strategic-plan KPIs."}
    existing = db.query(Plan).filter_by(code=PLAN_CODE).first()
    if existing is not None:
        return {"created": False, "plan_id": existing.id, "reason": "Already imported."}
    years = sorted(sp.years or {y for k in sp.kpis for y in k.targets})
    plan = service.create_plan(db, scope, code=PLAN_CODE, title=sp.title, start_fy=years[0], end_fy=years[-1],
                               description="Imported from the tenant configuration (tenant.yaml).")
    catalogue = {c for (c,) in db.query(Metric.code)}
    pillars: dict[str, PlanNode] = {}
    count = 0
    for i, kpi in enumerate(sp.kpis, start=1):
        if kpi.focus_area not in pillars:
            pillars[kpi.focus_area] = service.create_node(db, scope, plan.id, {
                "node_type": "pillar", "code": f"P{len(pillars) + 1}", "title": kpi.focus_area,
                "sort_order": len(pillars)})
        metric = PLAN_KEY_ALIASES.get(kpi.actual_key, kpi.actual_key) if kpi.actual_key else None
        automatic = bool(metric and metric in catalogue and kpi.capture == "live")
        code = f"K{i:02d}-{_slug(kpi.name, 20)}"
        ind = service.create_indicator(db, scope, plan.id, {
            "code": code, "name": kpi.name, "node_id": pillars[kpi.focus_area].id, "unit": kpi.unit,
            "polarity": "lower" if kpi.direction == "low" else "higher",
            "aggregation": "last" if kpi.unit in ("%", "Days") else "sum",
            "frequency": "year", "collection": "automatic" if automatic else "manual",
            "metric_code": metric if automatic else None, "baseline_value": kpi.baseline,
            "target_basis": f"{sp.title} (tenant configuration)", "source": "Connected systems" if automatic else None,
            "definition": f"{kpi.name}, as defined in {sp.title}."})
        targets = []
        for fy_end, value in sorted(kpi.targets.items()):
            if value is None:
                continue
            targets.append({"period_type": "year", "period_start": date(fy_calendar_year(int(fy_end), FY_START_MONTH),
                                                                        FY_START_MONTH, 1),
                            "value": float(value)})
        # Existing plan targets for the same measure (seeded by the integration bridge) are adopted, not changed.
        service.set_targets(db, scope, ind.id, targets, reason="Imported from the tenant configuration")
        count += 1
    db.flush()
    return {"created": True, "plan_id": plan.id, "pillars": len(pillars), "indicators": count}


def indicator_count(db: Session, plan_id: int) -> int:
    return db.query(Indicator).filter_by(plan_id=plan_id).count()
