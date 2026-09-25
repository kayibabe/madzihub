"""
/api/documents/* — controlled documents, evidence, versions, search and downloads.

  GET   /types
  GET   /?type=&controlled=&status=&tag=       documents the caller may see (master list: controlled=true)
  POST  /                                      create (metadata only)
  GET   /search?q=                             full text + title; results and snippets limited to scope
  POST  /evidence                              multipart: attach a file as evidence to any record
  GET   /{id}                                  detail with versions and approvals
  PUT   /{id}                                  edit metadata
  POST  /{id}/versions                         multipart: add a file version (drafts / evidence)
  POST  /{id}/transition                       approve | make_effective | withdraw
  POST  /{id}/revise                           start the next revision of an effective document
  GET   /{id}/download?version=                hash-checked download (audited)
"""
from __future__ import annotations

from datetime import date
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.modules.documents import service
from app.modules.documents.models import DocumentType
from app.platform.errors import Invalid, NotFound
from app.platform.scope import Scope, get_scope

router = APIRouter(prefix="/api/documents", tags=["Documents"])


async def _read(file: UploadFile) -> bytes:
    limit = settings.upload_limit_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(f"The file is larger than {settings.upload_limit_mb} MB.")
    return data


class DocumentIn(BaseModel):
    type_id: int
    title: str
    org_unit_code: str
    owner: Optional[str] = None
    approver: Optional[str] = None
    classification: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    metadata: Optional[dict] = None
    effective_date: Optional[date] = None


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    approver: Optional[str] = None
    classification: Optional[str] = None
    tags: Optional[list[str]] = None
    metadata: Optional[dict] = None
    effective_date: Optional[date] = None
    review_date: Optional[date] = None


class TransitionIn(BaseModel):
    name: str
    reason: Optional[str] = None


@router.get("/types")
def types(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not (scope.org_wide or scope.unit_roles):
        raise NotFound("Not found.")
    service.ensure_types(db)
    db.commit()
    return [{"id": t.id, "code": t.code, "name": t.name, "controlled": t.controlled, "number_prefix": t.number_prefix,
             "review_interval_months": t.review_interval_months, "allowed_extensions": t.allowed_extensions,
             "metadata_fields": t.metadata_fields or [], "default_classification": t.default_classification}
            for t in db.query(DocumentType).filter_by(active=True).order_by(DocumentType.controlled.desc(), DocumentType.name)]


@router.get("")
def list_documents(type: Optional[str] = None, controlled: Optional[bool] = None, status: Optional[str] = None,
                   tag: Optional[str] = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return [service.document_dict(db, d, scope)
            for d in service.query(db, scope, type_code=type, controlled=controlled, status=status, tag=tag)]


@router.post("", status_code=201)
def create(body: DocumentIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    service.ensure_types(db)
    d = service.create(db, scope, **body.model_dump())
    db.commit()
    return service.document_dict(db, d, scope, full=True)


@router.get("/search")
def search(q: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return service.search(db, scope, q)


@router.post("/evidence", status_code=201)
async def evidence(entity_type: str = Form(...), entity_id: str = Form(...), file: UploadFile = File(...),
                   title: Optional[str] = Form(None), document_id: Optional[int] = Form(None),
                   note: Optional[str] = Form(None), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    data = await _read(file)
    d, v = service.attach_evidence(db, scope, entity_type, entity_id, file.filename or "evidence", data, title,
                                   document_id, note)
    db.commit()
    return {**service.document_dict(db, d, scope, full=True), "attached_version": v.version}


@router.get("/{doc_id}")
def get(doc_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return service.document_dict(db, service.get(db, scope, doc_id), scope, full=True)


@router.put("/{doc_id}")
def update(doc_id: int, body: DocumentUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    d = service.update(db, scope, doc_id, body.model_dump(exclude_unset=True))
    db.commit()
    return service.document_dict(db, d, scope, full=True)


@router.post("/{doc_id}/versions", status_code=201)
async def add_version(doc_id: int, file: UploadFile = File(...), change_note: Optional[str] = Form(None),
                      scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    data = await _read(file)
    service.add_version(db, scope, doc_id, file.filename or "upload", data, change_note)
    db.commit()
    return service.document_dict(db, service.get(db, scope, doc_id), scope, full=True)


@router.post("/{doc_id}/transition")
def transition(doc_id: int, body: TransitionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    d = service.transition(db, scope, doc_id, body.name, body.reason)
    db.commit()
    return service.document_dict(db, d, scope, full=True)


@router.post("/{doc_id}/revise", status_code=201)
def revise(doc_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    d = service.revise(db, scope, doc_id)
    db.commit()
    return service.document_dict(db, d, scope, full=True)


@router.get("/{doc_id}/download")
def download(doc_id: int, version: Optional[int] = None, scope: Scope = Depends(get_scope),
             db: Session = Depends(get_db)):
    data, v = service.download(db, scope, doc_id, version)
    db.commit()
    return Response(data, media_type=v.mime, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(v.filename)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'", "X-Document-SHA256": v.sha256})
