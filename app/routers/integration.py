"""
routers/integration.py — Data sources, catalogue, targets and the strategic position.

Admin (require admin):
  GET/POST        /api/integration/sources                 list / create a source
  PUT/DELETE      /api/integration/sources/{code}          update / disable a source
  POST            /api/integration/sources/{code}/run      pull now
  POST            /api/integration/sources/{code}/upload   run a CSV/Excel report through the source's mapping
  POST            /api/integration/sources/{code}/token    issue a push token (shown once)
  PUT             /api/integration/sources/{code}/key-mappings   upsert crosswalk rows
  GET             /api/integration/runs                    run history (with rejected rows)
  GET/POST        /api/integration/org-units               hierarchy
  GET/POST        /api/integration/metrics                 catalogue
  POST            /api/integration/targets                 upsert targets
  POST            /api/integration/bootstrap-legacy        seed tree, metrics, legacy source from records

Any authenticated user:
  GET /api/position/{metric}?org_unit=&period_type=&start=&end=   where we were / are / are going
  GET /api/position?org_unit=                                      every active measure, current vs target
  GET /api/position/{metric}/reconciliation?org_unit=              sources that disagree
  GET /api/position/sources/freshness                              is the data current?
  GET /api/position/org-units                                      units for the scorecard picker

Machine (push token, no user session):
  POST /api/ingest/{code}   header X-Madzi-Ingest-Token, body {"rows": [...]}
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.core.config import settings
from app.database import get_db
from app.integration import connectors, formulas, pipeline
from app.integration import position as pos
from app.integration.models import (
    AGGREGATIONS, CONNECTORS, DIRECTIONS, PERIOD_TYPES, SYSTEM_TYPES,
    DataSource, KeyMapping, Metric, MetricTarget, OrgUnit, SyncRun,
)
from app.services.audit_log import log_event as write_audit_log

admin_router = APIRouter(prefix="/api/integration", tags=["Integration"])
position_router = APIRouter(prefix="/api/position", tags=["Strategic Position"])
ingest_router = APIRouter(prefix="/api/ingest", tags=["Ingest"])

MAX_PUSH_ROWS = 50_000


# ── schemas ─────────────────────────────────────────────────────────────────

def _one_of(allowed):
    def check(v):
        if v is not None and v not in allowed:
            raise ValueError(f"must be one of {', '.join(allowed)}")
        return v
    return check


class SourceIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,59}$")
    name: str
    system_type: str = "other"
    connector: str
    config: dict[str, Any] = {}
    mapping: dict[str, Any] = {}
    priority: int = 100
    enabled: bool = True
    owner: Optional[str] = None
    schedule_minutes: Optional[int] = Field(default=None, ge=5)

    _st = field_validator("system_type")(_one_of(SYSTEM_TYPES))
    _cn = field_validator("connector")(_one_of(CONNECTORS))


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    system_type: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    mapping: Optional[dict[str, Any]] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    owner: Optional[str] = None
    schedule_minutes: Optional[int] = Field(default=None, ge=5)
    reset_watermark: bool = False

    _st = field_validator("system_type")(_one_of(SYSTEM_TYPES))


class OrgUnitIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.\-]{0,79}$")
    name: str
    unit_type: str = "unit"
    parent_code: Optional[str] = None
    is_active: bool = True


class MetricIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,79}$")
    name: str
    unit: Optional[str] = None
    category: Optional[str] = None
    aggregation: str = "sum"
    direction: str = "higher"
    # e.g. "nrw / vol_produced * 100"; computed, never loaded. Set aggregation to "avg" for
    # ratios (comparable year to date); the "sum" default treats the result as accumulating.
    formula: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

    _ag = field_validator("aggregation")(_one_of(AGGREGATIONS))
    _dr = field_validator("direction")(_one_of(DIRECTIONS))


class TargetIn(BaseModel):
    metric_code: str
    org_unit_code: str = "org"
    period_type: str = "year"
    period_start: date
    value: float
    lower: Optional[float] = None
    upper: Optional[float] = None
    basis: str = "strategic_plan"
    note: Optional[str] = None

    _pt = field_validator("period_type")(_one_of(PERIOD_TYPES))


class KeyMappingIn(BaseModel):
    kind: str
    external_key: str
    internal_code: str

    _k = field_validator("kind")(_one_of(("org_unit", "metric")))


# ── helpers ─────────────────────────────────────────────────────────────────

def _source(db: Session, code: str) -> DataSource:
    s = db.query(DataSource).filter_by(code=code).first()
    if s is None:
        raise HTTPException(404, f"Unknown source '{code}'.")
    return s


def _source_dict(s: DataSource) -> dict:
    return {
        "code": s.code, "name": s.name, "system_type": s.system_type, "connector": s.connector,
        "config": s.config, "mapping": s.mapping, "priority": s.priority, "enabled": s.enabled,
        "owner": s.owner, "schedule_minutes": s.schedule_minutes, "watermark": s.watermark,
        "has_ingest_token": bool(s.ingest_token_hash),
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
    }


def _run_dict(r: SyncRun, include_rejects: bool = False) -> dict:
    d = {
        "id": r.id, "status": r.status, "triggered_by": r.triggered_by,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "rows_read": r.rows_read, "values_loaded": r.values_loaded, "rows_rejected": r.rows_rejected,
        "watermark_before": r.watermark_before, "watermark_after": r.watermark_after, "error": r.error,
    }
    if include_rejects:
        d["rejects"] = r.rejects or []
    return d


def _run(db: Session, source: DataSource, who: str, rows=None) -> dict:
    try:
        run = pipeline.run_sync(db, source, triggered_by=who, rows=rows)
    except pipeline.SyncBusy as exc:
        raise HTTPException(409, str(exc))
    return _run_dict(run, include_rejects=True)


# ── sources ─────────────────────────────────────────────────────────────────

@admin_router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    return [_source_dict(s) for s in db.query(DataSource).order_by(DataSource.priority, DataSource.code)]


@admin_router.post("/sources", status_code=201)
def create_source(body: SourceIn, db: Session = Depends(get_db), user=Depends(require_admin)):
    if db.query(DataSource).filter_by(code=body.code).first():
        raise HTTPException(409, f"Source '{body.code}' already exists.")
    s = DataSource(**body.model_dump())
    db.add(s)
    db.commit()
    write_audit_log(db, user.username, "integration_source_create", body.code)
    return _source_dict(s)


@admin_router.put("/sources/{code}")
def update_source(code: str, body: SourceUpdate, db: Session = Depends(get_db), user=Depends(require_admin)):
    s = _source(db, code)
    data = body.model_dump(exclude_unset=True)
    if data.pop("reset_watermark", False):
        s.watermark = None
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    write_audit_log(db, user.username, "integration_source_update", code)
    return _source_dict(s)


@admin_router.delete("/sources/{code}")
def disable_source(code: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Disables rather than deletes: loaded values keep their lineage."""
    s = _source(db, code)
    s.enabled = False
    db.commit()
    write_audit_log(db, user.username, "integration_source_disable", code)
    return {"code": code, "enabled": False}


@admin_router.post("/sources/{code}/run")
def run_source(code: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    s = _source(db, code)
    if not s.enabled:
        raise HTTPException(409, "Source is disabled.")
    return _run(db, s, user.username)


@admin_router.post("/sources/{code}/upload")
async def upload_to_source(code: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                           user=Depends(require_admin)):
    s = _source(db, code)
    content = await file.read()
    if len(content) > settings.upload_limit_mb * 1024 * 1024:
        raise HTTPException(413, "File too large.")
    try:
        rows = connectors.read_tabular(file.filename or "upload.csv", content,
                                       (s.config or {}).get("sheet"), int((s.config or {}).get("header_row", 1)))
    except connectors.ConnectorError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(400, "Could not read the file. Use .csv or .xlsx.")
    return _run(db, s, user.username, rows=rows)


@admin_router.post("/sources/{code}/token")
def issue_token(code: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    s = _source(db, code)
    if s.connector != "push":
        raise HTTPException(400, "Tokens are only for push sources.")
    token = pipeline.issue_ingest_token(s)
    db.commit()
    write_audit_log(db, user.username, "integration_token_issue", code)
    return {"code": code, "token": token, "note": "Store this now; it is not shown again. Issuing a new token revokes this one."}


@admin_router.get("/sources/{code}/key-mappings")
def list_key_mappings(code: str, db: Session = Depends(get_db)):
    s = _source(db, code)
    return [{"kind": k.kind, "external_key": k.external_key, "internal_code": k.internal_code}
            for k in db.query(KeyMapping).filter_by(source_id=s.id).order_by(KeyMapping.kind, KeyMapping.external_key)]


@admin_router.put("/sources/{code}/key-mappings")
def upsert_key_mappings(code: str, body: list[KeyMappingIn], db: Session = Depends(get_db),
                        user=Depends(require_admin)):
    s = _source(db, code)
    existing = {(k.kind, k.external_key): k for k in db.query(KeyMapping).filter_by(source_id=s.id)}
    for m in body:
        row = existing.get((m.kind, m.external_key))
        if row is None:
            db.add(KeyMapping(source_id=s.id, **m.model_dump()))
        else:
            row.internal_code = m.internal_code
    db.commit()
    write_audit_log(db, user.username, "integration_key_mappings", f"{code}: {len(body)} rows")
    return {"code": code, "upserted": len(body)}


@admin_router.get("/runs")
def list_runs(source: Optional[str] = None, limit: int = Query(50, le=500), include_rejects: bool = False,
              db: Session = Depends(get_db)):
    q = db.query(SyncRun)
    if source:
        q = q.filter(SyncRun.source_id == _source(db, source).id)
    names = {s.id: s.code for s in db.query(DataSource)}
    return [{"source": names.get(r.source_id), **_run_dict(r, include_rejects)}
            for r in q.order_by(SyncRun.id.desc()).limit(limit)]


# ── catalogue and hierarchy ─────────────────────────────────────────────────

@admin_router.get("/org-units")
def list_org_units(db: Session = Depends(get_db)):
    units = db.query(OrgUnit).order_by(OrgUnit.code).all()
    by_id = {u.id: u.code for u in units}
    return [{"code": u.code, "name": u.name, "unit_type": u.unit_type, "parent_code": by_id.get(u.parent_id),
             "is_active": u.is_active} for u in units]


@admin_router.post("/org-units")
def upsert_org_units(body: list[OrgUnitIn], db: Session = Depends(get_db), user=Depends(require_admin)):
    """Upsert in order, so a parent listed earlier in the same request can be referenced."""
    for item in body:
        parent_id = None
        if item.parent_code:
            parent = db.query(OrgUnit).filter_by(code=item.parent_code).first()
            if parent is None:
                raise HTTPException(400, f"Unknown parent '{item.parent_code}' for '{item.code}'.")
            parent_id = parent.id
        row = db.query(OrgUnit).filter_by(code=item.code).first()
        if row is None:
            row = OrgUnit(code=item.code)
            db.add(row)
        if parent_id is not None and item.parent_code in {item.code, *pos.descendants(db, item.code)}:
            raise HTTPException(400, f"'{item.parent_code}' cannot be the parent of '{item.code}' (cycle).")
        row.name, row.unit_type, row.parent_id, row.is_active = item.name, item.unit_type, parent_id, item.is_active
        db.flush()
    db.commit()
    write_audit_log(db, user.username, "integration_org_units", f"{len(body)} rows")
    return {"upserted": len(body)}


@admin_router.get("/metrics")
def list_metrics(db: Session = Depends(get_db)):
    return [{"code": m.code, "name": m.name, "unit": m.unit, "category": m.category, "aggregation": m.aggregation,
             "direction": m.direction, "formula": m.formula, "description": m.description,
             "is_active": m.is_active}
            for m in db.query(Metric).order_by(Metric.category, Metric.code)]


@admin_router.post("/metrics")
def upsert_metrics(body: list[MetricIn], db: Session = Depends(get_db), user=Depends(require_admin)):
    # Validate every formula against the catalogue as it will be after this request,
    # so a batch can define components and the ratios that use them together.
    current = {m.code: m.formula for m in db.query(Metric)}
    for item in body:
        current[item.code] = (item.formula or "").strip() or None
    try:
        formulas.check_catalogue({c: f for c, f in current.items() if f}, current.keys())
    except formulas.FormulaError as exc:
        raise HTTPException(400, f"Invalid formula: {exc}")
    for item in body:
        item.formula = current[item.code]
        row = db.query(Metric).filter_by(code=item.code).first()
        if row is None:
            db.add(Metric(**item.model_dump()))
        else:
            for k, v in item.model_dump().items():
                setattr(row, k, v)
    db.commit()
    write_audit_log(db, user.username, "integration_metrics", f"{len(body)} rows")
    return {"upserted": len(body)}


@admin_router.post("/targets")
def upsert_targets(body: list[TargetIn], db: Session = Depends(get_db), user=Depends(require_admin)):
    metrics = {c for (c,) in db.query(Metric.code)}
    units = {c for (c,) in db.query(OrgUnit.code)}
    for t in body:
        if t.metric_code not in metrics:
            raise HTTPException(400, f"Unknown metric '{t.metric_code}'.")
        if t.org_unit_code not in units:
            raise HTTPException(400, f"Unknown org unit '{t.org_unit_code}'.")
        key = dict(metric_code=t.metric_code, org_unit_code=t.org_unit_code, period_type=t.period_type,
                   period_start=t.period_start, basis=t.basis)
        row = db.query(MetricTarget).filter_by(**key).first() or MetricTarget(**key)
        row.value, row.lower, row.upper, row.note = t.value, t.lower, t.upper, t.note
        db.add(row)
    db.commit()
    write_audit_log(db, user.username, "integration_targets", f"{len(body)} rows")
    return {"upserted": len(body)}


@admin_router.post("/bootstrap-legacy")
def bootstrap_legacy(db: Session = Depends(get_db), user=Depends(require_admin)):
    created = pipeline.bootstrap_legacy(db)
    write_audit_log(db, user.username, "integration_bootstrap_legacy", str(created))
    return created


# ── strategic position (any signed-in user) ─────────────────────────────────

@position_router.get("/org-units")
def position_org_units(db: Session = Depends(get_db)):
    """Active units for the scorecard's unit picker (read-only, any signed-in user)."""
    units = db.query(OrgUnit).filter(OrgUnit.is_active.is_(True)).order_by(OrgUnit.code).all()
    by_id = {u.id: u.code for u in units}
    return [{"code": u.code, "name": u.name, "unit_type": u.unit_type, "parent_code": by_id.get(u.parent_id)}
            for u in units]


@position_router.get("/sources/freshness")
def sources_freshness(db: Session = Depends(get_db)):
    return pos.freshness(db)


@position_router.get("")
def overview(org_unit: str = "org", period_type: str = "month", db: Session = Depends(get_db)):
    if period_type not in PERIOD_TYPES:
        raise HTTPException(400, "Invalid period_type.")
    out = []
    for m in db.query(Metric).filter(Metric.is_active.is_(True)).order_by(Metric.category, Metric.code):
        p = pos.position(db, m, org_unit, period_type)
        out.append({"metric": p["metric"], "category": m.category, "where_we_are": p["where_we_are"],
                    "gap_to_target": p["gap_to_target"], "trend": p["trend"], "rolled_up": p["rolled_up"], "derived": p["derived"],
                    "next_target": (p["where_we_are_going"] or [None])[0]})
    return {"org_unit": org_unit, "period_type": period_type, "measures": out}


@position_router.get("/{metric_code}")
def metric_position(metric_code: str, org_unit: str = "org", period_type: str = "month",
                    start: Optional[date] = None, end: Optional[date] = None, db: Session = Depends(get_db)):
    m = db.query(Metric).filter_by(code=metric_code).first()
    if m is None:
        raise HTTPException(404, f"Unknown metric '{metric_code}'.")
    if period_type not in PERIOD_TYPES:
        raise HTTPException(400, "Invalid period_type.")
    return pos.position(db, m, org_unit, period_type, start, end)


@position_router.get("/{metric_code}/reconciliation")
def metric_reconciliation(metric_code: str, org_unit: str = "org", period_type: str = "month",
                          db: Session = Depends(get_db)):
    return pos.reconciliation(db, metric_code, org_unit, period_type)


# ── push ingest (machine token) ─────────────────────────────────────────────

@ingest_router.post("/{code}")
def ingest(code: str, body: dict = Body(...), x_madzi_ingest_token: Optional[str] = Header(default=None),
           db: Session = Depends(get_db)):
    s = db.query(DataSource).filter_by(code=code).first()
    # Same answer for unknown source and bad token, so the endpoint does not reveal source codes.
    if s is None or s.connector != "push" or not pipeline.check_ingest_token(s, x_madzi_ingest_token):
        raise HTTPException(401, "Invalid source or token.")
    if not s.enabled:
        raise HTTPException(409, "Source is disabled.")
    rows = body.get("rows")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise HTTPException(400, 'Body must be {"rows": [{...}, ...]}.')
    if len(rows) > MAX_PUSH_ROWS:
        raise HTTPException(413, f"At most {MAX_PUSH_ROWS} rows per request.")
    for i, r in enumerate(rows, start=1):
        r.setdefault("_source_ref", f"push#{i}")
    return _run(db, s, f"push:{code}", rows=rows)
