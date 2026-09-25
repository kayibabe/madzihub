"""
Scorecard rules: schemes, weights, snapshots.

- Schemes are versioned. Only a draft can be edited; an approved scheme is changed by
  creating a new version. Approving (signing off) needs the strategy manager duty and a
  different person from the author, and valid bands. The shipped default is created as a
  *draft* with proposed bands so that it is reviewed before any score is approved.
- Weights are edited per level; each level is either unweighted (equal shares, shown as
  such) or weighted to exactly 100.
- A snapshot freezes the inputs (value and target ids, weights, scheme, engine version,
  data-quality flags) and the result. Recalculating makes a new snapshot; approving one
  supersedes the previous approved snapshot for the same plan, period and unit. Overrides
  change a rating with a reason on a draft only, and are re-evaluated from the frozen inputs.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.integration.models import Metric, MetricTarget, MetricValue
from app.integration.position import published_series
from app.modules.scorecard import engine
from app.modules.scorecard.models import ScoreSnapshot, ScoringBand, ScoringScheme
from app.modules.strategy.models import CycleAssignment, DqaAssessment, Indicator, Plan, PlanNode, ProgressUpdate, \
    ReportingCycle
from app.modules.strategy.service import indicator_units
from app.platform import audit, entities, periods
from app.platform.errors import Conflict, Forbidden, Invalid, NotFound
from app.platform.models import Period
from app.platform.scope import Scope, check_unit
from app.platform.workflow import Transition, Workflow

DEFAULT_CODE = "madzihub-default"
# Proposed defaults (docs/PERFORMANCE_GOVERNANCE.md §3). They are a starting point for the
# organisation's sign-off, not a regulator's or government's method.
DEFAULT_BANDS = [
    (5, "Exceeded", 110.0, None),
    (4, "Achieved", 100.0, 110.0),
    (3, "Nearly achieved", 90.0, 100.0),
    (2, "Below target", 70.0, 90.0),
    (1, "Well below target", 0.0, 70.0),
]
FREQ_MONTHS = {"month": 1, "quarter": 3, "year": 12}
SCHEME_FIELDS = ("name", "description", "effective_from", "effective_to", "rating_order", "cap_pct",
                 "zero_target_rule", "lower_method", "missing_policy", "coverage_gate_pct")

SCHEME_FLOW = Workflow("scoring_scheme", ("draft", "approved", "retired"), [
    Transition("approve", ("draft",), "approved"),
    Transition("retire", ("approved",), "retired", reason_required=True),
])
SNAPSHOT_FLOW = Workflow("score_snapshot", ("draft", "approved", "superseded"), [
    Transition("approve", ("draft",), "approved"),
    Transition("supersede", ("approved",), "superseded"),
])

entities.register(entities.EntityType(
    key="score_snapshot", label="Score snapshot", model=ScoreSnapshot, unit_of=lambda s: s.org_unit_code,
    title_of=lambda s: f"Scorecard #{s.id}", page="scorecard",
    versions_of=lambda db, s: {1}))


# ── schemes ─────────────────────────────────────────────────────────────────

def to_engine(s: ScoringScheme) -> engine.Scheme:
    return engine.Scheme(cap_pct=s.cap_pct, zero_target_rule=s.zero_target_rule, lower_method=s.lower_method,
                         missing_policy=s.missing_policy, coverage_gate_pct=s.coverage_gate_pct,
                         rating_order=s.rating_order,
                         bands=tuple(engine.Band(b.rating, b.label, b.min_achievement, b.max_achievement)
                                     for b in sorted(s.bands, key=lambda b: b.min_achievement)))


def ensure_default_scheme(db: Session, actor: str = "system") -> ScoringScheme | None:
    if db.query(ScoringScheme.id).first():
        return None
    s = ScoringScheme(code=DEFAULT_CODE, version=1, name="MadziHub default (proposed)", status="draft",
                      description=("Polarity-aware percentage achievement, capped at 130 % for rating (the uncapped "
                                   "value is kept), five bands where 5 is best, weighted roll-up with an 80 % "
                                   "coverage gate. Review the bands and approve before approving any score."),
                      rating_order="higher_is_better", cap_pct=130.0, zero_target_rule="unscored",
                      lower_method="linear_deviation", missing_policy="coverage_gate", coverage_gate_pct=80.0,
                      created_by=actor)
    s.bands = [ScoringBand(rating=r, label=lbl, min_achievement=lo, max_achievement=hi) for r, lbl, lo, hi in DEFAULT_BANDS]
    db.add(s)
    db.flush()
    audit.record(db, actor, "scoring_scheme.create", "scoring_scheme", s.id, after=scheme_dict(s))
    return s


def _validate_scheme(s: ScoringScheme) -> None:
    if s.rating_order not in engine.RATING_ORDERS:
        raise Invalid(f"Rating order must be one of {', '.join(engine.RATING_ORDERS)}.")
    if s.zero_target_rule not in engine.ZERO_TARGET_RULES:
        raise Invalid(f"Zero-target rule must be one of {', '.join(engine.ZERO_TARGET_RULES)}.")
    if s.lower_method not in engine.LOWER_METHODS:
        raise Invalid(f"Lower-is-better method must be one of {', '.join(engine.LOWER_METHODS)}.")
    if s.missing_policy not in engine.MISSING_POLICIES:
        raise Invalid(f"Missing-data policy must be one of {', '.join(engine.MISSING_POLICIES)}.")
    if not 100 <= (s.cap_pct or 0) <= 500:
        raise Invalid("The cap is a percentage between 100 and 500.")
    if not 0 < (s.coverage_gate_pct or 0) <= 100:
        raise Invalid("The coverage gate is a percentage above 0 and at most 100.")
    if s.effective_from and s.effective_to and s.effective_to < s.effective_from:
        raise Invalid("The scheme ends before it starts.")


def create_scheme(db: Session, scope: Scope, data: dict, from_scheme_id: int | None = None) -> ScoringScheme:
    scope.require_function("strategy_manager")
    if from_scheme_id:
        src = _scheme(db, from_scheme_id)
        latest = db.query(ScoringScheme).filter_by(code=src.code).order_by(ScoringScheme.version.desc()).first()
        s = ScoringScheme(code=src.code, version=latest.version + 1, status="draft", created_by=scope.username,
                          **{k: getattr(src, k) for k in SCHEME_FIELDS})
        s.name = data.get("name") or src.name
        s.bands = [ScoringBand(rating=b.rating, label=b.label, min_achievement=b.min_achievement,
                               max_achievement=b.max_achievement) for b in src.bands]
    else:
        code = (data.get("code") or "").strip()
        if not code or len(code) > 40:
            raise Invalid("A scheme needs a code of up to 40 characters.")
        if db.query(ScoringScheme.id).filter_by(code=code).first():
            raise Conflict(f"Scheme '{code}' exists; create a new version of it instead.")
        s = ScoringScheme(code=code, version=1, status="draft", created_by=scope.username,
                          **{k: data.get(k) for k in SCHEME_FIELDS if data.get(k) is not None})
        s.name = s.name or code
        s.bands = [ScoringBand(rating=r, label=lbl, min_achievement=lo, max_achievement=hi)
                   for r, lbl, lo, hi in DEFAULT_BANDS]
    for k, default in (("rating_order", "higher_is_better"), ("cap_pct", 130.0), ("zero_target_rule", "unscored"),
                       ("lower_method", "linear_deviation"), ("missing_policy", "coverage_gate"),
                       ("coverage_gate_pct", 80.0)):
        if getattr(s, k) is None:
            setattr(s, k, default)
    _validate_scheme(s)
    db.add(s)
    db.flush()
    audit.record(db, scope.username, "scoring_scheme.create", "scoring_scheme", s.id, after=scheme_dict(s))
    return s


def _scheme(db: Session, scheme_id: int) -> ScoringScheme:
    s = db.get(ScoringScheme, scheme_id)
    if s is None:
        raise NotFound("Scoring scheme not found.")
    return s


def update_scheme(db: Session, scope: Scope, scheme_id: int, data: dict) -> ScoringScheme:
    scope.require_function("strategy_manager")
    s = _scheme(db, scheme_id)
    if s.status != "draft":
        raise Conflict("Only a draft scheme can be edited; create a new version of an approved scheme.")
    before = scheme_dict(s)
    for k in SCHEME_FIELDS:
        if k in data and data[k] is not None:
            setattr(s, k, data[k])
    if "bands" in data and data["bands"] is not None:
        bands = [engine.Band(int(b["rating"]), str(b["label"]).strip(), float(b["min_achievement"]),
                             None if b.get("max_achievement") in (None, "") else float(b["max_achievement"]))
                 for b in data["bands"]]
        errors = engine.validate_bands(bands, s.cap_pct)
        if errors:
            raise Invalid(" ".join(errors))
        s.bands = [ScoringBand(rating=b.rating, label=b.label, min_achievement=b.min_achievement,
                               max_achievement=b.max_achievement) for b in bands]
    _validate_scheme(s)
    db.flush()
    b, a = audit.changed(before, scheme_dict(s))
    if a:
        audit.record(db, scope.username, "scoring_scheme.update", "scoring_scheme", s.id, before=b, after=a)
    return s


def transition_scheme(db: Session, scope: Scope, scheme_id: int, name: str, reason: str | None = None) -> ScoringScheme:
    scope.require_function("strategy_manager")
    s = _scheme(db, scheme_id)
    if name == "approve":
        if s.created_by == scope.username:
            raise Forbidden("A scheme must be signed off by someone other than its author.")
        errors = engine.validate_bands(to_engine(s).bands, s.cap_pct)
        if errors:
            raise Invalid(" ".join(errors))
        s.approved_by, s.approved_at = scope.username, datetime.utcnow()
        s.effective_from = s.effective_from or date.today()
    SCHEME_FLOW.apply(db, s, name, scope.username, reason=reason, step="sign_off" if name == "approve" else None,
                      decision="approved" if name == "approve" else None)
    return s


def scheme_dict(s: ScoringScheme) -> dict:
    return {"id": s.id, "code": s.code, "version": s.version, "name": s.name, "description": s.description,
            "status": s.status, "effective_from": s.effective_from.isoformat() if s.effective_from else None,
            "effective_to": s.effective_to.isoformat() if s.effective_to else None, "rating_order": s.rating_order,
            "cap_pct": s.cap_pct, "zero_target_rule": s.zero_target_rule, "lower_method": s.lower_method,
            "missing_policy": s.missing_policy, "coverage_gate_pct": s.coverage_gate_pct,
            "created_by": s.created_by, "approved_by": s.approved_by,
            "approved_at": s.approved_at.isoformat() if s.approved_at else None,
            "bands": [{"rating": b.rating, "label": b.label, "min_achievement": b.min_achievement,
                       "max_achievement": b.max_achievement} for b in sorted(s.bands, key=lambda b: -b.min_achievement)]}


# ── weights ─────────────────────────────────────────────────────────────────

def weight_groups(db: Session, plan: Plan) -> list[dict]:
    nodes = db.query(PlanNode).filter(PlanNode.plan_id == plan.id, PlanNode.retired.is_(False),
                                      PlanNode.node_type.in_(("pillar", "objective", "outcome", "output"))).all()
    inds = db.query(Indicator).filter_by(plan_id=plan.id, status="active").all()
    by_id = {n.id: n for n in nodes}
    groups: dict[int | None, list[dict]] = {}
    for n in nodes:
        groups.setdefault(n.parent_id if n.parent_id in by_id else None, []).append(
            {"type": "node", "id": n.id, "code": n.code, "label": n.title, "node_type": n.node_type, "weight": n.weight})
    for i in inds:
        if i.node_id in by_id:
            groups.setdefault(i.node_id, []).append(
                {"type": "indicator", "id": i.id, "code": i.code, "label": i.name, "weight": i.weight})
    out = []
    for parent, items in groups.items():
        mode, problems = engine.check_weights([x["weight"] for x in items])
        p = by_id.get(parent)
        out.append({"parent_id": parent, "parent": "Whole plan" if p is None else f"{p.code} {p.title}",
                    "items": sorted(items, key=lambda x: (x["type"], x["code"])),
                    "sum": sum(x["weight"] or 0 for x in items), "mode": mode, "problems": problems})
    return sorted(out, key=lambda g: (g["parent_id"] is not None, g["parent"]))


def set_weights(db: Session, scope: Scope, plan_id: int, items: list[dict], reason: str | None = None) -> list[dict]:
    scope.require_function("strategy_manager")
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise NotFound("Plan not found.")
    changes = []
    for it in items:
        model = PlanNode if it.get("type") == "node" else Indicator if it.get("type") == "indicator" else None
        obj = db.get(model, int(it["id"])) if model else None
        if obj is None or obj.plan_id != plan.id:
            raise Invalid("Every weighted item must belong to this plan.")
        w = it.get("weight")
        if w is not None and not 0 <= float(w) <= 100:
            raise Invalid("Weights are percentages between 0 and 100.")
        before = obj.weight
        obj.weight = None if w is None else float(w)
        if before != obj.weight:
            changes.append({"type": it["type"], "id": obj.id, "code": obj.code, "before": before, "after": obj.weight})
    db.flush()
    bad = [g for g in weight_groups(db, plan) if g["mode"] == "invalid"]
    if bad:
        raise Invalid("Weights must add up to 100 at each level (or be left blank for equal shares): " +
                      "; ".join(f"{g['parent']}: {' '.join(g['problems'])}" for g in bad))
    if changes:
        audit.record(db, scope.username, "plan.weights", "plan", plan.id,
                     before={c["code"]: c["before"] for c in changes}, after={c["code"]: c["after"] for c in changes},
                     reason=reason)
    return weight_groups(db, plan)


# ── inputs, evaluation, snapshots ───────────────────────────────────────────

def _dq_for(db: Session, plan: Plan, period: Period, ind: Indicator, unit: str) -> tuple[dict | None, str | None]:
    a = (db.query(CycleAssignment).join(ReportingCycle, ReportingCycle.id == CycleAssignment.cycle_id)
         .filter(ReportingCycle.plan_id == plan.id, ReportingCycle.period_id == period.id,
                 CycleAssignment.indicator_id == ind.id, CycleAssignment.org_unit_code == unit).first())
    if a is None:
        return None, None
    if not a.current_update_id:
        return {"fails": 0, "warns": 0, "revision": None}, a.status
    rows = db.query(DqaAssessment.result).filter_by(update_id=a.current_update_id).all()
    upd = db.get(ProgressUpdate, a.current_update_id)
    return ({"fails": sum(1 for (r,) in rows if r == "fail"), "warns": sum(1 for (r,) in rows if r == "warn"),
             "revision": upd.revision if upd else None}, a.status)


def gather(db: Session, plan: Plan, period: Period, unit: str) -> dict:
    """Read everything the score depends on, with the ids of the rows used."""
    nodes = (db.query(PlanNode).filter(PlanNode.plan_id == plan.id, PlanNode.retired.is_(False),
                                       PlanNode.node_type.in_(("pillar", "objective", "outcome", "output")))
             .order_by(PlanNode.sort_order, PlanNode.code).all())
    keys = {n.id: f"n{n.id}" for n in nodes}
    inds = db.query(Indicator).filter_by(plan_id=plan.id, status="active").order_by(Indicator.code).all()
    out_inds = []
    for i in inds:
        if i.node_id not in keys:
            continue
        rec = {"key": f"i{i.id}", "id": i.id, "node": keys[i.node_id], "code": i.code, "name": i.name, "unit": i.unit,
               "polarity": i.polarity, "weight": i.weight, "actual": None, "target": None, "lower": None,
               "upper": None, "value_refs": [], "target_id": None, "source": None, "dq": None,
               "assignment_status": None, "note": None, "version": i.version}
        if unit not in indicator_units(i) and unit != i.org_unit_code:
            rec.update(state="not_reported", note="Not reported by this unit.")
        elif FREQ_MONTHS[i.frequency] > FREQ_MONTHS[period.period_type]:
            rec.update(state="not_due", note=f"Reported {i.frequency}ly; not due in a {period.period_type}.")
        else:
            key = dict(metric_code=i.metric_code, org_unit_code=unit, period_type=period.period_type,
                       period_start=period.start_date)
            metric = db.query(Metric).filter_by(code=i.metric_code).first()
            series = published_series(db, metric, unit, period.period_type, period.start_date, period.start_date)[0] \
                if metric else []
            rows = db.query(MetricValue).filter_by(**key).all()
            rec["value_refs"] = sorted(r.id for r in rows)
            if series:
                rec.update(state="measured", actual=series[0]["value"], source=series[0].get("source"))
            elif rows and all(r.status == "na" for r in rows):
                rec.update(state="not_applicable", note="Reported as not applicable for the period.")
            else:
                rec.update(state="no_value", note="No approved value for the period.")
            t = db.query(MetricTarget).filter_by(metric_code=i.metric_code, org_unit_code=unit,
                                                 period_type=period.period_type, period_start=period.start_date).first()
            if t is not None:
                rec.update(target=t.value, lower=t.lower, upper=t.upper, target_id=t.id)
            rec["dq"], rec["assignment_status"] = _dq_for(db, plan, period, i, unit)
        out_inds.append(rec)
    return {"plan": {"id": plan.id, "code": plan.code, "title": plan.title},
            "period": {"id": period.id, "label": period.label, "type": period.period_type,
                       "start": period.start_date.isoformat()},
            "unit": unit,
            "nodes": [{"key": keys[n.id], "id": n.id, "parent": keys.get(n.parent_id), "code": n.code,
                       "title": n.title, "node_type": n.node_type, "weight": n.weight} for n in nodes],
            "indicators": out_inds}


def _completeness(inputs: dict) -> float | None:
    counted = [i for i in inputs["indicators"] if i["state"] not in engine.EXCLUDED_STATES]
    if not counted:
        return None
    return round(sum(1 for i in counted if i["state"] == "measured") / len(counted) * 100, 2)


def evaluate(inputs: dict, scheme: ScoringScheme, overrides: dict | None = None) -> dict:
    tree = engine.evaluate_tree(inputs, to_engine(scheme), overrides)
    return {"tree": tree, "completeness_pct": _completeness(inputs), "scheme": scheme_dict(scheme),
            "engine_version": engine.ENGINE_VERSION}


def _context(db: Session, scope: Scope, plan_id: int, period_id: int, unit: str) -> tuple[Plan, Period, str]:
    plan, _ = entities.load(db, scope, "plan", plan_id)
    period = periods.get(db, period_id)
    unit = check_unit(db, unit)
    scope.require_see(unit, "Organisational unit")
    return plan, period, unit


def pick_scheme(db: Session, scheme_id: int | None) -> ScoringScheme:
    if scheme_id:
        return _scheme(db, scheme_id)
    ensure_default_scheme(db)
    s = (db.query(ScoringScheme).filter_by(status="approved").order_by(ScoringScheme.approved_at.desc()).first()
         or db.query(ScoringScheme).filter_by(status="draft").order_by(ScoringScheme.id.desc()).first())
    if s is None:
        raise NotFound("No scoring scheme is available.")
    return s


def preview(db: Session, scope: Scope, plan_id: int, period_id: int, unit: str, scheme_id: int | None = None) -> dict:
    plan, period, unit = _context(db, scope, plan_id, period_id, unit)
    scheme = pick_scheme(db, scheme_id)
    inputs = gather(db, plan, period, unit)
    return {"live": True, "inputs": inputs, **evaluate(inputs, scheme), "provisional": scheme.status != "approved"}


def create_snapshot(db: Session, scope: Scope, plan_id: int, period_id: int, unit: str,
                    scheme_id: int | None = None, note: str | None = None) -> ScoreSnapshot:
    plan, period, unit = _context(db, scope, plan_id, period_id, unit)
    if not (scope.has_function("strategy_manager") or scope.can(unit, "reviewer")) or scope.read_only:
        raise Forbidden("Taking a score snapshot needs the reviewer role on the unit or the strategy manager duty.")
    periods.assert_open(db, period)
    scheme = pick_scheme(db, scheme_id)
    if scheme.status == "retired":
        raise Conflict("That scheme is retired.")
    inputs = gather(db, plan, period, unit)
    result = evaluate(inputs, scheme)
    digest = engine.inputs_hash({"inputs": inputs, "scheme": result["scheme"], "engine": engine.ENGINE_VERSION})
    root = result["tree"]["root"]
    snap = ScoreSnapshot(plan_id=plan.id, period_id=period.id, org_unit_code=unit, scheme_id=scheme.id,
                         scheme_version=scheme.version, engine_version=engine.ENGINE_VERSION, inputs_hash=digest,
                         status="draft", provisional=int(scheme.status != "approved"),
                         achievement=root["achievement"], rating=root["rating"], rating_label=root["rating_label"],
                         completeness_pct=result["completeness_pct"], covered_weight=root["covered_weight"],
                         result={"inputs": inputs, **result}, overrides={}, note=note, created_by=scope.username)
    db.add(snap)
    db.flush()
    audit.record(db, scope.username, "score_snapshot.create", "score_snapshot", snap.id, org_unit_code=unit,
                 after={"plan": plan.code, "period": period.label, "scheme": f"{scheme.code} v{scheme.version}",
                        "inputs_hash": digest, "rating": snap.rating, "status": root["status"]})
    return snap


def _snapshot(db: Session, scope: Scope, snap_id: int) -> ScoreSnapshot:
    s, _ = entities.load(db, scope, "score_snapshot", snap_id)
    return s


def set_override(db: Session, scope: Scope, snap_id: int, key: str, rating: int | None, reason: str) -> ScoreSnapshot:
    s = _snapshot(db, scope, snap_id)
    if s.status != "draft":
        raise Conflict("Approved snapshots are read-only; take a new snapshot to change a score.")
    if not (scope.has_function("strategy_manager") or scope.can(s.org_unit_code, "approver")) or scope.read_only:
        raise Forbidden("Overriding a rating needs the approver role on the unit or the strategy manager duty.")
    if not (reason or "").strip():
        raise Invalid("An override needs a reason.")
    scheme = _scheme(db, s.scheme_id)
    inputs = s.result["inputs"]
    tree = s.result["tree"]
    if key != "plan" and key not in tree["items"]:
        raise Invalid("Unknown scorecard item.")
    overrides = dict(s.overrides or {})
    before = overrides.get(key)
    if rating is None:
        overrides.pop(key, None)
    else:
        if rating not in {b.rating for b in scheme.bands}:
            raise Invalid("Choose one of the scheme's ratings.")
        overrides[key] = {"rating": int(rating), "reason": reason.strip(), "by": scope.username,
                          "at": datetime.utcnow().isoformat()}
    result = evaluate(inputs, scheme, overrides)
    root = result["tree"]["root"]
    s.overrides = overrides
    s.result = {"inputs": inputs, **result}
    s.rating, s.rating_label, s.achievement = root["rating"], root["rating_label"], root["achievement"]
    audit.record(db, scope.username, "score_snapshot.override", "score_snapshot", s.id, org_unit_code=s.org_unit_code,
                 before={"item": key, "override": before}, after={"item": key, "override": overrides.get(key)},
                 reason=reason)
    return s


def approve_snapshot(db: Session, scope: Scope, snap_id: int, note: str | None = None) -> ScoreSnapshot:
    s = _snapshot(db, scope, snap_id)
    if not scope.can(s.org_unit_code, "approver"):
        raise Forbidden("Approving a score needs the approver role on the unit.")
    if s.created_by == scope.username:
        raise Forbidden("A score snapshot must be approved by someone other than the person who took it.")
    scheme = _scheme(db, s.scheme_id)
    if scheme.status != "approved" or s.provisional:
        raise Conflict("This snapshot uses a scheme that has not been signed off; approve the scheme and take a "
                       "new snapshot.")
    periods.assert_open(db, s.period_id)
    SNAPSHOT_FLOW.check(s, "approve")
    previous = (db.query(ScoreSnapshot).filter_by(plan_id=s.plan_id, period_id=s.period_id,
                                                  org_unit_code=s.org_unit_code, status="approved").all())
    for p in previous:
        SNAPSHOT_FLOW.apply(db, p, "supersede", scope.username, org_unit_code=p.org_unit_code,
                            extra_after={"superseded_by": s.id})
        s.supersedes_id = p.id
    s.approved_by, s.approved_at = scope.username, datetime.utcnow()
    SNAPSHOT_FLOW.apply(db, s, "approve", scope.username, reason=note, org_unit_code=s.org_unit_code,
                        step="approve", decision="approved", extra_after={"inputs_hash": s.inputs_hash})
    return s


def snapshot_dict(db: Session, s: ScoreSnapshot, scope: Scope, full: bool = False) -> dict:
    period = db.get(Period, s.period_id)
    plan = db.get(Plan, s.plan_id)
    d = {"id": s.id, "plan_id": s.plan_id, "plan": plan.code if plan else None, "period_id": s.period_id,
         "period": period.label if period else None, "org_unit_code": s.org_unit_code, "scheme_id": s.scheme_id,
         "scheme_version": s.scheme_version, "engine_version": s.engine_version, "inputs_hash": s.inputs_hash,
         "status": s.status, "provisional": bool(s.provisional), "achievement": s.achievement, "rating": s.rating,
         "rating_label": s.rating_label, "completeness_pct": s.completeness_pct, "covered_weight": s.covered_weight,
         "overrides": s.overrides or {}, "note": s.note, "created_by": s.created_by,
         "created_at": s.created_at.isoformat() if s.created_at else None, "approved_by": s.approved_by,
         "approved_at": s.approved_at.isoformat() if s.approved_at else None, "supersedes_id": s.supersedes_id,
         "can_approve": s.status == "draft" and not s.provisional and scope.can(s.org_unit_code, "approver")
                        and s.created_by != scope.username,
         "can_override": s.status == "draft" and not scope.read_only and (
             scope.has_function("strategy_manager") or scope.can(s.org_unit_code, "approver"))}
    if full:
        d.update({"inputs": s.result.get("inputs"), "tree": s.result.get("tree"), "scheme": s.result.get("scheme")})
    return d


def list_snapshots(db: Session, scope: Scope, plan_id: int | None = None, period_id: int | None = None,
                   unit: str | None = None) -> list[ScoreSnapshot]:
    q = scope.filter(db.query(ScoreSnapshot), ScoreSnapshot.org_unit_code)
    if plan_id:
        q = q.filter(ScoreSnapshot.plan_id == plan_id)
    if period_id:
        q = q.filter(ScoreSnapshot.period_id == period_id)
    if unit:
        q = q.filter(ScoreSnapshot.org_unit_code == unit)
    return q.order_by(ScoreSnapshot.id.desc()).all()


def latest_approved(db: Session, plan_id: int, period_id: int, unit: str) -> ScoreSnapshot | None:
    return (db.query(ScoreSnapshot).filter_by(plan_id=plan_id, period_id=period_id, org_unit_code=unit,
                                              status="approved").order_by(ScoreSnapshot.id.desc()).first())
