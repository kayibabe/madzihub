"""
Strategy and M&E rules.

Who may do what
- Strategy managers (duty) maintain plans, levels, nodes, indicators, targets and cycles.
- Anyone may read the plan structure they have scope for; ancestors of visible nodes are
  shown as context (titles only), never with another unit's figures.
- Reporting: the assigned contributor (or a contributor on the unit) submits; a reviewer
  verifies; an approver approves. Nobody verifies or approves their own submission.
  A locked period or closed cycle refuses every change; an approved value is corrected
  only through a reasoned reopen.

Values
- Approved manual updates are published to ``metric_values`` under the "strategy-updates"
  source, so every figure is read through ``published_series()`` like any other source.
  Not-applicable is stored as status ``na`` with no value; pending is never published.
- Automatic indicators take their value from connected systems; the update carries the
  narrative, variance reason and corrective action.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.database import User
from app.integration.models import AGGREGATIONS, DataSource, Metric, MetricTarget, MetricValue
from app.integration.position import published_series
from app.platform import actions as platform_actions
from app.platform import audit, entities, periods
from app.platform.errors import Conflict, Forbidden, IllegalTransition, Invalid, NotFound
from app.platform.models import Period
from app.platform.notifications import REMINDER_PRODUCERS, notify
from app.platform.scope import ROOT_ORG, Scope, check_unit, resolve_scope
from app.platform.workflow import Transition, Workflow, approval_history
from app.modules.strategy.models import (
    DEFAULT_LABELS, DELIVERY_STATUSES, DELIVERY_TYPES, DQA_CHECKS, DQA_RESULTS, FREQUENCIES, NODE_TYPES,
    POLARITIES, RESULT_TYPES, VALUE_STATES, CycleAssignment, DqaAssessment, Evaluation, Indicator,
    ManagementResponse, Plan, PlanLevel, PlanNode, ProgressUpdate, ReportingCycle,
)

MANUAL_SOURCE = "strategy-updates"
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,39}$")

PLAN_FLOW = Workflow("plan", ("draft", "active", "archived"), [
    Transition("activate", ("draft",), "active"),
    Transition("archive", ("active", "draft"), "archived", reason_required=True),
    Transition("reactivate", ("archived",), "active", reason_required=True),
])
CYCLE_FLOW = Workflow("reporting_cycle", ("draft", "open", "closed"), [
    Transition("open", ("draft",), "open"),
    Transition("close", ("open",), "closed"),
    Transition("reopen", ("closed",), "open", reason_required=True),
])
ASSIGNMENT_FLOW = Workflow("cycle_assignment", ("not_submitted", "submitted", "verified", "approved", "returned"), [
    Transition("submit", ("not_submitted", "returned", "submitted"), "submitted"),
    Transition("verify", ("submitted",), "verified"),
    Transition("approve", ("submitted", "verified"), "approved"),
    Transition("return", ("submitted", "verified"), "returned", reason_required=True),
    Transition("reopen", ("approved",), "returned", reason_required=True),
])
EVALUATION_FLOW = Workflow("evaluation", ("planned", "in_progress", "completed"), [
    Transition("start", ("planned",), "in_progress"),
    Transition("complete", ("in_progress",), "completed"),
    Transition("reopen", ("completed",), "in_progress", reason_required=True),
])


# ── helpers ─────────────────────────────────────────────────────────────────

def _manager(scope: Scope) -> None:
    scope.require_function("strategy_manager")


def _code(value: str, what: str) -> str:
    value = (value or "").strip()
    if not CODE_RE.match(value):
        raise Invalid(f"{what} code must be 1-40 letters, digits, '.', '_' or '-'.")
    return value


def _get(db: Session, model, pk: int, label: str):
    obj = db.get(model, pk)
    if obj is None:
        raise NotFound(f"{label} not found.")
    return obj


def _user_exists(db: Session, username: str | None) -> str | None:
    if not username:
        return None
    if not db.query(User.id).filter(User.username == username, User.is_active.is_(True)).first():
        raise Invalid(f"Unknown or inactive user '{username}'.")
    return username


def indicator_units(ind: Indicator) -> list[str]:
    return list(ind.reporting_units or [ind.org_unit_code])


def indicator_visible(scope: Scope, ind: Indicator) -> bool:
    return scope.can_see(ind.org_unit_code) or any(scope.can_see(u) for u in indicator_units(ind))


def plan_visible(scope: Scope, plan: Plan) -> bool:
    return scope.org_wide or bool(scope.unit_roles)


def _period(db: Session, cycle: ReportingCycle) -> Period:
    return periods.get(db, cycle.period_id)


# ── record types for links, comments and history ────────────────────────────

entities.register(entities.EntityType(
    key="plan", label="Plan", model=Plan, unit_of=lambda p: ROOT_ORG, title_of=lambda p: f"{p.code} {p.title}",
    can_view=plan_visible, page="strategy"))
entities.register(entities.EntityType(
    key="plan_node", label="Plan item", model=PlanNode, unit_of=lambda n: n.org_unit_code,
    title_of=lambda n: f"{n.code} {n.title}", page="strategy"))
entities.register(entities.EntityType(
    key="indicator", label="Indicator", model=Indicator, unit_of=lambda i: i.org_unit_code,
    title_of=lambda i: f"{i.code} {i.name}", can_view=indicator_visible, page="strategy"))
entities.register(entities.EntityType(
    key="cycle_assignment", label="Progress update", model=CycleAssignment, unit_of=lambda a: a.org_unit_code,
    title_of=lambda a: f"Update #{a.id}", page="updates"))
entities.register(entities.EntityType(
    key="evaluation", label="Evaluation", model=Evaluation, unit_of=lambda e: e.org_unit_code,
    title_of=lambda e: e.title, page="evaluations"))
entities.register(entities.EntityType(
    key="management_response", label="Management response", model=ManagementResponse,
    unit_of=lambda r: r.evaluation.org_unit_code if getattr(r, "evaluation", None) else ROOT_ORG,
    title_of=lambda r: (r.finding or "")[:80], page="evaluations"))


# ── plans and levels ────────────────────────────────────────────────────────

def create_plan(db: Session, scope: Scope, *, code: str, title: str, start_fy: int, end_fy: int,
                description: str | None = None) -> Plan:
    _manager(scope)
    code = _code(code, "Plan")
    if db.query(Plan.id).filter_by(code=code).first():
        raise Conflict(f"Plan code '{code}' is already used.")
    if not title.strip():
        raise Invalid("A plan needs a title.")
    if not 1990 <= start_fy <= end_fy <= 2100:
        raise Invalid("The plan must start no later than it ends (fiscal years 1990-2100).")
    plan = Plan(code=code, title=title.strip(), description=description, start_fy=start_fy, end_fy=end_fy,
                status="draft", created_by=scope.username)
    db.add(plan)
    db.flush()
    for node_type in NODE_TYPES:
        db.add(PlanLevel(plan_id=plan.id, node_type=node_type, label=DEFAULT_LABELS[node_type],
                         plural=DEFAULT_LABELS[node_type] + "s", enabled=True))
    audit.record(db, scope.username, "plan.create", "plan", plan.id,
                 after=audit.snapshot(plan, ("code", "title", "start_fy", "end_fy", "status")))
    return plan


def update_plan(db: Session, scope: Scope, plan_id: int, changes: dict) -> Plan:
    _manager(scope)
    plan = _get(db, Plan, plan_id, "Plan")
    if plan.status == "archived":
        raise Conflict("An archived plan cannot be edited; reactivate it first.")
    fields = ("title", "description", "start_fy", "end_fy")
    before = audit.snapshot(plan, fields)
    for k in fields:
        if k in changes and changes[k] is not None:
            setattr(plan, k, changes[k])
    if not 1990 <= plan.start_fy <= plan.end_fy <= 2100:
        raise Invalid("The plan must start no later than it ends.")
    b, a = audit.changed(before, audit.snapshot(plan, fields))
    if a:
        audit.record(db, scope.username, "plan.update", "plan", plan.id, before=b, after=a)
    return plan


def transition_plan(db: Session, scope: Scope, plan_id: int, name: str, reason: str | None = None) -> Plan:
    _manager(scope)
    plan = _get(db, Plan, plan_id, "Plan")
    if name == "activate":
        if not db.query(Indicator.id).filter_by(plan_id=plan.id, status="active").first():
            raise Invalid("Add at least one indicator before activating the plan.")
        plan.approved_by, plan.approved_at = scope.username, datetime.utcnow()
    PLAN_FLOW.apply(db, plan, name, scope.username, reason=reason, step="approve" if name == "activate" else None,
                    decision="approved" if name == "activate" else None)
    return plan


def set_levels(db: Session, scope: Scope, plan_id: int, levels: list[dict]) -> list[PlanLevel]:
    _manager(scope)
    plan = _get(db, Plan, plan_id, "Plan")
    rows = {lv.node_type: lv for lv in db.query(PlanLevel).filter_by(plan_id=plan.id)}
    before = {k: {"label": v.label, "enabled": v.enabled} for k, v in rows.items()}
    for item in levels:
        nt = item.get("node_type")
        if nt not in rows:
            raise Invalid(f"Unknown level '{nt}'. Levels are {', '.join(NODE_TYPES)}.")
        label = (item.get("label") or "").strip()
        if not label:
            raise Invalid("Each level needs a label.")
        rows[nt].label = label[:60]
        rows[nt].plural = (item.get("plural") or label + "s")[:60]
        if "enabled" in item:
            in_use = db.query(PlanNode.id).filter_by(plan_id=plan.id, node_type=nt, retired=False).first()
            if not item["enabled"] and in_use:
                raise Invalid(f"'{rows[nt].label}' is in use and cannot be switched off.")
            rows[nt].enabled = bool(item["enabled"])
    after = {k: {"label": v.label, "enabled": v.enabled} for k, v in rows.items()}
    b, a = audit.changed(before, after)
    if a:
        audit.record(db, scope.username, "plan.levels", "plan", plan.id, before=b, after=a)
    return list(rows.values())


# ── nodes ───────────────────────────────────────────────────────────────────

def _check_parent(db: Session, plan: Plan, node_type: str, parent_id: int | None, self_id: int | None = None) -> None:
    order = RESULT_TYPES if node_type in RESULT_TYPES else DELIVERY_TYPES
    if parent_id is None:
        return
    parent = _get(db, PlanNode, parent_id, "Parent item")
    if parent.plan_id != plan.id:
        raise Invalid("The parent belongs to another plan.")
    if parent.node_type not in order:
        raise Invalid("Results and delivery items are linked, not nested: choose a parent from the same tree "
                      "and link delivery work to results instead.")
    if order.index(parent.node_type) >= order.index(node_type):
        raise Invalid(f"A {DEFAULT_LABELS[node_type].lower()} cannot sit under a "
                      f"{DEFAULT_LABELS[parent.node_type].lower()}.")
    walk = parent
    while walk is not None:
        if self_id is not None and walk.id == self_id:
            raise Invalid("That parent would create a loop.")
        walk = db.get(PlanNode, walk.parent_id) if walk.parent_id else None


def create_node(db: Session, scope: Scope, plan_id: int, data: dict) -> PlanNode:
    _manager(scope)
    plan = _get(db, Plan, plan_id, "Plan")
    if plan.status == "archived":
        raise Conflict("An archived plan cannot be changed.")
    nt = data.get("node_type")
    if nt not in NODE_TYPES:
        raise Invalid(f"Item type must be one of {', '.join(NODE_TYPES)}.")
    level = db.query(PlanLevel).filter_by(plan_id=plan.id, node_type=nt).first()
    if level is not None and not level.enabled:
        raise Invalid(f"The '{level.label}' level is switched off for this plan.")
    code = _code(data.get("code", ""), "Item")
    if db.query(PlanNode.id).filter_by(plan_id=plan.id, code=code).first():
        raise Conflict(f"Code '{code}' is already used in this plan.")
    _check_parent(db, plan, nt, data.get("parent_id"))
    status = data.get("status") or ("not_started" if nt in DELIVERY_TYPES else "on_track")
    if status not in DELIVERY_STATUSES:
        raise Invalid(f"Status must be one of {', '.join(DELIVERY_STATUSES)}.")
    node = PlanNode(plan_id=plan.id, parent_id=data.get("parent_id"), node_type=nt, code=code,
                    title=(data.get("title") or "").strip()[:250], description=data.get("description"),
                    owner=_user_exists(db, data.get("owner")),
                    org_unit_code=check_unit(db, data.get("org_unit_code") or ROOT_ORG),
                    weight=_weight(data.get("weight")), sort_order=int(data.get("sort_order") or 0),
                    start_date=data.get("start_date"), end_date=data.get("end_date"), status=status,
                    budget=data.get("budget"))
    if not node.title:
        raise Invalid("Each item needs a title.")
    db.add(node)
    db.flush()
    audit.record(db, scope.username, "plan_node.create", "plan_node", node.id, org_unit_code=node.org_unit_code,
                 after=audit.snapshot(node, NODE_FIELDS))
    return node


NODE_FIELDS = ("parent_id", "node_type", "code", "title", "description", "owner", "org_unit_code", "weight",
               "sort_order", "start_date", "end_date", "status", "budget", "retired")


def _weight(v) -> float | None:
    if v in (None, ""):
        return None
    w = float(v)
    if not 0 <= w <= 100:
        raise Invalid("Weights are percentages between 0 and 100.")
    return w


def update_node(db: Session, scope: Scope, node_id: int, data: dict, reason: str | None = None) -> PlanNode:
    node = _get(db, PlanNode, node_id, "Plan item")
    plan = _get(db, Plan, node.plan_id, "Plan")
    status_only = set(data) <= {"status", "description"}
    if not scope.has_function("strategy_manager"):
        # The item's owner (or an approver on its unit) may report delivery status only.
        if not (status_only and (node.owner == scope.username or scope.can(node.org_unit_code, "approver"))
                and not scope.read_only):
            raise Forbidden("This needs the strategy manager duty.")
    if plan.status == "archived":
        raise Conflict("An archived plan cannot be changed.")
    before = audit.snapshot(node, NODE_FIELDS)
    if "parent_id" in data:
        _check_parent(db, plan, node.node_type, data["parent_id"], self_id=node.id)
        node.parent_id = data["parent_id"]
    for k in ("title", "description", "start_date", "end_date", "budget", "sort_order"):
        if k in data:
            setattr(node, k, data[k])
    if "owner" in data:
        node.owner = _user_exists(db, data["owner"])
    if "org_unit_code" in data:
        node.org_unit_code = check_unit(db, data["org_unit_code"])
    if "weight" in data:
        node.weight = _weight(data["weight"])
    if "status" in data:
        if data["status"] not in DELIVERY_STATUSES:
            raise Invalid(f"Status must be one of {', '.join(DELIVERY_STATUSES)}.")
        node.status = data["status"]
    if "retired" in data:
        if data["retired"] and not (reason or "").strip():
            raise Invalid("Retiring an item needs a reason.")
        node.retired = bool(data["retired"])
    if not (node.title or "").strip():
        raise Invalid("Each item needs a title.")
    b, a = audit.changed(before, audit.snapshot(node, NODE_FIELDS))
    if a:
        audit.record(db, scope.username, "plan_node.update", "plan_node", node.id, before=b, after=a,
                     reason=reason, org_unit_code=node.org_unit_code)
    return node


# ── indicators ──────────────────────────────────────────────────────────────

DEFINITION_FIELDS = ("name", "definition", "metric_code", "polarity", "unit", "aggregation", "formula_text",
                     "source", "baseline_value", "baseline_date", "target_basis", "frequency",
                     "evidence_required", "valid_min", "valid_max", "collection")
ADMIN_FIELDS = ("node_id", "owner", "org_unit_code", "reporting_units", "dq_notes", "weight", "status")
INDICATOR_FIELDS = DEFINITION_FIELDS + ADMIN_FIELDS + ("code", "version")


def _metric_slug(plan: Plan, code: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", f"ind_{plan.code}_{code}".lower())[:80]


def _ensure_metric(db: Session, plan: Plan, ind: Indicator) -> None:
    direction = ind.polarity if ind.polarity in ("higher", "lower", "range") else (
        "lower" if ind.polarity == "kri" else "higher")
    agg = ind.aggregation if ind.aggregation in AGGREGATIONS else "last"
    m = db.query(Metric).filter_by(code=ind.metric_code).first()
    if m is None:
        db.add(Metric(code=ind.metric_code, name=ind.name[:160], unit=ind.unit, category="Strategy",
                      aggregation=agg, direction=direction, description=ind.definition))
        db.flush()


def _validate_indicator(db: Session, ind: Indicator) -> None:
    if ind.polarity not in POLARITIES:
        raise Invalid(f"Polarity must be one of {', '.join(POLARITIES)}.")
    if ind.frequency not in FREQUENCIES:
        raise Invalid(f"Frequency must be one of {', '.join(FREQUENCIES)}.")
    if ind.aggregation not in AGGREGATIONS:
        raise Invalid(f"Aggregation must be one of {', '.join(AGGREGATIONS)}.")
    if ind.collection not in ("manual", "automatic"):
        raise Invalid("Collection must be manual or automatic.")
    if not (ind.name or "").strip():
        raise Invalid("An indicator needs a name.")
    if ind.valid_min is not None and ind.valid_max is not None and ind.valid_min > ind.valid_max:
        raise Invalid("The valid range minimum is above its maximum.")
    if ind.node_id is not None:
        node = db.get(PlanNode, ind.node_id)
        if node is None or node.plan_id != ind.plan_id or node.node_type not in RESULT_TYPES:
            raise Invalid("An indicator measures a results item (pillar, objective, outcome or output) of its plan.")
    ind.org_unit_code = check_unit(db, ind.org_unit_code)
    units = [check_unit(db, u) for u in (ind.reporting_units or [])]
    ind.reporting_units = sorted(set(units)) or None
    ind.owner = _user_exists(db, ind.owner)
    if ind.collection == "automatic" and not db.query(Metric.id).filter_by(code=ind.metric_code).first():
        raise Invalid(f"Automatic indicators read an existing catalogue measure; '{ind.metric_code}' is not in it.")


def create_indicator(db: Session, scope: Scope, plan_id: int, data: dict) -> Indicator:
    _manager(scope)
    plan = _get(db, Plan, plan_id, "Plan")
    if plan.status == "archived":
        raise Conflict("An archived plan cannot be changed.")
    code = _code(data.get("code", ""), "Indicator")
    if db.query(Indicator.id).filter_by(plan_id=plan.id, code=code).first():
        raise Conflict(f"Indicator code '{code}' is already used in this plan.")
    values = {k: data.get(k) for k in DEFINITION_FIELDS + ADMIN_FIELDS if k in data}
    ind = Indicator(plan_id=plan.id, code=code, created_by=scope.username, version=1,
                    polarity=values.pop("polarity", None) or "higher",
                    aggregation=values.pop("aggregation", None) or "sum",
                    frequency=values.pop("frequency", None) or "quarter",
                    collection=values.pop("collection", None) or "manual",
                    org_unit_code=values.pop("org_unit_code", None) or ROOT_ORG,
                    status=values.pop("status", None) or "active",
                    evidence_required=bool(values.pop("evidence_required", False)),
                    metric_code=(values.pop("metric_code", None) or _metric_slug(plan, code)).strip(),
                    **values)
    _validate_indicator(db, ind)
    db.add(ind)
    _ensure_metric(db, plan, ind)
    db.flush()
    audit.record(db, scope.username, "indicator.create", "indicator", ind.id, org_unit_code=ind.org_unit_code,
                 after=audit.snapshot(ind, INDICATOR_FIELDS))
    return ind


def update_indicator(db: Session, scope: Scope, indicator_id: int, data: dict, reason: str | None = None) -> Indicator:
    _manager(scope)
    ind = _get(db, Indicator, indicator_id, "Indicator")
    before = audit.snapshot(ind, INDICATOR_FIELDS)
    for k in DEFINITION_FIELDS + ADMIN_FIELDS:
        if k in data:
            setattr(ind, k, data[k])
    _validate_indicator(db, ind)
    definition_changed = any(before[k] != audit.snapshot(ind, (k,))[k] for k in DEFINITION_FIELDS)
    if definition_changed:
        if not (reason or "").strip():
            raise Invalid("Changing an indicator's definition needs a reason (it creates a new version).")
        ind.version = (ind.version or 1) + 1
    plan = _get(db, Plan, ind.plan_id, "Plan")
    _ensure_metric(db, plan, ind)
    b, a = audit.changed(before, audit.snapshot(ind, INDICATOR_FIELDS))
    if a:
        audit.record(db, scope.username, "indicator.update", "indicator", ind.id, before=b, after=a, reason=reason,
                     org_unit_code=ind.org_unit_code)
    return ind


def indicator_versions(db: Session, ind: Indicator) -> set[int]:
    return set(range(1, (ind.version or 1) + 1))


def set_targets(db: Session, scope: Scope, indicator_id: int, targets: list[dict], reason: str | None = None) -> list:
    """Upsert the indicator's period targets (basis: strategic plan, tagged with the plan)."""
    _manager(scope)
    ind = _get(db, Indicator, indicator_id, "Indicator")
    out = []
    for t in targets:
        ptype = t.get("period_type") or "year"
        if ptype not in FREQUENCIES:
            raise Invalid("Target periods are month, quarter or year.")
        start = t.get("period_start")
        if isinstance(start, str):
            start = date.fromisoformat(start)
        from app.integration.mapping import period_start as pstart
        if start is None or pstart(start, ptype) != start:
            raise Invalid(f"{start} is not the start of a {ptype} on the fiscal calendar.")
        unit = check_unit(db, t.get("org_unit_code") or ind.org_unit_code)
        key = dict(metric_code=ind.metric_code, org_unit_code=unit, period_type=ptype, period_start=start,
                   basis="strategic_plan")
        row = db.query(MetricTarget).filter_by(**key).first()
        before = None if row is None else {"value": row.value, "lower": row.lower, "upper": row.upper}
        if t.get("delete"):
            if row is not None:
                db.delete(row)
                audit.record(db, scope.username, "indicator.target_delete", "indicator", ind.id, before={
                    **before, "period_start": start, "period_type": ptype, "org_unit_code": unit}, reason=reason)
            continue
        value = t.get("value")
        if value is None:
            raise Invalid("Each target needs a value (or delete it).")
        if ind.polarity == "range" and (t.get("lower") is None or t.get("upper") is None):
            raise Invalid("Range indicators need a lower and an upper bound for each target.")
        if t.get("lower") is not None and t.get("upper") is not None and t["lower"] > t["upper"]:
            raise Invalid("The lower bound is above the upper bound.")
        if row is None:
            row = MetricTarget(**key)
            db.add(row)
        if before is not None and before["value"] != value and not (reason or "").strip():
            raise Invalid("Changing an agreed target needs a reason.")
        row.value, row.lower, row.upper = float(value), t.get("lower"), t.get("upper")
        row.plan_id, row.note = ind.plan_id, f"{ind.code} {ind.name}"[:300]
        audit.record(db, scope.username, "indicator.target", "indicator", ind.id, before=before,
                     after={"period_type": ptype, "period_start": start, "org_unit_code": unit, "value": row.value,
                            "lower": row.lower, "upper": row.upper}, reason=reason, org_unit_code=unit)
        out.append(row)
    db.flush()
    return out


def targets_for(db: Session, ind: Indicator, scope: Scope | None = None) -> list[dict]:
    q = db.query(MetricTarget).filter(MetricTarget.metric_code == ind.metric_code)
    rows = q.order_by(MetricTarget.period_start, MetricTarget.org_unit_code).all()
    from app.integration.mapping import period_label
    return [{"id": t.id, "org_unit_code": t.org_unit_code, "period_type": t.period_type,
             "period_start": t.period_start.isoformat(), "label": period_label(t.period_start, t.period_type),
             "value": t.value, "lower": t.lower, "upper": t.upper, "basis": t.basis, "plan_id": t.plan_id}
            for t in rows if scope is None or scope.can_see(t.org_unit_code)]


def target_for(db: Session, ind: Indicator, unit: str, period: Period) -> MetricTarget | None:
    exact = db.query(MetricTarget).filter_by(metric_code=ind.metric_code, org_unit_code=unit,
                                             period_type=period.period_type, period_start=period.start_date).first()
    return exact


def off_target(polarity: str, value: float | None, target: MetricTarget | None) -> bool | None:
    if value is None or target is None:
        return None
    if polarity == "range":
        if target.lower is None or target.upper is None:
            return None
        return not (target.lower <= value <= target.upper)
    if polarity in ("lower", "kri"):
        return value > target.value
    return value < target.value


# ── cycles and assignments ──────────────────────────────────────────────────

def create_cycle(db: Session, scope: Scope, plan_id: int, *, period_id: int, name: str | None = None,
                 opens_on: date | None = None, due_on: date | None = None,
                 require_verification: bool = True) -> ReportingCycle:
    _manager(scope)
    plan = _get(db, Plan, plan_id, "Plan")
    if plan.status != "active":
        raise Conflict("Reporting cycles run on an active plan.")
    period = periods.get(db, period_id)
    periods.assert_open(db, period)
    if db.query(ReportingCycle.id).filter_by(plan_id=plan.id, period_id=period.id).first():
        raise Conflict(f"{plan.code} already has a cycle for {period.label}.")
    if opens_on and due_on and due_on < opens_on:
        raise Invalid("The due date is before the opening date.")
    cycle = ReportingCycle(plan_id=plan.id, period_id=period.id, name=(name or f"{period.label} progress")[:120],
                           opens_on=opens_on, due_on=due_on or (period.end_date + timedelta(days=15)),
                           require_verification=bool(require_verification), status="draft",
                           created_by=scope.username)
    db.add(cycle)
    db.flush()
    audit.record(db, scope.username, "reporting_cycle.create", "reporting_cycle", cycle.id,
                 after=audit.snapshot(cycle, ("plan_id", "period_id", "name", "opens_on", "due_on",
                                              "require_verification")))
    return cycle


def generate_assignments(db: Session, scope: Scope, cycle_id: int) -> int:
    """One assignment per active indicator of the cycle's frequency and per reporting unit."""
    _manager(scope)
    cycle = _get(db, ReportingCycle, cycle_id, "Reporting cycle")
    if cycle.status == "closed":
        raise Conflict("The cycle is closed.")
    period = _period(db, cycle)
    existing = {(a.indicator_id, a.org_unit_code) for a in db.query(CycleAssignment).filter_by(cycle_id=cycle.id)}
    created = 0
    for ind in db.query(Indicator).filter_by(plan_id=cycle.plan_id, status="active",
                                             frequency=period.period_type).order_by(Indicator.code):
        for unit in indicator_units(ind):
            if (ind.id, unit) in existing:
                continue
            db.add(CycleAssignment(cycle_id=cycle.id, indicator_id=ind.id, org_unit_code=unit,
                                   contributor=ind.owner, status="not_submitted"))
            created += 1
    db.flush()
    if created:
        audit.record(db, scope.username, "reporting_cycle.generate", "reporting_cycle", cycle.id,
                     after={"assignments_created": created})
    return created


def transition_cycle(db: Session, scope: Scope, cycle_id: int, name: str, reason: str | None = None) -> ReportingCycle:
    _manager(scope)
    cycle = _get(db, ReportingCycle, cycle_id, "Reporting cycle")
    periods.assert_open(db, _period(db, cycle))
    if name == "open" and not db.query(CycleAssignment.id).filter_by(cycle_id=cycle.id).first():
        raise Invalid("Generate the assignments before opening the cycle.")
    CYCLE_FLOW.apply(db, cycle, name, scope.username, reason=reason)
    if name == "open":
        for a in db.query(CycleAssignment).filter_by(cycle_id=cycle.id, status="not_submitted"):
            notify(db, a.contributor, "update_requested", f"Progress update requested: {cycle.name}",
                   body=f"Due {cycle.due_on.isoformat()}." if cycle.due_on else None,
                   entity_type="cycle_assignment", entity_id=a.id)
    return cycle


def update_assignment(db: Session, scope: Scope, assignment_id: int, data: dict) -> CycleAssignment:
    _manager(scope)
    a = _get(db, CycleAssignment, assignment_id, "Assignment")
    fields = ("contributor", "reviewer", "approver")
    before = audit.snapshot(a, fields)
    for k in fields:
        if k in data:
            setattr(a, k, _user_exists(db, data[k]))
    b, after = audit.changed(before, audit.snapshot(a, fields))
    if after:
        audit.record(db, scope.username, "cycle_assignment.assign", "cycle_assignment", a.id, before=b, after=after,
                     org_unit_code=a.org_unit_code)
        if "contributor" in after and a.status in ("not_submitted", "returned"):
            notify(db, a.contributor, "update_requested", "A progress update has been assigned to you",
                   entity_type="cycle_assignment", entity_id=a.id)
    return a


def _load_assignment(db: Session, scope: Scope, assignment_id: int) -> tuple[CycleAssignment, ReportingCycle,
                                                                            Indicator, Period]:
    a, _ = entities.load(db, scope, "cycle_assignment", assignment_id)
    cycle = _get(db, ReportingCycle, a.cycle_id, "Reporting cycle")
    ind = _get(db, Indicator, a.indicator_id, "Indicator")
    return a, cycle, ind, _period(db, cycle)


def _latest(db: Session, a: CycleAssignment) -> ProgressUpdate | None:
    return db.get(ProgressUpdate, a.current_update_id) if a.current_update_id else None


def _published_value(db: Session, ind: Indicator, unit: str, period: Period, exclude_manual: bool = False):
    metric = db.query(Metric).filter_by(code=ind.metric_code).first()
    if metric is None:
        return None
    if exclude_manual:
        src = db.query(DataSource).filter_by(code=MANUAL_SOURCE).first()
        q = db.query(MetricValue).filter(MetricValue.metric_code == metric.code, MetricValue.org_unit_code == unit,
                                         MetricValue.period_type == period.period_type,
                                         MetricValue.period_start == period.start_date, MetricValue.value.isnot(None))
        if src is not None:
            q = q.filter(MetricValue.source_id != src.id)
        row = q.first()
        return None if row is None else row.value
    series, _ = published_series(db, metric, unit, period.period_type, period.start_date, period.start_date)
    return series[0]["value"] if series else None


def previous_value(db: Session, ind: Indicator, unit: str, period: Period) -> dict | None:
    metric = db.query(Metric).filter_by(code=ind.metric_code).first()
    if metric is None:
        return None
    series, _ = published_series(db, metric, unit, period.period_type, None, period.start_date - timedelta(days=1))
    return series[-1] if series else None


def run_dqa(db: Session, a: CycleAssignment, cycle: ReportingCycle, ind: Indicator, period: Period,
            upd: ProgressUpdate) -> list[DqaAssessment]:
    """Automatic checks at submission. Results are recorded; the value is never changed."""
    out: list[tuple[str, str, str]] = []
    reported = upd.value_state == "reported"
    if upd.late and cycle.due_on:
        days = (upd.submitted_at.date() - cycle.due_on).days
        out.append(("timeliness", "warn", f"Submitted {days} day(s) after the due date ({cycle.due_on.isoformat()})."))
    else:
        out.append(("timeliness", "pass", "Submitted on time."))
    if reported and (ind.valid_min is not None or ind.valid_max is not None):
        lo, hi = ind.valid_min, ind.valid_max
        if (lo is not None and upd.value < lo) or (hi is not None and upd.value > hi):
            out.append(("range", "fail", f"{upd.value:g} is outside the valid range "
                                         f"{'' if lo is None else f'{lo:g}'}–{'' if hi is None else f'{hi:g}'}."))
        else:
            out.append(("range", "pass", "Within the valid range."))
    if upd.value_state == "pending":
        out.append(("completeness", "warn", "No figure yet: the value is pending."))
    elif reported:
        miss = off_target(ind.polarity, upd.value, target_for(db, ind, a.org_unit_code, period))
        if miss and not (upd.variance_reason or "").strip():
            out.append(("completeness", "warn", "Off target without a variance explanation."))
        else:
            out.append(("completeness", "pass", "Required explanations present."))
    if ind.evidence_required:
        has_links = bool(_evidence_links(db, a.id))
        if not (upd.evidence_note or "").strip() and not has_links:
            out.append(("evidence", "fail", "Evidence is required for this indicator but none was supplied."))
        else:
            out.append(("evidence", "pass", "Evidence supplied."))
    if reported:
        prev = previous_value(db, ind, a.org_unit_code, period)
        notes = []
        if prev and prev["value"] not in (None, 0) and abs(upd.value - prev["value"]) > 0.5 * abs(prev["value"]):
            notes.append(f"changed {((upd.value - prev['value']) / abs(prev['value']) * 100):+.0f}% from the previous "
                         f"period ({prev['value']:g})")
        if ind.collection == "manual":
            other = _published_value(db, ind, a.org_unit_code, period, exclude_manual=True)
            if other is not None and abs(other - upd.value) > max(1e-9, 0.01 * abs(other)):
                notes.append(f"a connected system reports {other:g} for the same period")
        out.append(("consistency", "warn" if notes else "pass",
                    ("Check: " + "; ".join(notes) + ".") if notes else "Consistent with history and other sources."))
    rows = [DqaAssessment(update_id=upd.id, check=c, result=r, reason=why, assessed_by="system") for c, r, why in out]
    db.add_all(rows)
    return rows


def _evidence_links(db: Session, assignment_id: int) -> list:
    from app.platform.models import EntityLink
    return db.query(EntityLink).filter_by(from_type="cycle_assignment", from_id=str(assignment_id),
                                          relation="evidence").all()


def submit_update(db: Session, scope: Scope, assignment_id: int, data: dict) -> ProgressUpdate:
    a, cycle, ind, period = _load_assignment(db, scope, assignment_id)
    if cycle.status != "open":
        raise Conflict("This cycle is not open for submissions.")
    periods.assert_open(db, period)
    if not (a.contributor == scope.username or scope.can(a.org_unit_code, "contributor")) or scope.read_only:
        raise Forbidden("Only the assigned contributor or a contributor on this unit can submit.")
    state = data.get("value_state") or "reported"
    if state not in VALUE_STATES:
        raise Invalid(f"Value state must be one of {', '.join(VALUE_STATES)}.")
    value = data.get("value")
    source = "manual"
    if ind.collection == "automatic":
        source = "automatic"
        if state == "reported":
            value = _published_value(db, ind, a.org_unit_code, period)
            if value is None:
                raise Invalid("This indicator's value comes from connected systems and none is published for the "
                              "period yet. Submit it as pending, or as not applicable.")
    elif state == "reported":
        if value is None:
            raise Invalid("Enter a value, or mark the update as pending or not applicable (these are not zero).")
        if ind.polarity == "yes_no" and value not in (0, 1):
            raise Invalid("Yes/no indicators take 1 (yes) or 0 (no).")
    else:
        value = None
    if state == "not_applicable" and not (data.get("narrative") or "").strip():
        raise Invalid("Explain why the indicator does not apply this period.")
    revision = (db.query(ProgressUpdate).filter_by(assignment_id=a.id).count()) + 1
    now = datetime.utcnow()
    upd = ProgressUpdate(assignment_id=a.id, revision=revision, value_state=state,
                         value=None if value is None else float(value), forecast=data.get("forecast"),
                         narrative=data.get("narrative"), variance_reason=data.get("variance_reason"),
                         corrective_action=data.get("corrective_action"), evidence_note=data.get("evidence_note"),
                         value_source=source, submitted_by=scope.username, submitted_at=now,
                         late=bool(cycle.due_on and now.date() > cycle.due_on))
    db.add(upd)
    db.flush()
    ASSIGNMENT_FLOW.apply(db, a, "submit", scope.username, org_unit_code=a.org_unit_code,
                          extra_after={"revision": revision, "value_state": state, "value": upd.value},
                          step="submit", decision="submitted")
    a.current_update_id = upd.id
    run_dqa(db, a, cycle, ind, period, upd)
    reviewer = a.reviewer if cycle.require_verification else a.approver
    if reviewer and reviewer != scope.username:
        notify(db, reviewer, "update_submitted", f"Progress update to review: {ind.code} {ind.name}",
               entity_type="cycle_assignment", entity_id=a.id)
    return upd


def _publish(db: Session, actor: str, a: CycleAssignment, ind: Indicator, period: Period, upd: ProgressUpdate) -> None:
    if upd.value_source != "manual" or upd.value_state == "pending":
        return
    src = db.query(DataSource).filter_by(code=MANUAL_SOURCE).first()
    if src is None:
        src = DataSource(code=MANUAL_SOURCE, name="Approved progress updates (strategy module)", system_type="other",
                         connector="push", priority=400, config={}, mapping={}, enabled=True,
                         owner="Strategy module")
        db.add(src)
        db.flush()
    key = dict(metric_code=ind.metric_code, org_unit_code=a.org_unit_code, period_type=period.period_type,
               period_start=period.start_date, source_id=src.id)
    row = db.query(MetricValue).filter_by(**key).first()
    before = None if row is None else {"value": row.value, "status": row.status, "source_ref": row.source_ref}
    if row is None:
        row = MetricValue(**key)
        db.add(row)
    row.value = upd.value if upd.value_state == "reported" else None
    row.status = "actual" if upd.value_state == "reported" else "na"
    row.source_ref = f"progress_update:{upd.id}"
    row.loaded_at = datetime.utcnow()
    audit.record(db, actor, "metric_value.publish", "indicator", ind.id, before=before,
                 after={"value": row.value, "status": row.status, "source_ref": row.source_ref,
                        "org_unit_code": a.org_unit_code, "period": period.label},
                 org_unit_code=a.org_unit_code)


def review_update(db: Session, scope: Scope, assignment_id: int, name: str, reason: str | None = None) -> CycleAssignment:
    a, cycle, ind, period = _load_assignment(db, scope, assignment_id)
    t = ASSIGNMENT_FLOW.check(a, name, reason)
    periods.assert_open(db, period)
    upd = _latest(db, a)
    submitter = upd.submitted_by if upd else None
    if name == "verify":
        if not cycle.require_verification:
            raise IllegalTransition("This cycle does not use a verification step; approve directly.")
        if not scope.can(a.org_unit_code, "reviewer"):
            raise Forbidden("Verifying needs the reviewer role on this unit.")
    elif name == "approve":
        if cycle.require_verification and a.status != "verified":
            raise IllegalTransition("This update must be verified before it can be approved.")
        if not scope.can(a.org_unit_code, "approver"):
            raise Forbidden("Approving needs the approver role on this unit.")
        if upd and upd.value_state == "pending":
            raise Invalid("A pending update has no figure to approve; return it for the value.")
    elif name == "return":
        if not scope.can(a.org_unit_code, "reviewer"):
            raise Forbidden("Returning needs the reviewer role on this unit.")
    elif name == "reopen":
        if not scope.can(a.org_unit_code, "approver"):
            raise Forbidden("Reopening an approved update needs the approver role on this unit.")
        if cycle.status == "closed":
            raise Conflict("Reopen the cycle before correcting an update in it.")
    if name in ("verify", "approve") and submitter == scope.username:
        raise Forbidden("You cannot verify or approve your own submission.")
    if name == "verify" and a.reviewer and a.reviewer != scope.username and not scope.can(a.org_unit_code, "approver"):
        raise Forbidden(f"This update is assigned to {a.reviewer} for verification.")
    decision = {"verify": "approved", "approve": "approved", "return": "returned", "reopen": "reopened"}[name]
    ASSIGNMENT_FLOW.apply(db, a, t.name, scope.username, reason=reason, org_unit_code=a.org_unit_code,
                          extra_after={"revision": upd.revision if upd else None}, step=name, decision=decision)
    if name == "approve" and upd:
        _publish(db, scope.username, a, ind, period, upd)
    if name == "verify" and a.approver and a.approver != scope.username:
        notify(db, a.approver, "update_verified", f"Verified, awaiting approval: {ind.code} {ind.name}",
               entity_type="cycle_assignment", entity_id=a.id)
    if name in ("return", "reopen") and submitter:
        notify(db, a.contributor or submitter, "update_returned", f"Returned for correction: {ind.code} {ind.name}",
               body=reason, entity_type="cycle_assignment", entity_id=a.id)
    return a


def add_dqa(db: Session, scope: Scope, assignment_id: int, check: str, result: str, reason: str) -> DqaAssessment:
    a, cycle, ind, period = _load_assignment(db, scope, assignment_id)
    if not scope.can(a.org_unit_code, "reviewer"):
        raise Forbidden("Recording a data-quality assessment needs the reviewer role on this unit.")
    if check not in DQA_CHECKS or result not in DQA_RESULTS:
        raise Invalid("Unknown check or result.")
    if not (reason or "").strip():
        raise Invalid("Record the reason for the assessment.")
    upd = _latest(db, a)
    if upd is None:
        raise Invalid("There is no submission to assess yet.")
    row = DqaAssessment(update_id=upd.id, check=check, result=result, reason=reason.strip(), assessed_by=scope.username)
    db.add(row)
    audit.record(db, scope.username, "dqa.assess", "cycle_assignment", a.id,
                 after={"revision": upd.revision, "check": check, "result": result}, reason=reason,
                 org_unit_code=a.org_unit_code)
    return row


def assignment_query(db: Session, scope: Scope, *, cycle_id: int | None = None, queue: str | None = None):
    q = scope.filter(db.query(CycleAssignment), CycleAssignment.org_unit_code)
    if cycle_id:
        q = q.filter(CycleAssignment.cycle_id == cycle_id)
    rows = q.order_by(CycleAssignment.cycle_id.desc(), CycleAssignment.id).all()
    if not queue:
        return rows
    cycles = {c.id: c for c in db.query(ReportingCycle).filter(ReportingCycle.id.in_({r.cycle_id for r in rows} or {0}))}
    out = []
    today = date.today()
    for a in rows:
        c = cycles[a.cycle_id]
        upd = _latest(db, a)
        mine = upd is not None and upd.submitted_by == scope.username
        if queue == "submit":
            ok = c.status == "open" and a.status in ("not_submitted", "returned") and (
                a.contributor == scope.username or (a.contributor is None and scope.can(a.org_unit_code, "contributor")))
        elif queue == "verify":
            ok = c.require_verification and a.status == "submitted" and not mine and \
                scope.can(a.org_unit_code, "reviewer") and (a.reviewer in (None, scope.username))
        elif queue == "approve":
            ok = a.status == ("verified" if c.require_verification else "submitted") and not mine and \
                scope.can(a.org_unit_code, "approver") and (a.approver in (None, scope.username))
        elif queue == "overdue":
            ok = c.status == "open" and a.status in ("not_submitted", "returned") and c.due_on is not None and c.due_on < today
        else:
            ok = True
        if ok:
            out.append(a)
    return out


def assignment_dict(db: Session, a: CycleAssignment, scope: Scope, detail: bool = False) -> dict:
    cycle = db.get(ReportingCycle, a.cycle_id)
    ind = db.get(Indicator, a.indicator_id)
    period = db.get(Period, cycle.period_id)
    upd = _latest(db, a)
    target = target_for(db, ind, a.org_unit_code, period)
    d = {"id": a.id, "cycle_id": cycle.id, "cycle_name": cycle.name, "cycle_status": cycle.status,
         "due_on": cycle.due_on.isoformat() if cycle.due_on else None, "period": period.label,
         "period_id": period.id, "period_status": period.status,
         "require_verification": cycle.require_verification,
         "indicator": {"id": ind.id, "code": ind.code, "name": ind.name, "unit": ind.unit, "polarity": ind.polarity,
                       "collection": ind.collection, "evidence_required": ind.evidence_required,
                       "version": ind.version},
         "org_unit_code": a.org_unit_code, "contributor": a.contributor, "reviewer": a.reviewer,
         "approver": a.approver, "status": a.status,
         "overdue": bool(cycle.status == "open" and a.status in ("not_submitted", "returned") and cycle.due_on
                         and cycle.due_on < date.today()),
         "target": None if target is None else {"value": target.value, "lower": target.lower, "upper": target.upper},
         "latest": None if upd is None else update_dict(upd),
         "off_target": off_target(ind.polarity, upd.value if upd else None, target)}
    d["allowed"] = _allowed(scope, a, cycle, upd)
    if detail:
        d["revisions"] = [update_dict(u, db) for u in db.query(ProgressUpdate).filter_by(assignment_id=a.id)
                          .order_by(ProgressUpdate.revision.desc())]
        d["approvals"] = approval_history(db, "cycle_assignment", a.id)
        prev = previous_value(db, ind, a.org_unit_code, period)
        d["previous"] = prev and {"period": prev["period"], "value": prev["value"]}
        d["published"] = _published_value(db, ind, a.org_unit_code, period)
        d["indicator"].update({"definition": ind.definition, "baseline_value": ind.baseline_value,
                               "baseline_date": ind.baseline_date.isoformat() if ind.baseline_date else None,
                               "valid_min": ind.valid_min, "valid_max": ind.valid_max, "source": ind.source,
                               "formula_text": ind.formula_text, "dq_notes": ind.dq_notes})
    return d


def _allowed(scope: Scope, a: CycleAssignment, cycle: ReportingCycle, upd: ProgressUpdate | None) -> list[str]:
    if scope.read_only:
        return []
    out = []
    mine = upd is not None and upd.submitted_by == scope.username
    if cycle.status == "open" and a.status in ("not_submitted", "returned", "submitted") and (
            a.contributor == scope.username or scope.can(a.org_unit_code, "contributor")):
        out.append("submit")
    if a.status == "submitted" and cycle.require_verification and not mine and scope.can(a.org_unit_code, "reviewer"):
        out.append("verify")
    if a.status == ("verified" if cycle.require_verification else "submitted") and not mine and \
            scope.can(a.org_unit_code, "approver") and not (upd and upd.value_state == "pending"):
        out.append("approve")
    if a.status in ("submitted", "verified") and scope.can(a.org_unit_code, "reviewer"):
        out.append("return")
    if a.status == "approved" and cycle.status == "open" and scope.can(a.org_unit_code, "approver"):
        out.append("reopen")
    return out


def update_dict(u: ProgressUpdate, db: Session | None = None) -> dict:
    d = {"id": u.id, "revision": u.revision, "value_state": u.value_state, "value": u.value, "forecast": u.forecast,
         "narrative": u.narrative, "variance_reason": u.variance_reason, "corrective_action": u.corrective_action,
         "evidence_note": u.evidence_note, "value_source": u.value_source, "submitted_by": u.submitted_by,
         "submitted_at": u.submitted_at.isoformat() if u.submitted_at else None, "late": u.late}
    if db is not None:
        d["dqa"] = [{"check": r.check, "result": r.result, "reason": r.reason, "assessed_by": r.assessed_by,
                     "assessed_at": r.assessed_at.isoformat() if r.assessed_at else None}
                    for r in db.query(DqaAssessment).filter_by(update_id=u.id).order_by(DqaAssessment.id)]
    return d


def cycle_dict(db: Session, c: ReportingCycle, scope: Scope) -> dict:
    period = db.get(Period, c.period_id)
    rows = scope.filter(db.query(CycleAssignment.status), CycleAssignment.org_unit_code).filter(
        CycleAssignment.cycle_id == c.id).all()
    counts: dict[str, int] = {}
    for (s,) in rows:
        counts[s] = counts.get(s, 0) + 1
    return {"id": c.id, "plan_id": c.plan_id, "name": c.name, "period_id": c.period_id, "period": period.label,
            "period_type": period.period_type, "period_status": period.status,
            "opens_on": c.opens_on.isoformat() if c.opens_on else None,
            "due_on": c.due_on.isoformat() if c.due_on else None, "require_verification": c.require_verification,
            "status": c.status, "counts": counts, "total": len(rows), "created_by": c.created_by,
            "allowed": [] if not scope.has_function("strategy_manager") or scope.read_only else CYCLE_FLOW.allowed(c.status)}


# ── evaluations ─────────────────────────────────────────────────────────────

EVAL_FIELDS = ("title", "kind", "scope", "method", "criteria", "lead", "org_unit_code", "start_date", "end_date",
               "findings_summary", "limitations")


def create_evaluation(db: Session, scope: Scope, plan_id: int, data: dict) -> Evaluation:
    _manager(scope)
    plan = _get(db, Plan, plan_id, "Plan")
    if data.get("kind", "mid_term") not in ("mid_term", "end_term", "thematic", "other"):
        raise Invalid("Kind must be mid_term, end_term, thematic or other.")
    ev = Evaluation(plan_id=plan.id, created_by=scope.username, status="planned",
                    **{k: data.get(k) for k in EVAL_FIELDS if k in data})
    ev.kind = ev.kind or "mid_term"
    ev.org_unit_code = check_unit(db, ev.org_unit_code or ROOT_ORG)
    ev.lead = _user_exists(db, ev.lead)
    if not (ev.title or "").strip():
        raise Invalid("An evaluation needs a title.")
    db.add(ev)
    db.flush()
    audit.record(db, scope.username, "evaluation.create", "evaluation", ev.id, after=audit.snapshot(ev, EVAL_FIELDS),
                 org_unit_code=ev.org_unit_code)
    return ev


def _may_edit_eval(scope: Scope, ev: Evaluation) -> bool:
    return not scope.read_only and (scope.has_function("strategy_manager") or ev.lead == scope.username)


def update_evaluation(db: Session, scope: Scope, eval_id: int, data: dict) -> Evaluation:
    ev, _ = entities.load(db, scope, "evaluation", eval_id)
    if not _may_edit_eval(scope, ev):
        raise Forbidden("Only the evaluation lead or a strategy manager can edit it.")
    if ev.status == "completed":
        raise Conflict("A completed evaluation is read-only; reopen it with a reason to change it.")
    before = audit.snapshot(ev, EVAL_FIELDS)
    for k in EVAL_FIELDS:
        if k in data:
            setattr(ev, k, data[k])
    ev.org_unit_code = check_unit(db, ev.org_unit_code)
    ev.lead = _user_exists(db, ev.lead)
    b, a = audit.changed(before, audit.snapshot(ev, EVAL_FIELDS))
    if a:
        audit.record(db, scope.username, "evaluation.update", "evaluation", ev.id, before=b, after=a,
                     org_unit_code=ev.org_unit_code)
    return ev


def transition_evaluation(db: Session, scope: Scope, eval_id: int, name: str, reason: str | None = None) -> Evaluation:
    ev, _ = entities.load(db, scope, "evaluation", eval_id)
    if not _may_edit_eval(scope, ev):
        raise Forbidden("Only the evaluation lead or a strategy manager can change its status.")
    if name == "complete":
        if not (ev.findings_summary or "").strip():
            raise Invalid("Record the findings before completing the evaluation.")
        open_items = db.query(ManagementResponse).filter_by(evaluation_id=ev.id, response=None).count()
        if open_items:
            raise Invalid(f"{open_items} finding(s) still need a management response.")
    EVALUATION_FLOW.apply(db, ev, name, scope.username, reason=reason, org_unit_code=ev.org_unit_code)
    return ev


def add_finding(db: Session, scope: Scope, eval_id: int, finding: str, recommendation: str | None) -> ManagementResponse:
    ev, _ = entities.load(db, scope, "evaluation", eval_id)
    if not _may_edit_eval(scope, ev):
        raise Forbidden("Only the evaluation lead or a strategy manager can record findings.")
    if ev.status == "completed":
        raise Conflict("The evaluation is completed.")
    if not (finding or "").strip():
        raise Invalid("Describe the finding.")
    r = ManagementResponse(evaluation_id=ev.id, finding=finding.strip(), recommendation=recommendation,
                           created_by=scope.username)
    db.add(r)
    db.flush()
    audit.record(db, scope.username, "evaluation.finding", "evaluation", ev.id,
                 after={"finding_id": r.id, "finding": r.finding[:200]}, org_unit_code=ev.org_unit_code)
    return r


def respond(db: Session, scope: Scope, response_id: int, *, response: str, response_text: str,
            owner: str | None = None, due_date: date | None = None) -> ManagementResponse:
    r = _get(db, ManagementResponse, response_id, "Finding")
    ev, _ = entities.load(db, scope, "evaluation", r.evaluation_id)
    if not scope.can(ev.org_unit_code, "approver") and not scope.has_function("strategy_manager"):
        raise Forbidden("A management response needs the approver role on the evaluated unit or the strategy "
                        "manager duty.")
    if scope.read_only:
        raise Forbidden("Your account is read-only.")
    if r.response is not None:
        raise Conflict("This finding already has a management response.")
    if response not in ("accepted", "partially_accepted", "rejected"):
        raise Invalid("Response must be accepted, partially_accepted or rejected.")
    if not (response_text or "").strip():
        raise Invalid("Explain the management response.")
    r.response, r.response_text, r.responded_by, r.responded_at = response, response_text.strip(), scope.username, datetime.utcnow()
    if response != "rejected":
        if not owner:
            raise Invalid("An accepted recommendation needs an action owner.")
        a = platform_actions.create(db, scope, title=f"Evaluation follow-up: {(r.recommendation or r.finding)[:150]}",
                                    owner=owner, org_unit_code=ev.org_unit_code, due_date=due_date,
                                    description=f"{r.finding}\n\nManagement response: {r.response_text}",
                                    source_type="management_response", source_id=r.id, check_role=False)
        r.action_id, r.owner, r.due_date = a.id, a.owner, due_date
    audit.record(db, scope.username, "evaluation.response", "evaluation", ev.id,
                 after={"finding_id": r.id, "response": response, "action_id": r.action_id}, reason=response_text,
                 org_unit_code=ev.org_unit_code)
    return r


# ── my work and reminders ───────────────────────────────────────────────────

def my_work(db: Session, scope: Scope) -> dict:
    queues = {name: assignment_query(db, scope, queue=name) for name in ("submit", "verify", "approve")}
    return {"updates_to_submit": [assignment_dict(db, a, scope) for a in queues["submit"]],
            "updates_to_verify": [assignment_dict(db, a, scope) for a in queues["verify"]],
            "updates_to_approve": [assignment_dict(db, a, scope) for a in queues["approve"]]}


def _update_reminders(db: Session, today: date) -> int:
    sent = 0
    for c in db.query(ReportingCycle).filter_by(status="open"):
        if not c.due_on:
            continue
        for a in db.query(CycleAssignment).filter(CycleAssignment.cycle_id == c.id,
                                                  CycleAssignment.status.in_(("not_submitted", "returned"))):
            if c.due_on < today:
                sent += notify(db, a.contributor, "update_overdue", f"Overdue progress update: {c.name}",
                               body=f"Was due {c.due_on.isoformat()}.", entity_type="cycle_assignment",
                               entity_id=a.id, dedupe_key=f"assignment:{a.id}:overdue:{today.isoformat()}")
            elif c.due_on <= today + timedelta(days=5):
                sent += notify(db, a.contributor, "update_due_soon", f"Progress update due {c.due_on.isoformat()}",
                               body=c.name, entity_type="cycle_assignment", entity_id=a.id,
                               dedupe_key=f"assignment:{a.id}:due:{c.due_on.isoformat()}")
    return sent


REMINDER_PRODUCERS.append(_update_reminders)


# ── plan read model ─────────────────────────────────────────────────────────

def plan_detail(db: Session, scope: Scope, plan: Plan) -> dict:
    levels = {lv.node_type: {"label": lv.label, "plural": lv.plural, "enabled": lv.enabled}
              for lv in db.query(PlanLevel).filter_by(plan_id=plan.id)}
    nodes = db.query(PlanNode).filter_by(plan_id=plan.id).order_by(PlanNode.sort_order, PlanNode.code).all()
    inds = db.query(Indicator).filter_by(plan_id=plan.id).order_by(Indicator.code).all()
    visible_inds = [i for i in inds if indicator_visible(scope, i)]
    by_id = {n.id: n for n in nodes}
    visible = {n.id for n in nodes if scope.can_see(n.org_unit_code)}
    visible |= {i.node_id for i in visible_inds if i.node_id}
    context = set()
    for nid in list(visible):
        walk = by_id.get(nid)
        while walk is not None and walk.parent_id:
            if walk.parent_id not in visible:
                context.add(walk.parent_id)
            walk = by_id.get(walk.parent_id)
    from app.platform.models import EntityLink
    links = db.query(EntityLink).filter(EntityLink.from_type == "plan_node", EntityLink.to_type == "plan_node",
                                        EntityLink.relation == "contributes_to").all()
    contributes = [{"id": l.id, "from": int(l.from_id), "to": int(l.to_id)} for l in links
                   if int(l.from_id) in visible and int(l.to_id) in visible | context]

    def node_out(n: PlanNode) -> dict:
        if n.id in context and n.id not in visible:
            return {"id": n.id, "parent_id": n.parent_id, "node_type": n.node_type, "code": n.code, "title": n.title,
                    "context_only": True, "retired": n.retired}
        return {"id": n.id, "parent_id": n.parent_id, "node_type": n.node_type, "code": n.code, "title": n.title,
                "description": n.description, "owner": n.owner, "org_unit_code": n.org_unit_code, "weight": n.weight,
                "sort_order": n.sort_order, "start_date": n.start_date.isoformat() if n.start_date else None,
                "end_date": n.end_date.isoformat() if n.end_date else None, "status": n.status, "budget": n.budget,
                "retired": n.retired, "context_only": False}

    return {**plan_dict(plan, scope), "levels": levels,
            "nodes": [node_out(n) for n in nodes if n.id in visible or n.id in context],
            "indicators": [indicator_dict(i) for i in visible_inds], "contributes": contributes}


def plan_dict(p: Plan, scope: Scope | None = None) -> dict:
    d = {"id": p.id, "code": p.code, "title": p.title, "description": p.description, "start_fy": p.start_fy,
         "end_fy": p.end_fy, "status": p.status, "created_by": p.created_by,
         "approved_by": p.approved_by, "approved_at": p.approved_at.isoformat() if p.approved_at else None}
    if scope is not None:
        d["can_manage"] = scope.has_function("strategy_manager") and not scope.read_only
        d["allowed"] = PLAN_FLOW.allowed(p.status) if d["can_manage"] else []
    return d


def indicator_dict(i: Indicator) -> dict:
    return {"id": i.id, "plan_id": i.plan_id, "node_id": i.node_id, "code": i.code, "name": i.name,
            "definition": i.definition, "metric_code": i.metric_code, "polarity": i.polarity, "unit": i.unit,
            "aggregation": i.aggregation, "formula_text": i.formula_text, "source": i.source, "owner": i.owner,
            "org_unit_code": i.org_unit_code, "reporting_units": indicator_units(i), "collection": i.collection,
            "baseline_value": i.baseline_value, "baseline_date": i.baseline_date.isoformat() if i.baseline_date else None,
            "target_basis": i.target_basis, "frequency": i.frequency, "evidence_required": i.evidence_required,
            "dq_notes": i.dq_notes, "valid_min": i.valid_min, "valid_max": i.valid_max, "weight": i.weight,
            "version": i.version, "status": i.status}


def evaluation_dict(db: Session, ev: Evaluation, scope: Scope) -> dict:
    responses = db.query(ManagementResponse).filter_by(evaluation_id=ev.id).order_by(ManagementResponse.id).all()
    return {"id": ev.id, "plan_id": ev.plan_id, "title": ev.title, "kind": ev.kind, "scope": ev.scope,
            "method": ev.method, "criteria": ev.criteria or [], "lead": ev.lead, "org_unit_code": ev.org_unit_code,
            "start_date": ev.start_date.isoformat() if ev.start_date else None,
            "end_date": ev.end_date.isoformat() if ev.end_date else None, "status": ev.status,
            "findings_summary": ev.findings_summary, "limitations": ev.limitations, "created_by": ev.created_by,
            "can_edit": _may_edit_eval(scope, ev) and ev.status != "completed",
            "can_respond": not scope.read_only and (scope.can(ev.org_unit_code, "approver")
                                                    or scope.has_function("strategy_manager")),
            "allowed": EVALUATION_FLOW.allowed(ev.status) if _may_edit_eval(scope, ev) else [],
            "responses": [{"id": r.id, "finding": r.finding, "recommendation": r.recommendation,
                           "response": r.response, "response_text": r.response_text, "owner": r.owner,
                           "due_date": r.due_date.isoformat() if r.due_date else None, "action_id": r.action_id,
                           "responded_by": r.responded_by} for r in responses]}


def visible_evaluations(db: Session, scope: Scope, plan_id: int | None = None):
    q = scope.filter(db.query(Evaluation), Evaluation.org_unit_code)
    if plan_id:
        q = q.filter(Evaluation.plan_id == plan_id)
    return q.order_by(Evaluation.id.desc()).all()


def user_scope(db: Session, username: str) -> Scope | None:
    u = db.query(User).filter_by(username=username).first()
    return resolve_scope(db, u) if u else None
