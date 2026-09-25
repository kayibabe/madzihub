"""
/api/strategy/* — plans, indicator reference sheets, reporting cycles, progress updates, evaluations.

Reads are limited to the caller's scope; changes follow the rules in service.py.
  GET/POST   /plans                        list / create (strategy manager)
  POST       /plans/import-tenant          import the YAML plan from the tenant configuration
  GET/PUT    /plans/{id}                   structure, levels, indicators / edit
  POST       /plans/{id}/transition        activate | archive | reactivate
  PUT        /plans/{id}/levels            configurable level labels
  POST       /plans/{id}/nodes, PUT /nodes/{id}
  POST       /nodes/{id}/contributes       link a delivery item to the result it serves
  POST       /plans/{id}/indicators, GET/PUT /indicators/{id}, PUT /indicators/{id}/targets
  GET        /indicators/{id}/series?org_unit=
  GET/POST   /plans/{id}/cycles, GET /cycles/{id}, POST /cycles/{id}/generate, POST /cycles/{id}/transition
  GET        /assignments?cycle_id=&queue=submit|verify|approve|overdue
  GET/PUT    /assignments/{id}             detail (revisions, DQA, approvals) / reassign
  POST       /assignments/{id}/submit      new immutable revision + automatic DQA checks
  POST       /assignments/{id}/transition  verify | approve | return | reopen
  POST       /assignments/{id}/dqa         reviewer's data-quality assessment
  GET/POST   /plans/{id}/evaluations, GET/PUT /evaluations/{id}, POST /evaluations/{id}/transition
  POST       /evaluations/{id}/findings, POST /responses/{id}
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.integration.models import Metric
from app.integration.position import published_series
from app.modules.strategy import importer, service
from app.modules.strategy.models import Evaluation, Indicator, Plan, PlanNode, ReportingCycle
from app.platform import entities, links
from app.platform.errors import Invalid, NotFound
from app.platform.router import MY_WORK_PROVIDERS
from app.platform.scope import Scope, get_scope

router = APIRouter(prefix="/api/strategy", tags=["Strategy & M&E"])
MY_WORK_PROVIDERS.append(service.my_work)


def _visible_plan(db: Session, scope: Scope, plan_id: int) -> Plan:
    plan, _ = entities.load(db, scope, "plan", plan_id)
    return plan


# ── plans ───────────────────────────────────────────────────────────────────

class PlanIn(BaseModel):
    code: str
    title: str = Field(min_length=1, max_length=200)
    start_fy: int
    end_fy: int
    description: Optional[str] = None


class PlanUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_fy: Optional[int] = None
    end_fy: Optional[int] = None


class TransitionIn(BaseModel):
    name: str
    reason: Optional[str] = None


class LevelIn(BaseModel):
    node_type: str
    label: str
    plural: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/plans")
def list_plans(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not service.plan_visible(scope, None):
        return []
    return [service.plan_dict(p, scope) for p in db.query(Plan).order_by(Plan.status != "active", Plan.id.desc())]


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = service.create_plan(db, scope, **body.model_dump())
    db.commit()
    return service.plan_dict(p, scope)


@router.post("/plans/import-tenant")
def import_tenant(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    out = importer.import_tenant_plan(db, scope)
    db.commit()
    return out


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return service.plan_detail(db, scope, _visible_plan(db, scope, plan_id))


@router.put("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = service.update_plan(db, scope, plan_id, body.model_dump(exclude_unset=True))
    db.commit()
    return service.plan_dict(p, scope)


@router.post("/plans/{plan_id}/transition")
def transition_plan(plan_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = service.transition_plan(db, scope, plan_id, body.name, body.reason)
    db.commit()
    return service.plan_dict(p, scope)


@router.put("/plans/{plan_id}/levels")
def set_levels(plan_id: int, body: list[LevelIn], scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.set_levels(db, scope, plan_id, [x.model_dump(exclude_none=True) for x in body])
    db.commit()
    return service.plan_detail(db, scope, _visible_plan(db, scope, plan_id))["levels"]


# ── nodes ───────────────────────────────────────────────────────────────────

class NodeIn(BaseModel):
    node_type: str
    code: str
    title: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    org_unit_code: Optional[str] = None
    weight: Optional[float] = None
    sort_order: Optional[int] = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    budget: Optional[float] = None


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    parent_id: Optional[int] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    org_unit_code: Optional[str] = None
    weight: Optional[float] = None
    sort_order: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    budget: Optional[float] = None
    retired: Optional[bool] = None
    reason: Optional[str] = None


class ContributesIn(BaseModel):
    result_node_id: int
    note: Optional[str] = None


@router.post("/plans/{plan_id}/nodes", status_code=201)
def create_node(plan_id: int, body: NodeIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    n = service.create_node(db, scope, plan_id, body.model_dump())
    db.commit()
    return {"id": n.id}


@router.put("/nodes/{node_id}")
def update_node(node_id: int, body: NodeUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    entities.load(db, scope, "plan_node", node_id)
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    n = service.update_node(db, scope, node_id, data, reason)
    db.commit()
    return {"id": n.id}


@router.post("/nodes/{node_id}/contributes", status_code=201)
def contributes(node_id: int, body: ContributesIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_function("strategy_manager")
    src = db.get(PlanNode, node_id)
    dst = db.get(PlanNode, body.result_node_id)
    if src is None or dst is None or src.plan_id != dst.plan_id:
        raise NotFound("Plan item not found in this plan.")
    if src.node_type not in service.DELIVERY_TYPES or dst.node_type not in service.RESULT_TYPES:
        raise Invalid("Link delivery work (programme, initiative, activity, milestone) to a result it serves.")
    link = links.add_link(db, scope, "plan_node", src.id, "plan_node", dst.id, relation="contributes_to",
                          note=body.note, role="viewer")
    db.commit()
    return {"id": link.id}


# ── indicators ──────────────────────────────────────────────────────────────

class IndicatorIn(BaseModel):
    code: str
    name: str
    node_id: Optional[int] = None
    definition: Optional[str] = None
    metric_code: Optional[str] = None
    polarity: Optional[str] = None
    unit: Optional[str] = None
    aggregation: Optional[str] = None
    formula_text: Optional[str] = None
    source: Optional[str] = None
    owner: Optional[str] = None
    org_unit_code: Optional[str] = None
    reporting_units: Optional[list[str]] = None
    collection: Optional[str] = None
    baseline_value: Optional[float] = None
    baseline_date: Optional[date] = None
    target_basis: Optional[str] = None
    frequency: Optional[str] = None
    evidence_required: Optional[bool] = None
    dq_notes: Optional[str] = None
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    weight: Optional[float] = None


class IndicatorUpdate(BaseModel):
    name: Optional[str] = None
    node_id: Optional[int] = None
    definition: Optional[str] = None
    metric_code: Optional[str] = None
    polarity: Optional[str] = None
    unit: Optional[str] = None
    aggregation: Optional[str] = None
    formula_text: Optional[str] = None
    source: Optional[str] = None
    owner: Optional[str] = None
    org_unit_code: Optional[str] = None
    reporting_units: Optional[list[str]] = None
    collection: Optional[str] = None
    baseline_value: Optional[float] = None
    baseline_date: Optional[date] = None
    target_basis: Optional[str] = None
    frequency: Optional[str] = None
    evidence_required: Optional[bool] = None
    dq_notes: Optional[str] = None
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    weight: Optional[float] = None
    status: Optional[str] = None
    reason: Optional[str] = None


class TargetIn(BaseModel):
    period_type: str = "year"
    period_start: date
    value: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    org_unit_code: Optional[str] = None
    delete: bool = False


class TargetsIn(BaseModel):
    targets: list[TargetIn]
    reason: Optional[str] = None


@router.post("/plans/{plan_id}/indicators", status_code=201)
def create_indicator(plan_id: int, body: IndicatorIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ind = service.create_indicator(db, scope, plan_id, body.model_dump(exclude_none=True))
    db.commit()
    return service.indicator_dict(ind)


@router.get("/indicators/{indicator_id}")
def get_indicator(indicator_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ind, _ = entities.load(db, scope, "indicator", indicator_id)
    return {**service.indicator_dict(ind), "targets": service.targets_for(db, ind, scope),
            "can_manage": scope.has_function("strategy_manager") and not scope.read_only}


@router.put("/indicators/{indicator_id}")
def update_indicator(indicator_id: int, body: IndicatorUpdate, scope: Scope = Depends(get_scope),
                     db: Session = Depends(get_db)):
    entities.load(db, scope, "indicator", indicator_id)
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    ind = service.update_indicator(db, scope, indicator_id, data, reason)
    db.commit()
    return service.indicator_dict(ind)


@router.put("/indicators/{indicator_id}/targets")
def set_targets(indicator_id: int, body: TargetsIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ind, _ = entities.load(db, scope, "indicator", indicator_id)
    service.set_targets(db, scope, indicator_id, [t.model_dump() for t in body.targets], body.reason)
    db.commit()
    return service.targets_for(db, ind, scope)


@router.get("/indicators/{indicator_id}/series")
def indicator_series(indicator_id: int, org_unit: Optional[str] = None, period_type: Optional[str] = None,
                     scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ind, _ = entities.load(db, scope, "indicator", indicator_id)
    unit = org_unit or ind.org_unit_code
    scope.require_see(unit, "Organisational unit")
    metric = db.query(Metric).filter_by(code=ind.metric_code).first()
    if metric is None:
        return {"series": [], "info": {}}
    series, info = published_series(db, metric, unit, period_type or ind.frequency)
    return {"org_unit": unit, "period_type": period_type or ind.frequency, "series": series, "info": info}


# ── cycles and assignments ──────────────────────────────────────────────────

class CycleIn(BaseModel):
    period_id: int
    name: Optional[str] = None
    opens_on: Optional[date] = None
    due_on: Optional[date] = None
    require_verification: bool = True


class AssignIn(BaseModel):
    contributor: Optional[str] = None
    reviewer: Optional[str] = None
    approver: Optional[str] = None


class SubmitIn(BaseModel):
    value_state: str = "reported"
    value: Optional[float] = None
    forecast: Optional[float] = None
    narrative: Optional[str] = Field(default=None, max_length=10000)
    variance_reason: Optional[str] = Field(default=None, max_length=10000)
    corrective_action: Optional[str] = Field(default=None, max_length=10000)
    evidence_note: Optional[str] = Field(default=None, max_length=5000)
    # Submit although the value is out of range or required evidence is missing (recorded on the revision).
    acknowledge_checks: bool = False


class DqaIn(BaseModel):
    check: str
    result: str
    reason: str


@router.get("/plans/{plan_id}/cycles")
def list_cycles(plan_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _visible_plan(db, scope, plan_id)
    return [service.cycle_dict(db, c, scope)
            for c in db.query(ReportingCycle).filter_by(plan_id=plan_id).order_by(ReportingCycle.id.desc())]


@router.post("/plans/{plan_id}/cycles", status_code=201)
def create_cycle(plan_id: int, body: CycleIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = service.create_cycle(db, scope, plan_id, **body.model_dump())
    db.commit()
    return service.cycle_dict(db, c, scope)


@router.get("/cycles/{cycle_id}")
def get_cycle(cycle_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = db.get(ReportingCycle, cycle_id)
    if c is None:
        raise NotFound("Reporting cycle not found.")
    _visible_plan(db, scope, c.plan_id)
    # Strategy managers also see who will be asked at each step, to fix routing before the cycle opens.
    people = service.People(db) if scope.has_function("strategy_manager") else None
    return {**service.cycle_dict(db, c, scope),
            "assignments": [service.assignment_dict(db, a, scope, people=people)
                            for a in service.assignment_query(db, scope, cycle_id=c.id)]}


@router.post("/cycles/{cycle_id}/generate")
def generate(cycle_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    n = service.generate_assignments(db, scope, cycle_id)
    db.commit()
    return {"created": n}


@router.post("/cycles/{cycle_id}/transition")
def transition_cycle(cycle_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = service.transition_cycle(db, scope, cycle_id, body.name, body.reason)
    db.commit()
    return service.cycle_dict(db, c, scope)


@router.get("/assignments")
def list_assignments(cycle_id: Optional[int] = None, queue: Optional[str] = Query(None, pattern="^(submit|verify|approve|overdue|all)$"),
                     scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    rows = service.assignment_query(db, scope, cycle_id=cycle_id, queue=None if queue == "all" else queue)
    return [service.assignment_dict(db, a, scope) for a in rows[:1000]]


@router.get("/assignments/{assignment_id}")
def get_assignment(assignment_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a, _ = entities.load(db, scope, "cycle_assignment", assignment_id)
    return service.assignment_dict(db, a, scope, detail=True)


@router.put("/assignments/{assignment_id}")
def reassign(assignment_id: int, body: AssignIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    entities.load(db, scope, "cycle_assignment", assignment_id)
    a = service.update_assignment(db, scope, assignment_id, body.model_dump(exclude_unset=True))
    db.commit()
    return service.assignment_dict(db, a, scope)


@router.post("/assignments/{assignment_id}/submit", status_code=201)
def submit(assignment_id: int, body: SubmitIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    upd = service.submit_update(db, scope, assignment_id, body.model_dump())
    db.commit()
    a, _ = entities.load(db, scope, "cycle_assignment", assignment_id)
    return {**service.assignment_dict(db, a, scope, detail=True), "submitted_revision": upd.revision}


@router.post("/assignments/{assignment_id}/transition")
def review(assignment_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = service.review_update(db, scope, assignment_id, body.name, body.reason)
    db.commit()
    return service.assignment_dict(db, a, scope, detail=True)


@router.post("/assignments/{assignment_id}/dqa", status_code=201)
def dqa(assignment_id: int, body: DqaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.add_dqa(db, scope, assignment_id, body.check, body.result, body.reason)
    db.commit()
    a, _ = entities.load(db, scope, "cycle_assignment", assignment_id)
    return service.assignment_dict(db, a, scope, detail=True)


# ── evaluations ─────────────────────────────────────────────────────────────

class EvaluationIn(BaseModel):
    title: str
    kind: str = "mid_term"
    scope: Optional[str] = None
    method: Optional[str] = None
    criteria: Optional[list[str]] = None
    lead: Optional[str] = None
    org_unit_code: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class EvaluationUpdate(BaseModel):
    title: Optional[str] = None
    kind: Optional[str] = None
    scope: Optional[str] = None
    method: Optional[str] = None
    criteria: Optional[list[str]] = None
    lead: Optional[str] = None
    org_unit_code: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    findings_summary: Optional[str] = None
    limitations: Optional[str] = None


class FindingIn(BaseModel):
    finding: str
    recommendation: Optional[str] = None


class ResponseIn(BaseModel):
    response: str
    response_text: str
    owner: Optional[str] = None
    due_date: Optional[date] = None


@router.get("/evaluations")
def list_evaluations(plan_id: Optional[int] = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return [service.evaluation_dict(db, e, scope) for e in service.visible_evaluations(db, scope, plan_id)]


@router.post("/plans/{plan_id}/evaluations", status_code=201)
def create_evaluation(plan_id: int, body: EvaluationIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ev = service.create_evaluation(db, scope, plan_id, body.model_dump(exclude_none=True))
    db.commit()
    return service.evaluation_dict(db, ev, scope)


@router.get("/evaluations/{eval_id}")
def get_evaluation(eval_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ev, _ = entities.load(db, scope, "evaluation", eval_id)
    return service.evaluation_dict(db, ev, scope)


@router.put("/evaluations/{eval_id}")
def update_evaluation(eval_id: int, body: EvaluationUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ev = service.update_evaluation(db, scope, eval_id, body.model_dump(exclude_unset=True))
    db.commit()
    return service.evaluation_dict(db, ev, scope)


@router.post("/evaluations/{eval_id}/transition")
def transition_evaluation(eval_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ev = service.transition_evaluation(db, scope, eval_id, body.name, body.reason)
    db.commit()
    return service.evaluation_dict(db, ev, scope)


@router.post("/evaluations/{eval_id}/findings", status_code=201)
def add_finding(eval_id: int, body: FindingIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.add_finding(db, scope, eval_id, body.finding, body.recommendation)
    db.commit()
    ev = db.get(Evaluation, eval_id)
    return service.evaluation_dict(db, ev, scope)


@router.post("/responses/{response_id}")
def respond(response_id: int, body: ResponseIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = service.respond(db, scope, response_id, **body.model_dump())
    db.commit()
    ev = db.get(Evaluation, r.evaluation_id)
    return service.evaluation_dict(db, ev, scope)
