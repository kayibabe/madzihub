"""
Regulator packs, returns and league tables.

- Packs are imported from tenants/_packs/regulators/<regulator>/<cycle>.yaml as drafts (a new
  version each time). A regulatory officer edits a draft (every change audited with a reason)
  and marks figures verified against the cited source; a *different* regulatory officer approves
  it, and only when engine.blockers() is empty.
- Returns and league tables need an approved pack. Raw return values are append-only rows with
  their source; calculations never overwrite them. A league-table run is saved with its inputs,
  results and hashes.
- Regulatory work is organisation-level: visible to people with an organisation-wide grant or
  the regulatory officer duty; changed only by regulatory officers.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.modules.regulatory import engine
from app.modules.regulatory.models import LeagueTableRun, RegulatoryReturn, RegulatorPack, ReturnValue
from app.modules.scorecard.engine import inputs_hash
from app.platform import audit
from app.platform.errors import Conflict, Forbidden, Invalid, NotFound
from app.platform.scope import ROOT_ORG, Scope
from app.platform.workflow import approval_history

PACKS_DIR = BASE_DIR / "tenants" / "_packs" / "regulators"


def can_view(scope: Scope) -> bool:
    return scope.org_wide or "regulatory_officer" in scope.functions or scope.is_admin


def _view(scope: Scope) -> None:
    if not can_view(scope):
        raise NotFound("Not found.")


def _officer(scope: Scope) -> None:
    scope.require_function("regulatory_officer")


def available_files() -> list[dict]:
    out = []
    for p in sorted(PACKS_DIR.glob("*/*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            out.append({"file": p.relative_to(PACKS_DIR).as_posix(), "error": str(exc)[:200]})
            continue
        out.append({"file": p.relative_to(PACKS_DIR).as_posix(), "regulator": data.get("regulator"),
                    "cycle": data.get("cycle"), "title": data.get("title")})
    return out


def _check_structure(data: dict) -> None:
    for key in ("regulator", "jurisdiction", "cycle", "title", "method", "source", "groups", "indicators"):
        if not data.get(key):
            raise Invalid(f"The pack is missing '{key}'.")
    if data["method"] != "weighted_points":
        raise Invalid(f"Unsupported method '{data['method']}'.")
    if not (data["source"] or {}).get("title"):
        raise Invalid("A pack must cite its source document (source.title).")
    codes = [i.get("code") for i in data["indicators"]]
    if len(codes) != len(set(codes)) or not all(codes):
        raise Invalid("Every indicator needs a unique code.")
    for ind in data["indicators"]:
        if ind.get("polarity") not in engine.POLARITIES:
            raise Invalid(f"{ind.get('code')}: polarity must be one of {', '.join(engine.POLARITIES)}.")


def _content(data: dict) -> dict:
    return {k: data.get(k) for k in ("verification", "groups", "peer_groups", "indicators", "export_template")}


def import_pack(db: Session, scope: Scope, file: str) -> RegulatorPack:
    _officer(scope)
    path = (PACKS_DIR / file).resolve()
    if PACKS_DIR.resolve() not in path.parents or path.suffix != ".yaml" or not path.exists():
        raise NotFound("Pack file not found.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _check_structure(data)
    content = _content(data)
    latest = (db.query(RegulatorPack).filter_by(regulator=data["regulator"], cycle=data["cycle"])
              .order_by(RegulatorPack.version.desc()).first())
    src = data["source"]
    accessed = src.get("accessed")
    p = RegulatorPack(regulator=data["regulator"], jurisdiction=data["jurisdiction"], cycle=data["cycle"],
                      version=(latest.version + 1) if latest else 1, title=data["title"], method=data["method"],
                      source_title=src["title"], source_url=src.get("url"),
                      source_accessed=accessed if isinstance(accessed, date) else None,
                      content=content, content_hash=inputs_hash(content), status="draft",
                      imported_by=scope.username)
    db.add(p)
    db.flush()
    audit.record(db, scope.username, "regulator_pack.import", "regulator_pack", p.id, org_unit_code=ROOT_ORG,
                 after={"file": file, "regulator": p.regulator, "cycle": p.cycle, "version": p.version,
                        "content_hash": p.content_hash})
    return p


def get_pack(db: Session, scope: Scope, pack_id: int) -> RegulatorPack:
    _view(scope)
    p = db.get(RegulatorPack, pack_id)
    if p is None:
        raise NotFound("Pack not found.")
    return p


def update_pack(db: Session, scope: Scope, pack_id: int, content: dict, reason: str) -> RegulatorPack:
    _officer(scope)
    p = get_pack(db, scope, pack_id)
    if p.status != "draft":
        raise Conflict("Only a draft pack can be edited; import a new version to change an approved one.")
    if not (reason or "").strip():
        raise Invalid("Record why the pack changed (e.g. 'weights from Table 3.3, page 39').")
    _check_structure({"regulator": p.regulator, "jurisdiction": p.jurisdiction, "cycle": p.cycle, "title": p.title,
                      "method": p.method, "source": {"title": p.source_title}, **content})
    before = p.content_hash
    p.content = _content(content)
    p.content_hash = inputs_hash(p.content)
    audit.record(db, scope.username, "regulator_pack.edit", "regulator_pack", p.id, org_unit_code=ROOT_ORG,
                 before={"content_hash": before}, after={"content_hash": p.content_hash}, reason=reason.strip())
    return p


def _last_editor(db: Session, p: RegulatorPack) -> str:
    from app.platform.models import AuditEvent
    ev = (db.query(AuditEvent).filter(AuditEvent.entity_type == "regulator_pack", AuditEvent.entity_id == str(p.id),
                                      AuditEvent.action.in_(("regulator_pack.import", "regulator_pack.edit")))
          .order_by(AuditEvent.id.desc()).first())
    return ev.actor if ev else p.imported_by


def approve_pack(db: Session, scope: Scope, pack_id: int, note: str | None = None) -> RegulatorPack:
    _officer(scope)
    p = get_pack(db, scope, pack_id)
    if p.status != "draft":
        raise Conflict("Only a draft pack can be approved.")
    if scope.username in (p.imported_by, _last_editor(db, p)):
        raise Forbidden("A pack is approved by a regulatory officer who neither imported nor last edited it.")
    problems = engine.blockers(p.content)
    if problems:
        raise Conflict("The pack cannot be approved yet: " + " ".join(problems[:8]) +
                       (f" (and {len(problems) - 8} more)" if len(problems) > 8 else ""))
    for other in db.query(RegulatorPack).filter_by(regulator=p.regulator, cycle=p.cycle, status="approved"):
        other.status = "retired"
        audit.record(db, scope.username, "regulator_pack.retire", "regulator_pack", other.id,
                     after={"replaced_by": p.id}, org_unit_code=ROOT_ORG)
    p.status, p.approved_by, p.approved_at = "approved", scope.username, datetime.utcnow()
    from app.platform.models import ApprovalStep
    db.add(ApprovalStep(entity_type="regulator_pack", entity_id=str(p.id), step="approve", decision="approved",
                        actor=scope.username, comment=note))
    audit.record(db, scope.username, "regulator_pack.approve", "regulator_pack", p.id, org_unit_code=ROOT_ORG,
                 after={"status": "approved", "content_hash": p.content_hash}, reason=note)
    return p


def pack_dict(db: Session, p: RegulatorPack, scope: Scope, full: bool = False) -> dict:
    problems = engine.blockers(p.content)
    d = {"id": p.id, "regulator": p.regulator, "jurisdiction": p.jurisdiction, "cycle": p.cycle, "version": p.version,
         "title": p.title, "method": p.method, "source_title": p.source_title, "source_url": p.source_url,
         "source_accessed": p.source_accessed.isoformat() if p.source_accessed else None, "status": p.status,
         "content_hash": p.content_hash, "imported_by": p.imported_by, "approved_by": p.approved_by,
         "approved_at": p.approved_at.isoformat() if p.approved_at else None,
         "blockers": problems, "usable": p.status == "approved",
         "indicator_count": len(p.content.get("indicators") or []),
         "verified_count": sum(1 for i in p.content.get("indicators") or [] if i.get("verified")),
         "is_officer": "regulatory_officer" in scope.functions or scope.has_function("regulatory_officer")}
    if full:
        d["content"] = p.content
        d["decisions"] = approval_history(db, "regulator_pack", p.id)
    return d


# ── returns ─────────────────────────────────────────────────────────────────

def _usable(db: Session, scope: Scope, pack_id: int) -> RegulatorPack:
    p = get_pack(db, scope, pack_id)
    if p.status != "approved":
        raise Conflict("This pack is not approved: returns and league tables use approved packs only.")
    return p


def create_return(db: Session, scope: Scope, pack_id: int, period_label: str) -> RegulatoryReturn:
    _officer(scope)
    p = _usable(db, scope, pack_id)
    if not (period_label or "").strip():
        raise Invalid("Name the period the return covers.")
    r = RegulatoryReturn(pack_id=p.id, period_label=period_label.strip()[:40], created_by=scope.username)
    db.add(r)
    db.flush()
    audit.record(db, scope.username, "regulatory_return.create", "regulatory_return", r.id, org_unit_code=ROOT_ORG,
                 after={"pack": f"{p.regulator} {p.cycle} v{p.version}", "period": r.period_label})
    return r


def _return(db: Session, scope: Scope, return_id: int) -> tuple[RegulatoryReturn, RegulatorPack]:
    _view(scope)
    r = db.get(RegulatoryReturn, return_id)
    if r is None:
        raise NotFound("Return not found.")
    return r, db.get(RegulatorPack, r.pack_id)


def current_values(db: Session, r: RegulatoryReturn) -> dict[str, ReturnValue]:
    out: dict[str, ReturnValue] = {}
    for v in db.query(ReturnValue).filter_by(return_id=r.id).order_by(ReturnValue.id):
        out[v.indicator_code] = v
    return out


def set_value(db: Session, scope: Scope, return_id: int, code: str, value: float | None, note: str | None = None,
              source: str = "manual") -> ReturnValue:
    _officer(scope)
    r, p = _return(db, scope, return_id)
    if r.status != "draft":
        raise Conflict("A submitted return is final; create a new return for a correction.")
    ind = next((i for i in p.content["indicators"] if i["code"] == code), None)
    if ind is None:
        raise Invalid(f"'{code}' is not an indicator of this pack.")
    errors = engine.validate_value(ind, value)
    if errors:
        raise Invalid(f"{code}: " + "; ".join(errors) + ".")
    v = ReturnValue(return_id=r.id, indicator_code=code, raw_value=value, source=source[:120], note=note,
                    entered_by=scope.username)
    db.add(v)
    audit.record(db, scope.username, "regulatory_return.value", "regulatory_return", r.id, org_unit_code=ROOT_ORG,
                 after={"indicator": code, "value": value, "source": source}, reason=note)
    return v


def prefill(db: Session, scope: Scope, return_id: int, fy_end_year: int) -> int:
    """Fill values for indicators mapped to a catalogue measure, from the published annual figure."""
    from app.integration.models import Metric
    from app.integration.position import published_series
    from app.platform.periods import fiscal_year_start
    r, p = _return(db, scope, return_id)
    start = fiscal_year_start(fy_end_year)
    n = 0
    for ind in p.content["indicators"]:
        code = ind.get("madzihub_metric")
        m = db.query(Metric).filter_by(code=code).first() if code else None
        if m is None:
            continue
        series, _ = published_series(db, m, ROOT_ORG, "year", start, start)
        if series:
            set_value(db, scope, return_id, ind["code"], round(float(series[0]["value"]), 4),
                      f"From the catalogue: {m.code}, fiscal year ending {fy_end_year}", source=f"metric:{m.code}")
            n += 1
    return n


def submit_return(db: Session, scope: Scope, return_id: int) -> RegulatoryReturn:
    _officer(scope)
    r, p = _return(db, scope, return_id)
    if r.status != "draft":
        raise Conflict("Already submitted.")
    vals = current_values(db, r)
    missing = [i["code"] for i in p.content["indicators"] if i.get("in_score", True) and
               (i["code"] not in vals or vals[i["code"]].raw_value is None)]
    if missing:
        raise Invalid(f"Values missing for: {', '.join(missing)}.")
    r.status, r.submitted_by, r.submitted_at = "submitted", scope.username, datetime.utcnow()
    audit.record(db, scope.username, "regulatory_return.submit", "regulatory_return", r.id, org_unit_code=ROOT_ORG,
                 after={"values": {c: v.raw_value for c, v in vals.items()}})
    return r


def return_dict(db: Session, r: RegulatoryReturn, scope: Scope) -> dict:
    p = db.get(RegulatorPack, r.pack_id)
    vals = current_values(db, r)
    history = db.query(ReturnValue).filter_by(return_id=r.id).count()
    return {"id": r.id, "pack_id": p.id, "pack": f"{p.regulator} {p.cycle} v{p.version}", "period_label": r.period_label,
            "status": r.status, "created_by": r.created_by, "submitted_by": r.submitted_by,
            "values": [{"code": i["code"], "name": i.get("name"), "unit": i.get("unit"), "in_score": i.get("in_score", True),
                        "value": vals[i["code"]].raw_value if i["code"] in vals else None,
                        "source": vals[i["code"]].source if i["code"] in vals else None,
                        "entered_by": vals[i["code"]].entered_by if i["code"] in vals else None}
                       for i in p.content["indicators"]],
            "revisions": history}


def export_return(db: Session, scope: Scope, return_id: int) -> tuple[bytes, str]:
    r, p = _return(db, scope, return_id)
    from openpyxl import Workbook
    from openpyxl.styles import Font
    tpl = p.content.get("export_template") or {}
    wb = Workbook()
    ws = wb.active
    ws.title = (tpl.get("sheet") or "Return")[:31]
    ws.append([f"{p.regulator} {p.cycle} — {r.period_label}"])
    ws.append([f"Status: {r.status}. Raw values as entered; calculated scores are not part of this return."])
    ws.append([])
    cols = tpl.get("columns") or ["code", "name", "unit", "value", "source"]
    ws.append([c.title() for c in cols])
    for c in ws[4]:
        c.font = Font(bold=True)
    vals = current_values(db, r)
    for i in p.content["indicators"]:
        v = vals.get(i["code"])
        row = {"code": i["code"], "name": i.get("name"), "unit": i.get("unit"),
               "value": v.raw_value if v else None, "source": v.source if v else None}
        ws.append([row.get(c) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    audit.record(db, scope.username, "regulatory_return.export", "regulatory_return", r.id, org_unit_code=ROOT_ORG)
    return buf.getvalue(), f"{p.regulator}-{p.cycle}-{r.period_label}".replace("/", "-").replace(" ", "_") + ".xlsx"


# ── league tables ───────────────────────────────────────────────────────────

def run_league(db: Session, scope: Scope, pack_id: int, return_id: int | None, peers: list[dict],
               label: str | None = None) -> LeagueTableRun:
    _officer(scope)
    p = _usable(db, scope, pack_id)
    own: dict = {}
    if return_id:
        r, rp = _return(db, scope, return_id)
        if rp.id != p.id:
            raise Invalid("The return belongs to another pack.")
        own = {c: v.raw_value for c, v in current_values(db, r).items()}
    for peer in peers:
        if not (peer.get("name") or "").strip():
            raise Invalid("Every peer needs a name.")
        for code, value in (peer.get("values") or {}).items():
            ind = next((i for i in p.content["indicators"] if i["code"] == code), None)
            if ind is None:
                raise Invalid(f"Peer {peer['name']}: '{code}' is not an indicator of this pack.")
            errs = engine.validate_value(ind, value)
            if errs:
                raise Invalid(f"Peer {peer['name']}, {code}: " + "; ".join(errs) + ".")
    from app.core.tenant import tenant
    inputs = {"own": own, "peers": peers}
    results = engine.league(p.content, tenant.identity.name, own, peers)
    run = LeagueTableRun(pack_id=p.id, return_id=return_id, label=(label or f"{p.regulator} {p.cycle}")[:200],
                         inputs=inputs, results=results, inputs_hash=inputs_hash(inputs), pack_hash=p.content_hash,
                         created_by=scope.username)
    db.add(run)
    db.flush()
    audit.record(db, scope.username, "league_table.run", "regulator_pack", p.id, org_unit_code=ROOT_ORG,
                 after={"run_id": run.id, "inputs_hash": run.inputs_hash, "entities": len(results["entities"])})
    return run


def run_dict(run: LeagueTableRun) -> dict:
    return {"id": run.id, "pack_id": run.pack_id, "return_id": run.return_id, "label": run.label,
            "inputs_hash": run.inputs_hash, "pack_hash": run.pack_hash, "created_by": run.created_by,
            "created_at": run.created_at.isoformat() if run.created_at else None, "results": run.results,
            "note": "Calculated by MadziHub from an approved pack for comparison. It is not an official "
                    "regulator ranking."}


def packs_dir_exists() -> bool:
    return Path(PACKS_DIR).exists()
