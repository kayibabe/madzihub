"""
/api/people/* — performance contracts and staff appraisals (policy-gated, private).

  GET  /gate                          are the modules usable, and under which policy
  POST /gate                          HR officer records the approved policy for a module
  GET/POST /contracts, GET /contracts/{id}, POST /contracts/{id}/transition
  GET/POST /appraisals, GET /appraisals/{id}, POST /appraisals/{id}/transition
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.people import service
from app.platform.scope import Scope, get_scope

router = APIRouter(prefix="/api/people", tags=["People (private)"])


class GateIn(BaseModel):
    module: str
    policy_ref: str
    summary: Optional[str] = None


class ContractIn(BaseModel):
    plan_id: int
    period_id: int
    org_unit_code: str
    holder: str
    supervisor: str
    items: list[dict[str, Any]]


class AppraisalIn(BaseModel):
    employee: str
    appraiser: str
    period_label: str
    objectives: list[dict[str, Any]]


class TransitionIn(BaseModel):
    name: str
    reason: Optional[str] = None
    ratings: Optional[dict[str, float]] = None
    comment: Optional[str] = None
    overall: Optional[float] = None
    adjusted_rating: Optional[float] = None


@router.get("/gate")
def gate(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return {**service.gate_status(db), "is_hr_officer": "hr_officer" in scope.functions,
            "rating_scale": service.RATING_SCALE}


@router.post("/gate", status_code=201)
def confirm(body: GateIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.confirm_policy(db, scope, body.module, body.policy_ref, body.summary)
    db.commit()
    return service.gate_status(db)


@router.get("/contracts")
def contracts(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.require_gate(db, "performance_contracts")
    return [service.contract_dict(db, c, scope) for c in service.visible_contracts(db, scope)]


@router.post("/contracts", status_code=201)
def create_contract(body: ContractIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = service.create_contract(db, scope, **body.model_dump())
    db.commit()
    return service.contract_dict(db, c, scope)


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.require_gate(db, "performance_contracts")
    return service.contract_dict(db, service.get_contract(db, scope, contract_id), scope)


@router.post("/contracts/{contract_id}/transition")
def transition_contract(contract_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = service.transition_contract(db, scope, contract_id, body.name, body.reason, body.adjusted_rating)
    db.commit()
    return service.contract_dict(db, c, scope)


@router.get("/appraisals")
def appraisals(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.require_gate(db, "staff_appraisal")
    return [service.appraisal_dict(db, a, scope) for a in service.visible_appraisals(db, scope)]


@router.post("/appraisals", status_code=201)
def create_appraisal(body: AppraisalIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = service.create_appraisal(db, scope, **body.model_dump())
    db.commit()
    return service.appraisal_dict(db, a, scope)


@router.get("/appraisals/{appraisal_id}")
def get_appraisal(appraisal_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.require_gate(db, "staff_appraisal")
    return service.appraisal_dict(db, service.get_appraisal(db, scope, appraisal_id), scope)


@router.post("/appraisals/{appraisal_id}/transition")
def transition_appraisal(appraisal_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = service.transition_appraisal(db, scope, appraisal_id, body.name, reason=body.reason, ratings=body.ratings,
                                     comment=body.comment, overall=body.overall)
    db.commit()
    return service.appraisal_dict(db, a, scope)
