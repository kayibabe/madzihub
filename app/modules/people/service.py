"""
Performance contracts and staff appraisal.

Gates (both must hold, or every endpoint answers 409 with the reason)
- the module is not switched off in tenant.yaml (``modules.performance_contracts`` /
  ``modules.staff_appraisal``), and
- an HR officer has recorded the organisation's approved policy for it (policy reference).

Privacy
- Only the people named on a record and HR officers (explicit duty; administrators do not hold
  it implicitly) can see a contract or appraisal. Other records, lists and the general audit
  trail never show them.

Contracts:  draft ─sign(holder)→ holder_signed ─countersign(supervisor)→ signed
            ─evaluate(supervisor)→ evaluated ─accept(holder)→ closed
                                             └appeal(holder, reason)→ under_appeal ─decide(HR, reason)→ closed
            Scored on the approved scoring scheme from published values and targets (frozen at evaluation).
Appraisals: draft ─agree(employee)→ objectives_agreed ─self_assess(employee)→ self_assessed
            ─appraise(appraiser)→ appraised ─acknowledge(employee)→ closed
                                           └appeal(employee, reason)→ appealed ─decide(HR ≠ appraiser)→ closed
            closed ─correct(HR, reason)→ closed   (the correction is kept in the record's history)
Ratings on appraisals use 1–5 where 5 is the best; the scale is stated on every record.
No country-specific contract method (e.g. Kenya's) is implemented: an adapter is added only when
it can reproduce the exact current rules.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.integration.models import Metric, MetricTarget
from app.integration.position import published_series
from app.modules.people.models import (
    ContractItem, HrPolicyConfirmation, PerformanceContract, StaffAppraisal,
)
from app.modules.scorecard import engine as scoring
from app.modules.scorecard.models import ScoringScheme
from app.modules.scorecard.service import to_engine
from app.modules.strategy.models import Indicator
from app.platform import audit, entities, periods
from app.platform.errors import Conflict, Forbidden, Invalid, NotFound
from app.platform.notifications import notify
from app.platform.scope import Scope, check_unit
from app.platform.workflow import Transition, Workflow

MODULES = ("performance_contracts", "staff_appraisal")
RATING_SCALE = "1 to 5, where 5 is the best"

CONTRACT_FLOW = Workflow("performance_contract", ("draft", "holder_signed", "signed", "evaluated", "under_appeal", "closed"), [
    Transition("sign", ("draft",), "holder_signed"),
    Transition("countersign", ("holder_signed",), "signed"),
    Transition("evaluate", ("signed",), "evaluated"),
    Transition("accept", ("evaluated",), "closed"),
    Transition("appeal", ("evaluated",), "under_appeal", reason_required=True),
    Transition("decide", ("under_appeal",), "closed", reason_required=True),
])
APPRAISAL_FLOW = Workflow("staff_appraisal", ("draft", "objectives_agreed", "self_assessed", "appraised", "appealed", "closed"), [
    Transition("agree", ("draft",), "objectives_agreed"),
    Transition("self_assess", ("objectives_agreed",), "self_assessed"),
    Transition("appraise", ("self_assessed",), "appraised"),
    Transition("acknowledge", ("appraised",), "closed"),
    Transition("appeal", ("appraised",), "appealed", reason_required=True),
    Transition("decide", ("appealed",), "closed", reason_required=True),
    Transition("correct", ("closed",), "closed", reason_required=True),
])


def _hr(scope: Scope) -> bool:
    return "hr_officer" in scope.functions and not scope.read_only


def contract_visible(scope: Scope, c: PerformanceContract) -> bool:
    return scope.username in (c.holder, c.supervisor) or "hr_officer" in scope.functions


def appraisal_visible(scope: Scope, a: StaffAppraisal) -> bool:
    return scope.username in (a.employee, a.appraiser) or "hr_officer" in scope.functions


entities.register(entities.EntityType(
    key="performance_contract", label="Performance contract", model=PerformanceContract,
    unit_of=lambda c: c.org_unit_code, title_of=lambda c: f"Contract #{c.id} ({c.holder})",
    can_view=contract_visible, page="people"))
entities.register(entities.EntityType(
    key="staff_appraisal", label="Staff appraisal", model=StaffAppraisal, unit_of=lambda a: None,
    title_of=lambda a: f"Appraisal #{a.id}", can_view=appraisal_visible, page="people"))

from app.platform.router import PRIVATE_ENTITY_TYPES  # noqa: E402

PRIVATE_ENTITY_TYPES.update({"performance_contract", "staff_appraisal", "hr_policy"})


# ── gate ────────────────────────────────────────────────────────────────────

def gate_status(db: Session) -> dict:
    from app.core.tenant import tenant
    out = {}
    for m in MODULES:
        conf = db.query(HrPolicyConfirmation).filter_by(module=m, active=True).order_by(HrPolicyConfirmation.id.desc()).first()
        switched_off = tenant.modules.get(m) is False
        out[m] = {"enabled": not switched_off and conf is not None, "switched_off_in_config": switched_off,
                  "policy_ref": conf.policy_ref if conf else None,
                  "confirmed_by": conf.confirmed_by if conf else None,
                  "confirmed_at": conf.confirmed_at.isoformat() if conf and conf.confirmed_at else None}
    return out


def require_gate(db: Session, module: str) -> None:
    g = gate_status(db)[module]
    if g["switched_off_in_config"]:
        raise Conflict(f"{module.replace('_', ' ').capitalize()} is switched off in this installation's configuration.")
    if not g["enabled"]:
        raise Conflict("This module is off until an HR officer records the organisation's approved HR policy for it.")


def confirm_policy(db: Session, scope: Scope, module: str, policy_ref: str, summary: str | None) -> HrPolicyConfirmation:
    if not _hr(scope):
        raise Forbidden("Only HR officers (explicit duty) confirm HR policy.")
    if module not in MODULES:
        raise Invalid(f"Module must be one of {', '.join(MODULES)}.")
    if not (policy_ref or "").strip():
        raise Invalid("Give the approved policy reference (document, clause, approval).")
    for old in db.query(HrPolicyConfirmation).filter_by(module=module, active=True):
        old.active = False
    c = HrPolicyConfirmation(module=module, policy_ref=policy_ref.strip()[:200], summary=summary, active=True,
                             confirmed_by=scope.username)
    db.add(c)
    db.flush()
    audit.record(db, scope.username, "hr_policy.confirm", "hr_policy", c.id, after={"module": module,
                                                                                    "policy_ref": c.policy_ref})
    return c


def _user(db: Session, username: str) -> str:
    from app.database import User
    if not db.query(User.id).filter(User.username == username, User.is_active.is_(True)).first():
        raise Invalid(f"Unknown or inactive user '{username}'.")
    return username


# ── contracts ───────────────────────────────────────────────────────────────

def create_contract(db: Session, scope: Scope, *, plan_id: int, period_id: int, org_unit_code: str, holder: str,
                    supervisor: str, items: list[dict]) -> PerformanceContract:
    require_gate(db, "performance_contracts")
    if not _hr(scope):
        raise Forbidden("HR officers draw up performance contracts.")
    unit = check_unit(db, org_unit_code)
    holder, supervisor = _user(db, holder), _user(db, supervisor)
    if holder == supervisor:
        raise Invalid("The holder and the supervisor must be different people.")
    periods.get(db, period_id)
    total = sum(float(i.get("weight") or 0) for i in items)
    if not items or abs(total - 100) > 1e-6:
        raise Invalid(f"Contract weights must add up to 100 (they add up to {total:g}).")
    c = PerformanceContract(plan_id=plan_id, period_id=period_id, org_unit_code=unit, holder=holder,
                            supervisor=supervisor, status="draft", created_by=scope.username)
    db.add(c)
    db.flush()
    for it in items:
        ind = db.get(Indicator, int(it["indicator_id"]))
        if ind is None or ind.plan_id != plan_id:
            raise Invalid("Every contract item must be an indicator of the chosen plan.")
        db.add(ContractItem(contract_id=c.id, indicator_id=ind.id, weight=float(it["weight"])))
    audit.record(db, scope.username, "performance_contract.create", "performance_contract", c.id,
                 after={"holder": holder, "supervisor": supervisor, "unit": unit, "items": len(items)})
    notify(db, holder, "contract_to_sign", "A performance contract is ready for your signature",
           entity_type="performance_contract", entity_id=c.id)
    return c


def _evaluate(db: Session, c: PerformanceContract) -> dict:
    scheme = (db.query(ScoringScheme).filter_by(status="approved").order_by(ScoringScheme.approved_at.desc()).first())
    if scheme is None:
        raise Conflict("No approved scoring scheme: a strategy manager must sign one off before contracts are evaluated.")
    sch = to_engine(scheme)
    period = periods.get(db, c.period_id)
    rows, children = [], []
    for it in db.query(ContractItem).filter_by(contract_id=c.id):
        ind = db.get(Indicator, it.indicator_id)
        metric = db.query(Metric).filter_by(code=ind.metric_code).first()
        series = published_series(db, metric, c.org_unit_code, period.period_type, period.start_date, period.start_date)[0] if metric else []
        actual = series[0]["value"] if series else None
        t = db.query(MetricTarget).filter_by(metric_code=ind.metric_code, org_unit_code=c.org_unit_code,
                                             period_type=period.period_type, period_start=period.start_date).first()
        a = scoring.achievement(ind.polarity, actual, t.value if t else None, sch, t.lower if t else None, t.upper if t else None)
        band = scoring.rate(a.capped, sch)
        rows.append({"indicator": f"{ind.code} {ind.name}", "weight": it.weight, "actual": actual,
                     "target": t.value if t else None, "achievement": a.capped, "achievement_uncapped": a.uncapped,
                     "rating": band.rating if band else None, "rating_label": band.label if band else None,
                     "note": a.note})
        children.append(scoring.Child(ind.code, ind.name, it.weight, a.capped, float(band.rating) if band else None,
                                      "scored" if band else "missing", a.note))
    r = scoring.rollup(children, sch)
    label = scoring.band_for_rating(r.rating, sch)
    return {"scheme": f"{scheme.code} v{scheme.version}", "engine_version": scoring.ENGINE_VERSION, "items": rows,
            "rating": r.rating, "rating_label": label.label if label else None, "status": r.status,
            "method": r.method, "coverage_pct": r.coverage_pct}


def transition_contract(db: Session, scope: Scope, contract_id: int, name: str, reason: str | None = None,
                        adjusted_rating: float | None = None) -> PerformanceContract:
    require_gate(db, "performance_contracts")
    c, _ = entities.load(db, scope, "performance_contract", contract_id)
    CONTRACT_FLOW.check(c, name, reason)
    actor = scope.username
    if scope.read_only:
        raise Forbidden("Your account is read-only.")
    if name in ("sign", "accept", "appeal") and actor != c.holder:
        raise Forbidden("Only the contract holder can do that.")
    if name in ("countersign", "evaluate") and actor != c.supervisor:
        raise Forbidden("Only the supervisor can do that.")
    if name == "decide":
        if not _hr(scope) or actor in (c.supervisor, c.holder):
            raise Forbidden("An HR officer who is neither the holder nor the supervisor decides an appeal.")
        c.appeal_decision = reason
        if adjusted_rating is not None:
            before = c.final_rating
            c.final_rating = float(adjusted_rating)
            audit.record(db, actor, "performance_contract.correct", "performance_contract", c.id,
                         before={"final_rating": before}, after={"final_rating": c.final_rating}, reason=reason)
    if name == "evaluate":
        c.evaluation = _evaluate(db, c)
        c.final_rating, c.final_label = c.evaluation["rating"], c.evaluation["rating_label"]
    if name == "appeal":
        c.appeal_reason = reason
    CONTRACT_FLOW.apply(db, c, name, actor, reason=reason, step=name,
                        extra_after={"final_rating": c.final_rating} if name in ("evaluate", "decide") else None)
    return c


def contract_dict(db: Session, c: PerformanceContract, scope: Scope) -> dict:
    items = []
    for it in db.query(ContractItem).filter_by(contract_id=c.id):
        ind = db.get(Indicator, it.indicator_id)
        items.append({"indicator_id": ind.id, "indicator": f"{ind.code} {ind.name}", "weight": it.weight})
    period = periods.get(db, c.period_id)
    who = scope.username
    allowed = [t for t in CONTRACT_FLOW.allowed(c.status) if not scope.read_only and (
        (t in ("sign", "accept", "appeal") and who == c.holder) or (t in ("countersign", "evaluate") and who == c.supervisor)
        or (t == "decide" and _hr(scope) and who not in (c.holder, c.supervisor)))]
    return {"id": c.id, "plan_id": c.plan_id, "period": period.label, "org_unit_code": c.org_unit_code, "holder": c.holder,
            "supervisor": c.supervisor, "status": c.status, "items": items, "evaluation": c.evaluation,
            "final_rating": c.final_rating, "final_label": c.final_label, "appeal_reason": c.appeal_reason,
            "appeal_decision": c.appeal_decision, "allowed": allowed}


# ── appraisals ──────────────────────────────────────────────────────────────

def _check_ratings(obj: StaffAppraisal, ratings: dict) -> dict:
    n = len(obj.objectives)
    clean = {}
    for i in range(n):
        v = ratings.get(str(i), ratings.get(i))
        if v is None or not 1 <= float(v) <= 5:
            raise Invalid(f"Rate every objective on the scale {RATING_SCALE}.")
        clean[str(i)] = float(v)
    return clean


def create_appraisal(db: Session, scope: Scope, *, employee: str, appraiser: str, period_label: str,
                     objectives: list[dict]) -> StaffAppraisal:
    require_gate(db, "staff_appraisal")
    employee, appraiser = _user(db, employee), _user(db, appraiser)
    if not (_hr(scope) or (scope.username == appraiser and not scope.read_only)):
        raise Forbidden("An HR officer or the appraiser sets up an appraisal.")
    if employee == appraiser:
        raise Invalid("The employee cannot appraise themselves.")
    total = sum(float(o.get("weight") or 0) for o in objectives)
    if not objectives or abs(total - 100) > 1e-6 or any(not (o.get("title") or "").strip() for o in objectives):
        raise Invalid(f"Give each objective a title; weights must add up to 100 (they add up to {total:g}).")
    a = StaffAppraisal(employee=employee, appraiser=appraiser, period_label=period_label.strip()[:40], status="draft",
                       objectives=[{"title": o["title"].strip(), "weight": float(o["weight"]),
                                    "measure": (o.get("measure") or "").strip()} for o in objectives],
                       created_by=scope.username)
    db.add(a)
    db.flush()
    audit.record(db, scope.username, "staff_appraisal.create", "staff_appraisal", a.id,
                 after={"employee": employee, "appraiser": appraiser, "period": a.period_label})
    notify(db, employee, "appraisal_objectives", "Your appraisal objectives are ready to agree",
           entity_type="staff_appraisal", entity_id=a.id)
    return a


def transition_appraisal(db: Session, scope: Scope, appraisal_id: int, name: str, *, reason: str | None = None,
                         ratings: dict | None = None, comment: str | None = None,
                         overall: float | None = None) -> StaffAppraisal:
    require_gate(db, "staff_appraisal")
    a, _ = entities.load(db, scope, "staff_appraisal", appraisal_id)
    APPRAISAL_FLOW.check(a, name, reason)
    who = scope.username
    if scope.read_only:
        raise Forbidden("Your account is read-only.")
    if name in ("agree", "self_assess", "acknowledge", "appeal") and who != a.employee:
        raise Forbidden("Only the employee can do that.")
    if name == "appraise" and who != a.appraiser:
        raise Forbidden("Only the appraiser can appraise.")
    if name in ("decide", "correct") and (not _hr(scope) or who in (a.appraiser, a.employee)):
        raise Forbidden("An HR officer who is neither the employee nor the appraiser does that.")
    before = {"overall_rating": a.overall_rating}
    if name == "self_assess":
        a.self_assessment = {"ratings": _check_ratings(a, ratings or {}), "comment": comment}
    elif name == "appraise":
        r = _check_ratings(a, ratings or {})
        a.appraiser_assessment = {"ratings": r, "comment": comment}
        a.overall_rating = round(sum(r[str(i)] * o["weight"] for i, o in enumerate(a.objectives)) / 100, 2)
    elif name == "acknowledge":
        a.employee_comment = comment
    elif name == "appeal":
        a.appeal_reason = reason
    elif name in ("decide", "correct"):
        a.appeal_decision = reason if name == "decide" else a.appeal_decision
        if overall is not None:
            if not 1 <= float(overall) <= 5:
                raise Invalid(f"Ratings run {RATING_SCALE}.")
            a.overall_rating = float(overall)
    APPRAISAL_FLOW.apply(db, a, name, who, reason=reason or comment, step=name,
                         extra_before=before, extra_after={"overall_rating": a.overall_rating})
    target = a.appraiser if name in ("self_assess", "acknowledge", "appeal") else a.employee
    notify(db, target, f"appraisal_{name}", f"Appraisal #{a.id}: {name.replace('_', ' ')}",
           entity_type="staff_appraisal", entity_id=a.id)
    return a


def appraisal_dict(db: Session, a: StaffAppraisal, scope: Scope) -> dict:
    who = scope.username
    allowed = [t for t in APPRAISAL_FLOW.allowed(a.status) if not scope.read_only and (
        (t in ("agree", "self_assess", "acknowledge", "appeal") and who == a.employee) or (t == "appraise" and who == a.appraiser)
        or (t in ("decide", "correct") and _hr(scope) and who not in (a.employee, a.appraiser)))]
    from app.platform.models import AuditEvent
    history = [{"action": e.action, "actor": e.actor, "at": e.at.isoformat() if e.at else None,
                "before": e.before, "after": e.after, "reason": e.reason}
               for e in db.query(AuditEvent).filter_by(entity_type="staff_appraisal", entity_id=str(a.id)).order_by(AuditEvent.id)]
    return {"id": a.id, "employee": a.employee, "appraiser": a.appraiser, "period_label": a.period_label,
            "status": a.status, "objectives": a.objectives, "self_assessment": a.self_assessment,
            "appraiser_assessment": a.appraiser_assessment, "overall_rating": a.overall_rating,
            "employee_comment": a.employee_comment, "appeal_reason": a.appeal_reason,
            "appeal_decision": a.appeal_decision, "rating_scale": RATING_SCALE, "allowed": allowed, "history": history}


def visible_appraisals(db: Session, scope: Scope) -> list[StaffAppraisal]:
    q = db.query(StaffAppraisal)
    if "hr_officer" not in scope.functions:
        q = q.filter((StaffAppraisal.employee == scope.username) | (StaffAppraisal.appraiser == scope.username))
    return q.order_by(StaffAppraisal.id.desc()).limit(500).all()


def visible_contracts(db: Session, scope: Scope) -> list[PerformanceContract]:
    q = db.query(PerformanceContract)
    if "hr_officer" not in scope.functions:
        q = q.filter((PerformanceContract.holder == scope.username) | (PerformanceContract.supervisor == scope.username))
    return q.order_by(PerformanceContract.id.desc()).limit(500).all()


def get_contract(db: Session, scope: Scope, contract_id: int) -> PerformanceContract:
    c, _ = entities.load(db, scope, "performance_contract", contract_id)
    return c


def get_appraisal(db: Session, scope: Scope, appraisal_id: int) -> StaffAppraisal:
    a, _ = entities.load(db, scope, "staff_appraisal", appraisal_id)
    return a


__all__ = ["NotFound"]
