"""
/api/regulatory/* — regulator packs, returns and league-table runs.

  GET  /pack-files                 pack files shipped under tenants/_packs/regulators
  GET  /packs, POST /packs/import {file}, GET /packs/{id}
  PUT  /packs/{id}                 edit a draft's content (reason required)
  POST /packs/{id}/approve         second regulatory officer; refused while blockers remain
  GET/POST /returns, GET /returns/{id}, PUT /returns/{id}/values, POST /returns/{id}/prefill,
  POST /returns/{id}/submit, GET /returns/{id}/export
  GET/POST /league-runs, GET /league-runs/{id}
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.regulatory import service
from app.modules.regulatory.models import LeagueTableRun, RegulatoryReturn, RegulatorPack
from app.platform.errors import NotFound
from app.platform.scope import Scope, get_scope

router = APIRouter(prefix="/api/regulatory", tags=["Regulatory"])


class ImportIn(BaseModel):
    file: str


class PackEdit(BaseModel):
    content: dict[str, Any]
    reason: str


class NoteIn(BaseModel):
    note: Optional[str] = None


class ReturnIn(BaseModel):
    pack_id: int
    period_label: str


class ValueIn(BaseModel):
    code: str
    value: Optional[float] = None
    note: Optional[str] = None


class PrefillIn(BaseModel):
    fiscal_year: int


class LeagueIn(BaseModel):
    pack_id: int
    return_id: Optional[int] = None
    peers: list[dict[str, Any]] = []
    label: Optional[str] = None


@router.get("/pack-files")
def pack_files(scope: Scope = Depends(get_scope)):
    service._view(scope)
    return service.available_files()


@router.get("/packs")
def packs(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service._view(scope)
    return [service.pack_dict(db, p, scope) for p in
            db.query(RegulatorPack).order_by(RegulatorPack.regulator, RegulatorPack.cycle, RegulatorPack.version.desc())]


@router.post("/packs/import", status_code=201)
def import_pack(body: ImportIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = service.import_pack(db, scope, body.file)
    db.commit()
    return service.pack_dict(db, p, scope, full=True)


@router.get("/packs/{pack_id}")
def get_pack(pack_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return service.pack_dict(db, service.get_pack(db, scope, pack_id), scope, full=True)


@router.put("/packs/{pack_id}")
def edit_pack(pack_id: int, body: PackEdit, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = service.update_pack(db, scope, pack_id, body.content, body.reason)
    db.commit()
    return service.pack_dict(db, p, scope, full=True)


@router.post("/packs/{pack_id}/approve")
def approve_pack(pack_id: int, body: NoteIn = NoteIn(), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = service.approve_pack(db, scope, pack_id, body.note)
    db.commit()
    return service.pack_dict(db, p, scope, full=True)


@router.get("/returns")
def returns(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service._view(scope)
    return [service.return_dict(db, r, scope) for r in db.query(RegulatoryReturn).order_by(RegulatoryReturn.id.desc())]


@router.post("/returns", status_code=201)
def create_return(body: ReturnIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = service.create_return(db, scope, body.pack_id, body.period_label)
    db.commit()
    return service.return_dict(db, r, scope)


@router.get("/returns/{return_id}")
def get_return(return_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r, _ = service._return(db, scope, return_id)
    return service.return_dict(db, r, scope)


@router.put("/returns/{return_id}/values")
def set_values(return_id: int, body: list[ValueIn], scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    for v in body:
        service.set_value(db, scope, return_id, v.code, v.value, v.note)
    db.commit()
    r, _ = service._return(db, scope, return_id)
    return service.return_dict(db, r, scope)


@router.post("/returns/{return_id}/prefill")
def prefill(return_id: int, body: PrefillIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    n = service.prefill(db, scope, return_id, body.fiscal_year)
    db.commit()
    r, _ = service._return(db, scope, return_id)
    return {**service.return_dict(db, r, scope), "prefilled": n}


@router.post("/returns/{return_id}/submit")
def submit(return_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = service.submit_return(db, scope, return_id)
    db.commit()
    return service.return_dict(db, r, scope)


@router.get("/returns/{return_id}/export")
def export(return_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    data, name = service.export_return(db, scope, return_id)
    db.commit()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/league-runs")
def league_runs(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service._view(scope)
    return [service.run_dict(r) for r in db.query(LeagueTableRun).order_by(LeagueTableRun.id.desc()).limit(100)]


@router.post("/league-runs", status_code=201)
def run_league(body: LeagueIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    run = service.run_league(db, scope, body.pack_id, body.return_id, body.peers, body.label)
    db.commit()
    return service.run_dict(run)


@router.get("/league-runs/{run_id}")
def get_run(run_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service._view(scope)
    run = db.get(LeagueTableRun, run_id)
    if run is None:
        raise NotFound("Run not found.")
    return service.run_dict(run)
