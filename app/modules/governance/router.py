"""
/api/governance/* — meetings and resolutions, audit findings, risk criteria and the risk register.

  GET/POST /meetings, GET /meetings/{id}, POST /meetings/{id}/transition, POST /meetings/{id}/resolutions
  POST /resolutions/{id}/transition                  implement | close | reopen | cancel
  GET/POST /findings, GET/PUT /findings/{id}, POST /findings/{id}/transition
  GET /risk-matrices, GET /risk-matrices/template?likelihood=&impact=, POST/PUT /risk-matrices[/{id}],
  POST /risk-matrices/{id}/activate
  GET/POST /risks, GET/PUT /risks/{id}, POST /risks/{id}/assess, POST /risks/{id}/controls[/{cid}],
  POST /risks/{id}/transition, GET /risk-heatmap?kind=residual|inherent
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.governance import service
from app.modules.governance.models import AuditFinding, Meeting, Resolution, Risk, RiskMatrix
from app.modules.reporting.builders import SECTION_PROVIDERS
from app.platform import entities
from app.platform.errors import NotFound
from app.platform.scope import Scope, get_scope

router = APIRouter(prefix="/api/governance", tags=["Governance & Risk"])
SECTION_PROVIDERS.append(service.risks_section)


class TransitionIn(BaseModel):
    name: str
    reason: Optional[str] = None
    minutes_document_id: Optional[int] = None
    response: Optional[str] = None
    agreed_due_date: Optional[date] = None


def _any(scope: Scope) -> None:
    if not (scope.org_wide or scope.unit_roles):
        raise NotFound("Not found.")


# ── meetings ────────────────────────────────────────────────────────────────

class MeetingIn(BaseModel):
    body: str
    title: str
    meeting_date: date
    org_unit_code: str = "org"
    secretary: Optional[str] = None


class ResolutionIn(BaseModel):
    text: str
    owner: Optional[str] = None
    due_date: Optional[date] = None
    org_unit_code: Optional[str] = None
    number: Optional[str] = None


def _meeting_dict(db: Session, m: Meeting, scope: Scope) -> dict:
    res = [r for r in db.query(Resolution).filter_by(meeting_id=m.id).order_by(Resolution.id) if scope.can_see(r.org_unit_code)]
    secretary = scope.has_function("board_secretary") and not scope.read_only
    return {"id": m.id, "body": m.body, "title": m.title, "meeting_date": m.meeting_date.isoformat(),
            "org_unit_code": m.org_unit_code, "status": m.status, "secretary": m.secretary,
            "minutes_document_id": m.minutes_document_id,
            "allowed": service.MEETING_FLOW.allowed(m.status) if secretary else [],
            "can_add_resolution": secretary and m.status != "scheduled",
            "resolutions": [{"id": r.id, "number": r.number, "text": r.text, "owner": r.owner, "status": r.status,
                             "due_date": r.due_date.isoformat() if r.due_date else None, "action_id": r.action_id,
                             "implementation_note": r.implementation_note, "org_unit_code": r.org_unit_code,
                             "allowed": [t for t in service.RESOLUTION_FLOW.allowed(r.status)
                                         if (t == "implement" and (secretary or r.owner == scope.username) and not scope.read_only)
                                         or (t == "close" and secretary and r.owner != scope.username)
                                         or (t in ("reopen", "cancel") and secretary)]} for r in res]}


@router.get("/meetings")
def meetings(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    q = scope.filter(db.query(Meeting), Meeting.org_unit_code).order_by(Meeting.meeting_date.desc())
    return [_meeting_dict(db, m, scope) for m in q.limit(300)]


@router.post("/meetings", status_code=201)
def create_meeting(body: MeetingIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    m = service.create_meeting(db, scope, **body.model_dump())
    db.commit()
    return _meeting_dict(db, m, scope)


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    m, _ = entities.load(db, scope, "meeting", meeting_id)
    return _meeting_dict(db, m, scope)


@router.post("/meetings/{meeting_id}/transition")
def transition_meeting(meeting_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    m = service.transition_meeting(db, scope, meeting_id, body.name, body.minutes_document_id)
    db.commit()
    return _meeting_dict(db, m, scope)


@router.post("/meetings/{meeting_id}/resolutions", status_code=201)
def add_resolution(meeting_id: int, body: ResolutionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.add_resolution(db, scope, meeting_id, **body.model_dump())
    db.commit()
    return _meeting_dict(db, db.get(Meeting, meeting_id), scope)


@router.post("/resolutions/{res_id}/transition")
def transition_resolution(res_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = service.transition_resolution(db, scope, res_id, body.name, body.reason)
    db.commit()
    return _meeting_dict(db, db.get(Meeting, r.meeting_id), scope)


# ── audit findings ──────────────────────────────────────────────────────────

class FindingIn(BaseModel):
    audit_name: str
    title: str
    rating: str
    owner: str
    org_unit_code: str = "org"
    source: str = "internal_audit"
    description: Optional[str] = None
    recommendation: Optional[str] = None


class FindingUpdate(BaseModel):
    audit_name: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    recommendation: Optional[str] = None
    rating: Optional[str] = None
    owner: Optional[str] = None


@router.get("/findings")
def findings(status: Optional[str] = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    q = scope.filter(db.query(AuditFinding), AuditFinding.org_unit_code)
    if status:
        q = q.filter(AuditFinding.status == status)
    return {"findings": [service.finding_dict(db, f, scope) for f in q.order_by(AuditFinding.id.desc()).limit(500)],
            "ratings": list(service.FINDING_RATINGS), "sources": list(service.FINDING_SOURCES),
            "can_raise": "auditor" in scope.functions and not scope.read_only}


@router.post("/findings", status_code=201)
def create_finding(body: FindingIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f = service.create_finding(db, scope, body.model_dump())
    db.commit()
    return service.finding_dict(db, f, scope, full=True)


@router.get("/findings/{finding_id}")
def get_finding(finding_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f, _ = entities.load(db, scope, "audit_finding", finding_id)
    return service.finding_dict(db, f, scope, full=True)


@router.put("/findings/{finding_id}")
def update_finding(finding_id: int, body: FindingUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f = service.update_finding(db, scope, finding_id, body.model_dump(exclude_unset=True))
    db.commit()
    return service.finding_dict(db, f, scope, full=True)


@router.post("/findings/{finding_id}/transition")
def transition_finding(finding_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f = service.transition_finding(db, scope, finding_id, body.name, reason=body.reason, response=body.response,
                                   agreed_due_date=body.agreed_due_date)
    db.commit()
    return service.finding_dict(db, f, scope, full=True)


# ── risk criteria ───────────────────────────────────────────────────────────

class MatrixIn(BaseModel):
    name: str
    likelihood_levels: list[dict[str, Any]]
    impact_levels: list[dict[str, Any]]
    bands: list[dict[str, Any]]


@router.get("/risk-matrices")
def matrices(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _any(scope)
    return {"matrices": [service.matrix_dict(m) for m in db.query(RiskMatrix).order_by(RiskMatrix.id.desc())],
            "can_manage": scope.has_function("risk_manager") and not scope.read_only}


@router.get("/risk-matrices/template")
def matrix_template(likelihood: int = Query(5, ge=2, le=10), impact: int = Query(5, ge=2, le=10),
                    scope: Scope = Depends(get_scope)):
    _any(scope)
    return service.matrix_template(likelihood, impact)


@router.post("/risk-matrices", status_code=201)
def create_matrix(body: MatrixIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    m = service.save_matrix(db, scope, body.model_dump())
    db.commit()
    return service.matrix_dict(m)


@router.put("/risk-matrices/{matrix_id}")
def update_matrix(matrix_id: int, body: MatrixIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    m = service.save_matrix(db, scope, body.model_dump(), matrix_id)
    db.commit()
    return service.matrix_dict(m)


@router.post("/risk-matrices/{matrix_id}/activate")
def activate(matrix_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    m = service.activate_matrix(db, scope, matrix_id)
    db.commit()
    return service.matrix_dict(m)


# ── risks ───────────────────────────────────────────────────────────────────

class RiskIn(BaseModel):
    title: str
    org_unit_code: str = "org"
    owner: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    cause: Optional[str] = None
    consequence: Optional[str] = None
    review_date: Optional[date] = None
    inherent_l: Optional[int] = None
    inherent_i: Optional[int] = None
    residual_l: Optional[int] = None
    residual_i: Optional[int] = None


class RiskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    cause: Optional[str] = None
    consequence: Optional[str] = None
    owner: Optional[str] = None
    org_unit_code: Optional[str] = None
    review_date: Optional[date] = None


class AssessIn(BaseModel):
    kind: str
    likelihood: int
    impact: int
    note: Optional[str] = None


class ControlIn(BaseModel):
    description: Optional[str] = None
    control_type: Optional[str] = None
    owner: Optional[str] = None
    effectiveness: Optional[str] = None
    last_tested: Optional[date] = None
    retired: Optional[bool] = None


@router.get("/risks")
def risks(status: Optional[str] = "open", scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    q = scope.filter(db.query(Risk), Risk.org_unit_code)
    if status:
        q = q.filter(Risk.status == status)
    rows = [service.risk_dict(db, r, scope) for r in q.limit(1000)]
    rows.sort(key=lambda r: -((r["residual"] or r["inherent"] or {}).get("score") or 0))
    m = service.active_matrix(db)
    return {"risks": rows, "matrix": service.matrix_dict(m) if m else None}


@router.post("/risks", status_code=201)
def create_risk(body: RiskIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = service.create_risk(db, scope, body.model_dump())
    db.commit()
    return service.risk_dict(db, r, scope, full=True)


@router.get("/risks/{risk_id}")
def get_risk(risk_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r, _ = entities.load(db, scope, "risk", risk_id)
    return service.risk_dict(db, r, scope, full=True)


@router.put("/risks/{risk_id}")
def update_risk(risk_id: int, body: RiskUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = service.update_risk(db, scope, risk_id, body.model_dump(exclude_unset=True))
    db.commit()
    return service.risk_dict(db, r, scope, full=True)


@router.post("/risks/{risk_id}/assess", status_code=201)
def assess(risk_id: int, body: AssessIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.assess(db, scope, risk_id, body.kind, body.likelihood, body.impact, body.note)
    db.commit()
    return service.risk_dict(db, db.get(Risk, risk_id), scope, full=True)


@router.post("/risks/{risk_id}/controls", status_code=201)
def add_control(risk_id: int, body: ControlIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.add_control(db, scope, risk_id, body.model_dump(exclude_unset=True))
    db.commit()
    return service.risk_dict(db, db.get(Risk, risk_id), scope, full=True)


@router.post("/risks/{risk_id}/controls/{control_id}")
def update_control(risk_id: int, control_id: int, body: ControlIn, scope: Scope = Depends(get_scope),
                   db: Session = Depends(get_db)):
    service.add_control(db, scope, risk_id, body.model_dump(exclude_unset=True), control_id)
    db.commit()
    return service.risk_dict(db, db.get(Risk, risk_id), scope, full=True)


@router.post("/risks/{risk_id}/transition")
def transition_risk(risk_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = service.transition_risk(db, scope, risk_id, body.name, body.reason)
    db.commit()
    return service.risk_dict(db, r, scope, full=True)


@router.get("/risk-heatmap")
def risk_heatmap(kind: str = Query("residual", pattern="^(residual|inherent)$"), scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    return service.heatmap(db, scope, kind)
