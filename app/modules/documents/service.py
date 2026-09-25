"""
Document-control rules.

Access
- A document belongs to a unit; unit scope applies to the record, every version, the
  download, search results and snippets.
- Classification narrows it further: *public* and *internal* follow unit scope;
  *confidential* needs the reviewer role on the unit (or being owner/approver, or the
  document-controller duty); *restricted* is limited to owner, approver and document
  controllers. Out-of-bounds documents answer "not found".

Controlled documents
    draft ──approve──► approved ──make_effective──► effective ──(superseded by a revision)──► superseded
      └── withdraw (reason) from any state before superseded
- Only document controllers (duty) or the owner create and edit them; approval is by the
  named approver or a document controller, never by the owner or the last uploader.
- Files can be added only while a document is a draft. "Revise" creates the next revision
  (same number) as a new draft that supersedes the current one when it becomes effective.

Evidence
- attach_evidence() files a document of the evidence type under the record's unit and links
  the record to that exact version; replacing adds a version and a new pinned link.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.documents import files
from app.modules.documents.models import CLASSIFICATIONS, Document, DocumentType, DocumentVersion
from app.platform import audit, entities, filestore, links
from app.platform.errors import Conflict, Forbidden, Invalid, NotFound
from app.platform.models import EntityLink
from app.platform.notifications import REMINDER_PRODUCERS, notify
from app.platform.scope import Scope, check_unit
from app.platform.workflow import Transition, Workflow, approval_history

FLOW = Workflow("document", ("draft", "approved", "effective", "superseded", "withdrawn", "active"), [
    Transition("approve", ("draft",), "approved"),
    Transition("make_effective", ("approved",), "effective"),
    Transition("supersede", ("effective",), "superseded"),
    Transition("withdraw", ("draft", "approved", "effective", "active"), "withdrawn", reason_required=True),
])

DEFAULT_TYPES = [
    # code, name, controlled, prefix, review months, extensions, default classification
    ("evidence", "Evidence", False, None, None, ["pdf", "docx", "xlsx", "csv", "txt", "md", "png", "jpg", "jpeg"], "internal"),
    ("policy", "Policy", True, "POL", 36, ["pdf", "docx"], "internal"),
    ("procedure", "Procedure", True, "PRO", 24, ["pdf", "docx"], "internal"),
    ("plan", "Plan", True, "PLN", 12, ["pdf", "docx", "xlsx"], "internal"),
    ("form", "Form / template", True, "FRM", 24, ["pdf", "docx", "xlsx"], "internal"),
    ("minutes", "Minutes", False, None, None, ["pdf", "docx"], "confidential"),
    ("report", "Report", False, None, None, ["pdf", "docx", "xlsx"], "internal"),
]


def can_view(scope: Scope, d: Document) -> bool:
    if scope.username in (d.owner, d.approver):
        return True          # the people named on a document always see it
    if not scope.can_see(d.org_unit_code):
        return False
    involved = scope.has_function("document_controller")
    if d.classification == "restricted":
        return involved
    if d.classification == "confidential":
        return involved or scope.can(d.org_unit_code, "reviewer")
    return True


entities.register(entities.EntityType(
    key="document", label="Document", model=Document, unit_of=lambda d: d.org_unit_code,
    title_of=lambda d: f"{d.number + ' r' + str(d.revision) + ' ' if d.number else ''}{d.title}",
    can_view=can_view, page="documents",
    versions_of=lambda db, d: {v for (v,) in db.query(DocumentVersion.version).filter_by(document_id=d.id)}))


def ensure_types(db: Session) -> None:
    have = {c for (c,) in db.query(DocumentType.code)}
    for code, name, controlled, prefix, months, exts, cls in DEFAULT_TYPES:
        if code not in have:
            db.add(DocumentType(code=code, name=name, controlled=controlled, number_prefix=prefix,
                                review_interval_months=months, allowed_extensions=exts, default_classification=cls,
                                metadata_fields=[]))
    db.flush()


def _type(db: Session, type_id: int) -> DocumentType:
    t = db.get(DocumentType, type_id)
    if t is None or not t.active:
        raise NotFound("Document type not found.")
    return t


def get(db: Session, scope: Scope, doc_id: int) -> Document:
    d, _ = entities.load(db, scope, "document", doc_id)
    return d


def _may_edit(scope: Scope, d: Document) -> bool:
    if scope.read_only:
        return False
    return scope.has_function("document_controller") or d.owner == scope.username or (
        d.status == "active" and scope.can(d.org_unit_code, "contributor"))


def _next_number(db: Session, t: DocumentType) -> str:
    prefix = t.number_prefix or t.code.upper()[:3]
    nums = [n for (n,) in db.query(Document.number).filter(Document.number.like(f"{prefix}-%"))]
    seq = max([int(n.split("-")[-1]) for n in nums if n.split("-")[-1].isdigit()] or [0]) + 1
    return f"{prefix}-{seq:04d}"


def _check_metadata(t: DocumentType, metadata: dict | None) -> dict:
    metadata = dict(metadata or {})
    for f in t.metadata_fields or []:
        if f.get("required") and not str(metadata.get(f["key"], "")).strip():
            raise Invalid(f"'{f.get('label') or f['key']}' is required for a {t.name.lower()}.")
    return metadata


def _user(db: Session, username: str | None) -> str | None:
    if not username:
        return None
    from app.database import User
    if not db.query(User.id).filter(User.username == username, User.is_active.is_(True)).first():
        raise Invalid(f"Unknown or inactive user '{username}'.")
    return username


def create(db: Session, scope: Scope, *, type_id: int, title: str, org_unit_code: str,
           owner: str | None = None, approver: str | None = None, classification: str | None = None,
           description: str | None = None, tags: list[str] | None = None, metadata: dict | None = None,
           effective_date: date | None = None) -> Document:
    t = _type(db, type_id)
    unit = check_unit(db, org_unit_code)
    if t.controlled:
        if not (scope.has_function("document_controller") or scope.can(unit, "reviewer")) or scope.read_only:
            raise Forbidden("Controlled documents are created by document controllers or reviewers on the unit.")
    elif not (scope.has_function("document_controller") and scope.can_see(unit)):
        scope.require(unit, "contributor", "documents")
    classification = classification or t.default_classification
    if classification not in CLASSIFICATIONS:
        raise Invalid(f"Classification must be one of {', '.join(CLASSIFICATIONS)}.")
    if not (title or "").strip():
        raise Invalid("A document needs a title.")
    d = Document(type_id=t.id, title=title.strip()[:250], description=description, org_unit_code=unit,
                 owner=_user(db, owner) or scope.username, approver=_user(db, approver),
                 classification=classification, status="draft" if t.controlled else "active",
                 tags=sorted({x.strip().lower() for x in (tags or []) if x.strip()}) or None,
                 doc_metadata=_check_metadata(t, metadata), effective_date=effective_date,
                 number=_next_number(db, t) if t.controlled else None, revision=1, created_by=scope.username)
    if t.controlled and d.approver and d.approver == d.owner:
        raise Invalid("The approver must be someone other than the owner.")
    db.add(d)
    db.flush()
    audit.record(db, scope.username, "document.create", "document", d.id, org_unit_code=unit,
                 after={"type": t.code, "number": d.number, "title": d.title, "classification": classification})
    return d


def add_version(db: Session, scope: Scope, doc_id: int, filename: str, data: bytes,
                change_note: str | None = None) -> DocumentVersion:
    d = get(db, scope, doc_id)
    if not _may_edit(scope, d):
        raise Forbidden("Only the owner or a document controller can add files to this document.")
    t = _type(db, d.type_id)
    if t.controlled and d.status != "draft":
        raise Conflict("An approved document cannot change; start a new revision instead.")
    if d.status in ("withdrawn", "superseded"):
        raise Conflict(f"This document is {d.status}.")
    ext, mime = files.check(filename, data, t.allowed_extensions)
    name, sha, size = filestore.put(data)
    text_content, status, error = files.extract(ext, data)
    v = DocumentVersion(document_id=d.id, version=d.current_version + 1, filename=filename[-255:], extension=ext,
                        mime=mime, size=size, sha256=sha, storage_name=name, text_content=text_content,
                        extraction_status=status, extraction_error=error, change_note=change_note,
                        uploaded_by=scope.username)
    db.add(v)
    d.current_version = v.version
    db.flush()
    _index(db, d, v)
    audit.record(db, scope.username, "document.version", "document", d.id, org_unit_code=d.org_unit_code,
                 after={"version": v.version, "filename": v.filename, "sha256": sha, "size": size,
                        "extraction": status}, reason=change_note)
    return v


def update(db: Session, scope: Scope, doc_id: int, data: dict) -> Document:
    d = get(db, scope, doc_id)
    if not _may_edit(scope, d):
        raise Forbidden("Only the owner or a document controller can edit this document.")
    t = _type(db, d.type_id)
    if t.controlled and d.status not in ("draft",):
        editable = {"review_date", "tags", "description"}
        if set(data) - editable:
            raise Conflict("Only the review date, tags and description can change after approval.")
    fields = ("title", "description", "owner", "approver", "classification", "tags", "doc_metadata",
              "effective_date", "review_date")
    before = audit.snapshot(d, fields)
    for k, v in data.items():
        if k == "classification" and v not in CLASSIFICATIONS:
            raise Invalid(f"Classification must be one of {', '.join(CLASSIFICATIONS)}.")
        if k in ("owner", "approver"):
            v = _user(db, v)
        if k == "tags":
            v = sorted({x.strip().lower() for x in (v or []) if x.strip()}) or None
        if k == "metadata":
            k, v = "doc_metadata", _check_metadata(t, v)
        setattr(d, k, v)
    if t.controlled and d.approver and d.approver == d.owner:
        raise Invalid("The approver must be someone other than the owner.")
    b, a = audit.changed(before, audit.snapshot(d, fields))
    if a:
        audit.record(db, scope.username, "document.update", "document", d.id, before=b, after=a,
                     org_unit_code=d.org_unit_code)
    return d


def transition(db: Session, scope: Scope, doc_id: int, name: str, reason: str | None = None) -> Document:
    d = get(db, scope, doc_id)
    t = _type(db, d.type_id)
    FLOW.check(d, name, reason)
    if scope.read_only:
        raise Forbidden("Your account is read-only.")
    controller = scope.has_function("document_controller")
    if name == "approve":
        if not t.controlled:
            raise Invalid("Only controlled documents are approved.")
        if not d.current_version:
            raise Invalid("Upload the document before approving it.")
        last = db.query(DocumentVersion).filter_by(document_id=d.id, version=d.current_version).one()
        if scope.username in (d.owner, last.uploaded_by):
            raise Forbidden("A document must be approved by someone other than its owner and last uploader.")
        if not (controller or scope.username == d.approver):
            raise Forbidden("Only the named approver or a document controller can approve.")
        d.approved_by, d.approved_at, d.approved_version = scope.username, datetime.utcnow(), d.current_version
    elif name == "make_effective":
        if not (controller or d.owner == scope.username):
            raise Forbidden("The owner or a document controller makes a document effective.")
        d.effective_date = d.effective_date or date.today()
        if t.review_interval_months and not d.review_date:
            d.review_date = _add_months(d.effective_date, t.review_interval_months)
        prev = db.get(Document, d.supersedes_id) if d.supersedes_id else None
        if prev is not None and prev.status == "effective":
            FLOW.apply(db, prev, "supersede", scope.username, org_unit_code=prev.org_unit_code,
                       extra_after={"superseded_by": d.id, "revision": d.revision})
    elif name == "withdraw":
        if not (controller or d.owner == scope.username):
            raise Forbidden("The owner or a document controller withdraws a document.")
    FLOW.apply(db, d, name, scope.username, reason=reason, org_unit_code=d.org_unit_code,
               step=name if name == "approve" else None, decision="approved" if name == "approve" else None,
               extra_after={"version": d.current_version, "effective_date": d.effective_date,
                            "review_date": d.review_date} if name in ("approve", "make_effective") else None)
    return d


def revise(db: Session, scope: Scope, doc_id: int) -> Document:
    d = get(db, scope, doc_id)
    t = _type(db, d.type_id)
    if not t.controlled or d.status != "effective":
        raise Conflict("Only an effective controlled document can be revised.")
    if not (scope.has_function("document_controller") or d.owner == scope.username) or scope.read_only:
        raise Forbidden("The owner or a document controller starts a revision.")
    if db.query(Document.id).filter(Document.supersedes_id == d.id, Document.status.in_(("draft", "approved"))).first():
        raise Conflict("A revision of this document is already in progress.")
    n = Document(type_id=d.type_id, number=d.number, revision=d.revision + 1, title=d.title, description=d.description,
                 org_unit_code=d.org_unit_code, owner=d.owner, approver=d.approver, classification=d.classification,
                 status="draft", tags=d.tags, doc_metadata=d.doc_metadata, supersedes_id=d.id,
                 created_by=scope.username)
    db.add(n)
    db.flush()
    links.add_link(db, scope, "document", n.id, "document", d.id, relation="supersedes", role="viewer")
    audit.record(db, scope.username, "document.revise", "document", n.id, org_unit_code=n.org_unit_code,
                 after={"number": n.number, "revision": n.revision, "supersedes": d.id})
    return n


def _add_months(d: date, months: int) -> date:
    import calendar
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


# ── evidence ────────────────────────────────────────────────────────────────

def attach_evidence(db: Session, scope: Scope, entity_type: str, entity_id, filename: str, data: bytes,
                    title: str | None = None, document_id: int | None = None, note: str | None = None) -> tuple[Document, DocumentVersion]:
    """File evidence for a record; pins the link to the exact version uploaded."""
    obj, et = entities.load(db, scope, entity_type, entity_id, role="contributor")
    unit = et.unit_of(obj) or "org"
    ensure_types(db)
    if document_id:
        d = get(db, scope, document_id)
        existing = db.query(EntityLink.id).filter_by(from_type=entity_type, from_id=str(entity_id),
                                                     to_type="document", to_id=str(d.id), relation="evidence").first()
        if not existing:
            raise Invalid("That document is not evidence for this record; attach a new file instead.")
    else:
        t = db.query(DocumentType).filter_by(code="evidence").one()
        d = create(db, scope, type_id=t.id, title=title or filename, org_unit_code=unit,
                   description=f"Evidence for {et.label.lower()} {et.title_of(obj)}")
    v = add_version(db, scope, d.id, filename, data, note)
    links.add_link(db, scope, entity_type, entity_id, "document", d.id, relation="evidence", to_version=v.version,
                   note=note, role="contributor")
    return d, v


# ── search ──────────────────────────────────────────────────────────────────

def _index(db: Session, d: Document, v: DocumentVersion) -> None:
    if db.get_bind().dialect.name != "sqlite":
        return   # PostgreSQL searches document_versions.text_content with to_tsvector at query time
    db.execute(text("INSERT INTO document_fts(version_id, document_id, title, body) VALUES (:v, :d, :t, :b)"),
               {"v": v.id, "d": d.id, "t": d.title, "b": v.text_content or ""})


def _fts_query(q: str) -> str:
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in q).split() if w][:12]
    return " ".join(f'"{w}"*' for w in words)


def search(db: Session, scope: Scope, q: str, limit: int = 50) -> list[dict]:
    q = (q or "").strip()
    if len(q) < 2:
        raise Invalid("Search for at least two characters.")
    rows: list[tuple[int, int, str]] = []
    if db.get_bind().dialect.name == "sqlite":
        match = _fts_query(q)
        if not match:
            return []
        found = db.execute(text("SELECT document_id, version_id, snippet(document_fts, 3, '[', ']', ' … ', 12) "
                                "FROM document_fts WHERE document_fts MATCH :m ORDER BY rank LIMIT 500"),
                           {"m": match}).fetchall()
        rows = [(r[0], r[1], r[2]) for r in found]
    else:
        found = db.execute(text("SELECT document_id, id, ts_headline('simple', coalesce(text_content,''), "
                                "plainto_tsquery('simple', :q)) FROM document_versions WHERE "
                                "to_tsvector('simple', coalesce(text_content,'')) @@ plainto_tsquery('simple', :q) "
                                "LIMIT 500"), {"q": q}).fetchall()
        rows = [(r[0], r[1], r[2]) for r in found]
    out, seen = [], set()
    title_hits = db.query(Document).filter(Document.title.ilike(f"%{q}%")).limit(200).all()
    for d in title_hits:
        rows.insert(0, (d.id, None, ""))
    for doc_id, version_id, snippet in rows:
        if doc_id in seen:
            continue
        d = db.get(Document, doc_id)
        if d is None or not can_view(scope, d):
            continue   # never reveal a snippet from a document the reader cannot open
        seen.add(doc_id)
        v = db.get(DocumentVersion, version_id) if version_id else None
        out.append({**document_dict(db, d, scope), "match_version": v.version if v else None, "snippet": snippet})
        if len(out) >= limit:
            break
    return out


# ── read models ─────────────────────────────────────────────────────────────

def version_dict(v: DocumentVersion) -> dict:
    return {"id": v.id, "version": v.version, "filename": v.filename, "extension": v.extension, "mime": v.mime,
            "size": v.size, "sha256": v.sha256, "extraction_status": v.extraction_status,
            "extraction_error": v.extraction_error, "change_note": v.change_note, "uploaded_by": v.uploaded_by,
            "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None}


def document_dict(db: Session, d: Document, scope: Scope, full: bool = False) -> dict:
    t = db.get(DocumentType, d.type_id)
    today = date.today()
    out = {"id": d.id, "type": {"id": t.id, "code": t.code, "name": t.name, "controlled": t.controlled},
           "number": d.number, "revision": d.revision, "title": d.title, "description": d.description,
           "org_unit_code": d.org_unit_code, "owner": d.owner, "approver": d.approver,
           "classification": d.classification, "status": d.status, "tags": d.tags or [],
           "metadata": d.doc_metadata or {}, "effective_date": d.effective_date.isoformat() if d.effective_date else None,
           "review_date": d.review_date.isoformat() if d.review_date else None,
           "review_overdue": bool(d.review_date and d.review_date < today and d.status == "effective"),
           "current_version": d.current_version, "approved_version": d.approved_version,
           "approved_by": d.approved_by, "supersedes_id": d.supersedes_id,
           "can_edit": _may_edit(scope, d) and d.status in ("draft", "active"),
           "allowed": [n for n in FLOW.allowed(d.status) if n != "supersede" and not scope.read_only and (
               (n == "approve" and t.controlled and (scope.has_function("document_controller") or scope.username == d.approver)
                and scope.username != d.owner)
               or (n in ("make_effective", "withdraw") and (scope.has_function("document_controller") or d.owner == scope.username)))],
           "can_revise": t.controlled and d.status == "effective" and not scope.read_only and (
               scope.has_function("document_controller") or d.owner == scope.username)}
    if full:
        out["versions"] = [version_dict(v) for v in db.query(DocumentVersion).filter_by(document_id=d.id)
                           .order_by(DocumentVersion.version.desc())]
        out["approvals"] = approval_history(db, "document", d.id)
        out["evidence_for"] = [{"type": l.from_type, "id": l.from_id, "version": l.to_version, "note": l.note}
                               for l in db.query(EntityLink).filter_by(to_type="document", to_id=str(d.id),
                                                                       relation="evidence")
                               if entities.visible(db, scope, l.from_type, l.from_id)]
    return out


def download(db: Session, scope: Scope, doc_id: int, version: int | None = None) -> tuple[bytes, DocumentVersion]:
    d = get(db, scope, doc_id)
    v = db.query(DocumentVersion).filter_by(document_id=d.id, version=version or d.current_version).first()
    if v is None:
        raise NotFound("That version does not exist.")
    data = filestore.get(v.storage_name, v.sha256)
    audit.record(db, scope.username, "document.download", "document", d.id, org_unit_code=d.org_unit_code,
                 after={"version": v.version, "sha256": v.sha256[:16]})
    return data, v


def query(db: Session, scope: Scope, *, type_code: str | None = None, controlled: bool | None = None,
          status: str | None = None, tag: str | None = None) -> list[Document]:
    q = scope.filter(db.query(Document), Document.org_unit_code)
    if type_code or controlled is not None:
        q = q.join(DocumentType, DocumentType.id == Document.type_id)
        if type_code:
            q = q.filter(DocumentType.code == type_code)
        if controlled is not None:
            q = q.filter(DocumentType.controlled.is_(controlled))
    if status:
        q = q.filter(Document.status == status)
    rows = [d for d in q.order_by(Document.number.is_(None), Document.number, Document.revision.desc(), Document.id.desc())
            .limit(2000) if can_view(scope, d)]
    if tag:
        rows = [d for d in rows if tag.lower() in (d.tags or [])]
    return rows


# ── review reminders ────────────────────────────────────────────────────────

def _review_reminders(db: Session, today: date) -> int:
    sent = 0
    for d in db.query(Document).filter(Document.status == "effective", Document.review_date.isnot(None)):
        if d.review_date < today:
            sent += notify(db, d.owner, "document_review_overdue", f"Review overdue: {d.number} {d.title}",
                           body=f"Review was due {d.review_date.isoformat()}.", entity_type="document", entity_id=d.id,
                           dedupe_key=f"document:{d.id}:review_overdue:{today.isoformat()}")
        elif d.review_date <= today + timedelta(days=30):
            sent += notify(db, d.owner, "document_review_due", f"Review due {d.review_date.isoformat()}: {d.number}",
                           body=d.title, entity_type="document", entity_id=d.id,
                           dedupe_key=f"document:{d.id}:review:{d.review_date.isoformat()}")
    return sent


REMINDER_PRODUCERS.append(_review_reminders)
