"""
/api/scorecard/* — scoring schemes, weights, live scorecards, snapshots and the strategy map.

  GET/POST  /schemes                    list (creates the proposed default on first use) / new or new version
  GET/PUT   /schemes/{id}               detail / edit a draft (incl. its five bands)
  POST      /schemes/{id}/transition    approve (sign-off by someone other than the author) | retire
  GET/PUT   /plans/{id}/weights         weight groups with sums / save weights (each level sums to 100)
  GET       /preview?plan_id&period_id&org_unit&scheme_id     live calculation, not stored
  GET/POST  /snapshots                  list / take a snapshot (frozen inputs and result)
  GET       /snapshots/{id}
  POST      /snapshots/{id}/override    change one item's rating with a reason (draft only)
  POST      /snapshots/{id}/approve     approve; supersedes the previous approved snapshot
  GET       /plans/{id}/map?period_id&org_unit      strategy map with ratings
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.scorecard import service
from app.modules.scorecard.models import ScoringScheme
from app.modules.strategy.models import PlanNode
from app.platform import entities
from app.platform.models import EntityLink
from app.platform.scope import Scope, get_scope

router = APIRouter(prefix="/api/scorecard", tags=["Scorecard"])


class BandIn(BaseModel):
    rating: int
    label: str
    min_achievement: float
    max_achievement: Optional[float] = None


class SchemeIn(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    from_scheme_id: Optional[int] = None
    description: Optional[str] = None
    rating_order: Optional[str] = None
    cap_pct: Optional[float] = None
    zero_target_rule: Optional[str] = None
    lower_method: Optional[str] = None
    missing_policy: Optional[str] = None
    coverage_gate_pct: Optional[float] = None


class SchemeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    rating_order: Optional[str] = None
    cap_pct: Optional[float] = None
    zero_target_rule: Optional[str] = None
    lower_method: Optional[str] = None
    missing_policy: Optional[str] = None
    coverage_gate_pct: Optional[float] = None
    bands: Optional[list[BandIn]] = None


class TransitionIn(BaseModel):
    name: str
    reason: Optional[str] = None


class WeightItem(BaseModel):
    type: str
    id: int
    weight: Optional[float] = None


class WeightsIn(BaseModel):
    items: list[WeightItem]
    reason: Optional[str] = None


class SnapshotIn(BaseModel):
    plan_id: int
    period_id: int
    org_unit_code: str
    scheme_id: Optional[int] = None
    note: Optional[str] = None


class OverrideIn(BaseModel):
    key: str
    rating: Optional[int] = None
    reason: str


class ApproveIn(BaseModel):
    note: Optional[str] = None


def _any_scope(scope: Scope) -> None:
    from app.platform.errors import NotFound
    if not (scope.org_wide or scope.unit_roles):
        raise NotFound("Not found.")


@router.get("/schemes")
def list_schemes(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _any_scope(scope)
    if service.ensure_default_scheme(db):
        db.commit()
    rows = db.query(ScoringScheme).order_by(ScoringScheme.code, ScoringScheme.version.desc()).all()
    manager = scope.has_function("strategy_manager") and not scope.read_only
    return [{**service.scheme_dict(s), "can_edit": manager and s.status == "draft",
             "can_approve": manager and s.status == "draft" and s.created_by != scope.username} for s in rows]


@router.post("/schemes", status_code=201)
def create_scheme(body: SchemeIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    s = service.create_scheme(db, scope, body.model_dump(exclude_none=True), body.from_scheme_id)
    db.commit()
    return service.scheme_dict(s)


@router.get("/schemes/{scheme_id}")
def get_scheme(scheme_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _any_scope(scope)
    return service.scheme_dict(service._scheme(db, scheme_id))


@router.put("/schemes/{scheme_id}")
def update_scheme(scheme_id: int, body: SchemeUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if data.get("bands") is not None:
        data["bands"] = [b.model_dump() if hasattr(b, "model_dump") else b for b in body.bands]
    s = service.update_scheme(db, scope, scheme_id, data)
    db.commit()
    return service.scheme_dict(s)


@router.post("/schemes/{scheme_id}/transition")
def transition_scheme(scheme_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    s = service.transition_scheme(db, scope, scheme_id, body.name, body.reason)
    db.commit()
    return service.scheme_dict(s)


@router.get("/plans/{plan_id}/weights")
def get_weights(plan_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    plan, _ = entities.load(db, scope, "plan", plan_id)
    return service.weight_groups(db, plan)


@router.put("/plans/{plan_id}/weights")
def set_weights(plan_id: int, body: WeightsIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    groups = service.set_weights(db, scope, plan_id, [i.model_dump() for i in body.items], body.reason)
    db.commit()
    return groups


@router.get("/preview")
def preview(plan_id: int, period_id: int, org_unit: str = "org", scheme_id: Optional[int] = None,
            scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    out = service.preview(db, scope, plan_id, period_id, org_unit, scheme_id)
    db.commit()   # the default scheme may have been created on first use
    return out


@router.get("/snapshots")
def list_snapshots(plan_id: Optional[int] = None, period_id: Optional[int] = None, org_unit: Optional[str] = None,
                   scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return [service.snapshot_dict(db, s, scope) for s in service.list_snapshots(db, scope, plan_id, period_id, org_unit)]


@router.post("/snapshots", status_code=201)
def create_snapshot(body: SnapshotIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    s = service.create_snapshot(db, scope, body.plan_id, body.period_id, body.org_unit_code, body.scheme_id, body.note)
    db.commit()
    return service.snapshot_dict(db, s, scope, full=True)


@router.get("/snapshots/{snap_id}")
def get_snapshot(snap_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return service.snapshot_dict(db, service._snapshot(db, scope, snap_id), scope, full=True)


@router.post("/snapshots/{snap_id}/override")
def override(snap_id: int, body: OverrideIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    s = service.set_override(db, scope, snap_id, body.key, body.rating, body.reason)
    db.commit()
    return service.snapshot_dict(db, s, scope, full=True)


@router.post("/snapshots/{snap_id}/approve")
def approve(snap_id: int, body: ApproveIn = ApproveIn(), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    s = service.approve_snapshot(db, scope, snap_id, body.note)
    db.commit()
    return service.snapshot_dict(db, s, scope, full=True)


@router.get("/plans/{plan_id}/map")
def strategy_map(plan_id: int, period_id: int, org_unit: str = "org", scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    """Plan items with ratings: the latest approved snapshot, else a live (unapproved) calculation."""
    snap = service.latest_approved(db, plan_id, period_id, org_unit)
    if snap is not None:
        entities.load(db, scope, "score_snapshot", snap.id)
        tree, source = snap.result["tree"], {"kind": "approved_snapshot", "id": snap.id}
        scheme = snap.result.get("scheme")
    else:
        live = service.preview(db, scope, plan_id, period_id, org_unit)
        db.commit()
        tree, source, scheme = live["tree"], {"kind": "live", "provisional": live["provisional"]}, live["scheme"]
    nodes = db.query(PlanNode).filter(PlanNode.plan_id == plan_id, PlanNode.retired.is_(False)).all()
    visible = [n for n in nodes if scope.can_see(n.org_unit_code) or n.org_unit_code == "org"]
    ids = {n.id for n in visible}
    links = db.query(EntityLink).filter(EntityLink.from_type == "plan_node", EntityLink.to_type == "plan_node",
                                        EntityLink.relation == "contributes_to").all()
    items = tree["items"]
    return {"source": source, "scheme": scheme, "root": tree["root"],
            "nodes": [{"id": n.id, "parent_id": n.parent_id, "node_type": n.node_type, "code": n.code, "title": n.title,
                       "status": n.status, "rating": (items.get(f"n{n.id}") or {}).get("rating"),
                       "rating_label": (items.get(f"n{n.id}") or {}).get("rating_label"),
                       "score_status": (items.get(f"n{n.id}") or {}).get("status")} for n in visible],
            "links": [{"from": int(l.from_id), "to": int(l.to_id)} for l in links
                      if int(l.from_id) in ids and int(l.to_id) in ids]}
