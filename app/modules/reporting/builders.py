"""
Freeze the data a report needs. Called once per "freeze"; the result is stored on the
instance and every output is rendered from it (never from live queries).

Scores come from the latest *approved* score snapshot. When none exists the report
carries a live calculation clearly marked as unapproved, and approval of a board pack or
scorecard report is refused until the score is approved.

Other modules add sections through SECTION_PROVIDERS: fn(db, scope, ctx) -> (key, data).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.integration.position import freshness
from app.modules.scorecard import service as scoring
from app.modules.scorecard.models import ScoreSnapshot
from app.modules.strategy import service as strategy
from app.modules.strategy.models import CycleAssignment, DqaAssessment, Indicator, ProgressUpdate, ReportingCycle
from app.platform.models import Action, Period
from app.platform.scope import Scope, _tree, subtree, unit_names

SECTION_PROVIDERS: list = []


def _flatten(tree: dict) -> list[dict]:
    rows: list[dict] = []
    items = tree["items"]

    def walk(key: str, depth: int) -> None:
        it = items.get(key)
        if not it:
            return
        rows.append({"key": key, "depth": depth, "type": it["type"], "code": it.get("code"),
                     "title": it.get("title") or it.get("name"), "weight": it.get("weight"),
                     "actual": it.get("actual"), "target": it.get("target"), "unit": it.get("unit"),
                     "achievement": it.get("achievement"), "achievement_uncapped": it.get("achievement_uncapped"),
                     "rating": it.get("rating"), "rating_label": it.get("rating_label"),
                     "status": it.get("status") or it.get("state"), "override": bool(it.get("override")),
                     "dq": it.get("dq")})
        for k in it.get("children", []) if it["type"] == "node" else []:
            walk(k, depth + 1)

    for k in tree["root"]["children"]:
        walk(k, 0)
    return rows


def score_section(db: Session, scope: Scope, plan_id: int, period: Period, unit: str) -> dict:
    snap = scoring.latest_approved(db, plan_id, period.id, unit)
    if snap is not None:
        tree, scheme = snap.result["tree"], snap.result["scheme"]
        source = {"approved": True, "snapshot_id": snap.id, "inputs_hash": snap.inputs_hash,
                  "approved_by": snap.approved_by, "approved_at": snap.approved_at.isoformat() if snap.approved_at else None}
    else:
        live = scoring.preview(db, scope, plan_id, period.id, unit)
        tree, scheme = live["tree"], live["scheme"]
        source = {"approved": False, "snapshot_id": None, "note": "No approved score snapshot: live calculation."}
    root = tree["root"]
    return {"source": source, "scheme": {"code": scheme["code"], "version": scheme["version"], "status": scheme["status"],
                                         "rating_order": scheme["rating_order"], "cap_pct": scheme["cap_pct"],
                                         "coverage_gate_pct": scheme["coverage_gate_pct"], "bands": scheme["bands"]},
            "root": {k: root.get(k) for k in ("achievement", "rating", "rating_label", "status", "method",
                                               "coverage_pct")},
            "rows": _flatten(tree)}


def trend_section(db: Session, plan_id: int, period: Period, unit: str) -> list[dict]:
    rows = (db.query(ScoreSnapshot, Period).join(Period, Period.id == ScoreSnapshot.period_id)
            .filter(ScoreSnapshot.plan_id == plan_id, ScoreSnapshot.org_unit_code == unit,
                    ScoreSnapshot.status == "approved", Period.period_type == period.period_type,
                    Period.start_date <= period.start_date)
            .order_by(Period.start_date).all())
    return [{"period": p.label, "rating": s.rating, "rating_label": s.rating_label, "achievement": s.achievement,
             "completeness_pct": s.completeness_pct, "snapshot_id": s.id} for s, p in rows][-8:]


def submissions_section(db: Session, scope: Scope, plan_id: int | None, period: Period, units: set[str]) -> list[dict]:
    q = (db.query(CycleAssignment, ReportingCycle).join(ReportingCycle, ReportingCycle.id == CycleAssignment.cycle_id)
         .filter(ReportingCycle.period_id == period.id, CycleAssignment.org_unit_code.in_(sorted(units) or [""])))
    if plan_id:
        q = q.filter(ReportingCycle.plan_id == plan_id)
    out = []
    for a, c in q.order_by(CycleAssignment.org_unit_code, CycleAssignment.id):
        if not scope.can_see(a.org_unit_code):
            continue
        ind = db.get(Indicator, a.indicator_id)
        upd = db.get(ProgressUpdate, a.current_update_id) if a.current_update_id else None
        dqa = db.query(DqaAssessment).filter_by(update_id=upd.id).all() if upd else []
        target = strategy.target_for(db, ind, a.org_unit_code, period)
        out.append({"assignment_id": a.id, "indicator": f"{ind.code} {ind.name}", "unit_of_measure": ind.unit,
                    "org_unit_code": a.org_unit_code, "status": a.status, "cycle_status": c.status,
                    "due_on": c.due_on.isoformat() if c.due_on else None,
                    "value_state": upd.value_state if upd else None, "value": upd.value if upd else None,
                    "target": target.value if target else None,
                    "off_target": strategy.off_target(ind.polarity, upd.value if upd else None, target),
                    "revision": upd.revision if upd else None, "late": bool(upd and upd.late),
                    "overdue": bool(c.status == "open" and a.status in ("not_submitted", "returned") and c.due_on
                                    and c.due_on < date.today()),
                    "narrative": upd.narrative if upd else None,
                    "variance_reason": upd.variance_reason if upd else None,
                    "corrective_action": upd.corrective_action if upd else None,
                    "dq_fails": [f"{d.check}: {d.reason}" for d in dqa if d.result == "fail"],
                    "dq_warns": [f"{d.check}: {d.reason}" for d in dqa if d.result == "warn"]})
    return out


def actions_section(db: Session, scope: Scope, units: set[str]) -> list[dict]:
    today = date.today()
    q = db.query(Action).filter(Action.org_unit_code.in_(sorted(units) or [""]),
                                Action.status.in_(("open", "in_progress", "completed")))
    return [{"ref": a.ref, "title": a.title, "owner": a.owner, "org_unit_code": a.org_unit_code,
             "due_date": a.due_date.isoformat() if a.due_date else None, "status": a.status, "priority": a.priority,
             "overdue": bool(a.due_date and a.due_date < today and a.status in ("open", "in_progress")),
             "source_type": a.source_type}
            for a in q.order_by(Action.due_date.is_(None), Action.due_date) if scope.can_see(a.org_unit_code)]


def freeze(db: Session, scope: Scope, kind: str, plan_id: int | None, period: Period, unit: str) -> dict:
    children, _ = _tree(db)
    units = {u for u in subtree(children, unit) if scope.can_see(u)}
    names = unit_names(db)
    data: dict = {"kind": kind, "frozen_at": datetime.utcnow().isoformat(timespec="seconds"),
                  "period": {"id": period.id, "label": period.label, "type": period.period_type,
                             "start": period.start_date.isoformat(), "end": period.end_date.isoformat()},
                  "unit": {"code": unit, "name": names.get(unit, unit)},
                  "unit_names": {u: names.get(u, u) for u in sorted(units)}}
    if plan_id:
        from app.modules.strategy.models import Plan
        p = db.get(Plan, plan_id)
        data["plan"] = {"id": p.id, "code": p.code, "title": p.title}
    if kind in ("board_pack", "scorecard_detail") and plan_id:
        data["score"] = score_section(db, scope, plan_id, period, unit)
        data["trend"] = trend_section(db, plan_id, period, unit)
    if kind in ("board_pack", "submission_dq", "exceptions"):
        data["submissions"] = submissions_section(db, scope, plan_id, period, units)
    if kind in ("board_pack", "exceptions"):
        data["actions"] = actions_section(db, scope, units)
    if kind == "exceptions":
        data["sources"] = [{"code": s["code"], "name": s["name"], "last_success_at": s["last_success_at"],
                            "overdue": s["overdue"], "last_status": s["last_status"]} for s in freshness(db)]
        if plan_id:
            data["score"] = score_section(db, scope, plan_id, period, unit)
    ctx = {"kind": kind, "plan_id": plan_id, "period": period, "unit": unit, "units": units}
    for provider in SECTION_PROVIDERS:
        out = provider(db, scope, ctx)
        if out:
            key, value = out
            data[key] = value
    return data
