"""
/api/reports-hub/* — report templates, instances, approvals and outputs.

  GET   /templates
  GET   /instances?status=            reports the caller may see
  POST  /instances                    create a draft and freeze its data
  GET   /instances/{id}               detail, approvals, outputs, access log
  POST  /instances/{id}/freeze        refresh the frozen data (draft only)
  PUT   /instances/{id}/commentary    commentary sections (draft only)
  POST  /instances/{id}/transition    submit | return | approve | publish | withdraw
  GET   /instances/{id}/output/{fmt}?download=   html | pdf | xlsx, rendered from the frozen data
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.reporting import service
from app.modules.reporting.models import ReportTemplate
from app.platform.errors import NotFound
from app.platform.router import MY_WORK_PROVIDERS
from app.platform.scope import Scope, get_scope

router = APIRouter(prefix="/api/reports-hub", tags=["Reporting hub"])
MY_WORK_PROVIDERS.append(service.my_work)


class InstanceIn(BaseModel):
    template_id: int
    period_id: int
    org_unit_code: str
    plan_id: Optional[int] = None
    title: Optional[str] = None
    audience: Optional[str] = None


class CommentaryIn(BaseModel):
    commentary: dict[str, str]


class TransitionIn(BaseModel):
    name: str
    reason: Optional[str] = None


@router.get("/templates")
def templates(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not (scope.org_wide or scope.unit_roles):
        raise NotFound("Not found.")
    service.ensure_templates(db)
    db.commit()
    return [{"id": t.id, "code": t.code, "version": t.version, "name": t.name, "kind": t.kind,
             "audience": t.audience, "description": t.description}
            for t in db.query(ReportTemplate).filter_by(active=True).order_by(ReportTemplate.id)]


@router.get("/instances")
def instances(status: Optional[str] = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return [service.instance_dict(db, r, scope) for r in service.visible(db, scope, status)]


@router.post("/instances", status_code=201)
def create(body: InstanceIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.ensure_templates(db)
    inst = service.create(db, scope, **body.model_dump())
    db.commit()
    return service.instance_dict(db, inst, scope, full=True)


@router.get("/instances/{inst_id}")
def get(inst_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return service.instance_dict(db, service._get(db, scope, inst_id), scope, full=True)


@router.post("/instances/{inst_id}/freeze")
def freeze(inst_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    inst = service.freeze(db, scope, inst_id)
    db.commit()
    return service.instance_dict(db, inst, scope, full=True)


@router.put("/instances/{inst_id}/commentary")
def commentary(inst_id: int, body: CommentaryIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    inst = service.set_commentary(db, scope, inst_id, body.commentary)
    db.commit()
    return service.instance_dict(db, inst, scope, full=True)


@router.post("/instances/{inst_id}/transition")
def transition(inst_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    inst = service.transition(db, scope, inst_id, body.name, body.reason)
    db.commit()
    return service.instance_dict(db, inst, scope, full=True)


@router.get("/instances/{inst_id}/output/{fmt}")
def output(inst_id: int, fmt: str, download: bool = False, scope: Scope = Depends(get_scope),
           db: Session = Depends(get_db)):
    data, media, filename = service.output(db, scope, inst_id, fmt, download)
    db.commit()   # the access-log entry (and a first stored output) are kept
    disposition = "attachment" if download or fmt != "html" else "inline"
    return Response(data, media_type=media, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        # Report HTML is self-contained: no scripts, no external loads.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})
