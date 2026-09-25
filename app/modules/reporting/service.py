"""
Reporting rules.

    draft ──submit──► in_review ──approve──► approved ──publish──► published
      ▲                  │ return (reason)       └──────withdraw (reason)──► withdrawn
      └──────────────────┘

- Report managers (duty) or reviewers on the unit create reports. The data is *frozen*
  (captured from governed sources) while in draft; it can be re-frozen until submitted.
- Approval needs the approver role on the unit (or the report manager duty) and a
  different person from the author. Board packs and scorecard reports need an approved
  score snapshot. Approval fixes a content fingerprint over data + commentary + template.
- Outputs of approved/published reports are rendered once per format, stored, hashed and
  served from storage after an integrity check; drafts are rendered on the fly and marked.
- Every create, freeze, decision, preview and download is written to the access log.
- Nothing is sent outside the app: distribution is by download only in this release.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.reporting import builders, layout, render
from app.modules.reporting.models import (
    AUDIENCES, FORMATS, REPORT_KINDS, ReportAccessLog, ReportInstance, ReportOutput, ReportTemplate,
)
from app.modules.scorecard import engine
from app.modules.scorecard.service import score_gap
from app.platform import audit, entities, filestore, periods
from app.platform.errors import Conflict, Forbidden, Invalid, NotFound
from app.platform.scope import Scope, check_unit
from app.platform.workflow import Transition, Workflow, approval_history

FLOW = Workflow("report_instance", ("draft", "in_review", "approved", "published", "withdrawn"), [
    Transition("submit", ("draft",), "in_review"),
    Transition("return", ("in_review",), "draft", reason_required=True),
    Transition("approve", ("in_review",), "approved"),
    Transition("publish", ("approved",), "published"),
    Transition("withdraw", ("approved", "published"), "withdrawn", reason_required=True),
])

BUILT_IN = [
    ("board-pack", "Board performance pack", "board_pack", "board",
     "Strategy status, trend, variance commentary, principal risks, decisions required and overdue actions."),
    ("scorecard-detail", "Scorecard and indicator detail", "scorecard_detail", "management",
     "Every item and indicator with actual, target, achievement, rating and completeness."),
    ("submission-dq", "Submissions and data quality", "submission_dq", "management",
     "Completeness of the period's submissions and every data-quality finding."),
    ("exceptions", "Exception report", "exceptions", "management",
     "Missed targets, missing submissions and evidence, stale sources, overdue actions."),
]
NEEDS_APPROVED_SCORE = ("board_pack", "scorecard_detail")


def can_view(scope: Scope, inst: ReportInstance) -> bool:
    if not scope.can_see(inst.org_unit_code):
        return False
    if inst.status in ("approved", "published"):
        return True
    return inst.created_by == scope.username or scope.has_function("report_manager") or \
        scope.can(inst.org_unit_code, "reviewer")


entities.register(entities.EntityType(
    key="report_instance", label="Report", model=ReportInstance, unit_of=lambda r: r.org_unit_code,
    title_of=lambda r: f"#{r.id} {r.title}", can_view=can_view, page="reports-hub",
    versions_of=lambda db, r: set(range(1, (r.data_version or 0) + 1))))


def ensure_templates(db: Session) -> None:
    have = {c for (c,) in db.query(ReportTemplate.code)}
    for code, name, kind, audience, desc in BUILT_IN:
        if code not in have:
            db.add(ReportTemplate(code=code, version=1, name=name, kind=kind, audience=audience, description=desc,
                                  config={"commentary": [k for k, _ in layout.COMMENTARY_SECTIONS[kind]]},
                                  created_by="system"))
    db.flush()


def log(db: Session, inst: ReportInstance, action: str, actor: str, output_id: int | None = None,
        detail: str | None = None) -> None:
    db.add(ReportAccessLog(instance_id=inst.id, output_id=output_id, action=action, actor=actor,
                           detail=(detail or "")[:300] or None))


def _get(db: Session, scope: Scope, inst_id: int) -> ReportInstance:
    inst, _ = entities.load(db, scope, "report_instance", inst_id)
    return inst


def _manager_or_author(scope: Scope, inst: ReportInstance) -> None:
    if scope.read_only or not (inst.created_by == scope.username or scope.has_function("report_manager")):
        raise Forbidden("Only the report's author or a report manager can do that.")


def create(db: Session, scope: Scope, *, template_id: int, period_id: int, org_unit_code: str,
           plan_id: int | None = None, title: str | None = None, audience: str | None = None) -> ReportInstance:
    tpl = db.get(ReportTemplate, template_id)
    if tpl is None or not tpl.active:
        raise NotFound("Report template not found.")
    unit = check_unit(db, org_unit_code)
    scope.require_see(unit, "Organisational unit")
    if scope.read_only or not (scope.has_function("report_manager") or scope.can(unit, "reviewer")):
        raise Forbidden("Creating a report needs the report manager duty or the reviewer role on the unit.")
    period = periods.get(db, period_id)
    if tpl.kind in NEEDS_APPROVED_SCORE and not plan_id:
        raise Invalid("This report needs a plan.")
    if plan_id:
        entities.load(db, scope, "plan", plan_id)
    audience = audience or tpl.audience
    if audience not in AUDIENCES:
        raise Invalid(f"Audience must be one of {', '.join(AUDIENCES)}.")
    from app.platform.scope import unit_names
    inst = ReportInstance(template_id=tpl.id, template_version=tpl.version, plan_id=plan_id, period_id=period.id,
                          org_unit_code=unit, audience=audience, status="draft", commentary={},
                          title=(title or f"{tpl.name} — {unit_names(db).get(unit, unit)} — {period.label}")[:200],
                          created_by=scope.username)
    db.add(inst)
    db.flush()
    log(db, inst, "created", scope.username)
    audit.record(db, scope.username, "report_instance.create", "report_instance", inst.id, org_unit_code=unit,
                 after={"template": f"{tpl.code} v{tpl.version}", "period": period.label, "audience": audience})
    freeze(db, scope, inst.id)
    return inst


def freeze(db: Session, scope: Scope, inst_id: int) -> ReportInstance:
    inst = _get(db, scope, inst_id)
    _manager_or_author(scope, inst)
    if inst.status != "draft":
        raise Conflict("Data can only be refreshed while the report is a draft.")
    tpl = db.get(ReportTemplate, inst.template_id)
    period = periods.get(db, inst.period_id)
    data = builders.freeze(db, scope, tpl.kind, inst.plan_id, period, inst.org_unit_code)
    inst.data = data
    inst.data_hash = engine.inputs_hash(data)
    inst.data_version = (inst.data_version or 0) + 1
    inst.frozen_at = datetime.utcnow()
    score = data.get("score") or {}
    inst.score_snapshot_ids = [score["source"]["snapshot_id"]] if score.get("source", {}).get("snapshot_id") else []
    log(db, inst, "frozen", scope.username, detail=f"data version {inst.data_version}, fingerprint {inst.data_hash[:16]}")
    audit.record(db, scope.username, "report_instance.freeze", "report_instance", inst.id,
                 org_unit_code=inst.org_unit_code, after={"data_version": inst.data_version, "data_hash": inst.data_hash})
    return inst


def set_commentary(db: Session, scope: Scope, inst_id: int, commentary: dict) -> ReportInstance:
    inst = _get(db, scope, inst_id)
    _manager_or_author(scope, inst)
    if inst.status != "draft":
        raise Conflict("Commentary can only change while the report is a draft.")
    tpl = db.get(ReportTemplate, inst.template_id)
    allowed = {k for k, _ in layout.COMMENTARY_SECTIONS[tpl.kind]}
    unknown = set(commentary) - allowed
    if unknown:
        raise Invalid(f"Unknown commentary sections: {', '.join(sorted(unknown))}.")
    before = dict(inst.commentary or {})
    merged = {**before, **{k: (v or "").strip() for k, v in commentary.items()}}
    if any(len(v) > 20000 for v in merged.values()):
        raise Invalid("Each commentary section is limited to 20,000 characters.")
    inst.commentary = merged
    b, a = audit.changed(before, merged)
    if a:
        audit.record(db, scope.username, "report_instance.commentary", "report_instance", inst.id, before=b, after=a,
                     org_unit_code=inst.org_unit_code)
    return inst


def _content_hash(inst: ReportInstance) -> str:
    return engine.inputs_hash({"data": inst.data, "commentary": inst.commentary or {},
                               "template": [inst.template_id, inst.template_version], "title": inst.title})


def transition(db: Session, scope: Scope, inst_id: int, name: str, reason: str | None = None) -> ReportInstance:
    inst = _get(db, scope, inst_id)
    FLOW.check(inst, name, reason)
    tpl = db.get(ReportTemplate, inst.template_id)
    if scope.read_only:
        raise Forbidden("Your account is read-only.")
    if name == "submit":
        _manager_or_author(scope, inst)
        if not inst.data:
            raise Invalid("Freeze the report data before submitting it.")
        inst.submitted_by = scope.username
    elif name in ("approve", "return"):
        if not (scope.can(inst.org_unit_code, "approver") or scope.has_function("report_manager")):
            raise Forbidden("Approving or returning a report needs the approver role on the unit or the report "
                            "manager duty.")
        if name == "approve":
            if scope.username in (inst.created_by, inst.submitted_by):
                raise Forbidden("A report must be approved by someone other than its author.")
            score = (inst.data or {}).get("score")
            if tpl.kind in NEEDS_APPROVED_SCORE and not (score and score["source"]["approved"]):
                raise Conflict("Approve the score snapshot for this plan, period and unit, then refresh the data, "
                               "before approving this report.")
            gap = score_gap(score["root"]) if tpl.kind in NEEDS_APPROVED_SCORE else None
            if gap:
                raise Conflict(gap)
            inst.content_hash = _content_hash(inst)
            inst.approved_by, inst.approved_at = scope.username, datetime.utcnow()
    elif name in ("publish", "withdraw"):
        if not scope.has_function("report_manager"):
            raise Forbidden("Publishing or withdrawing needs the report manager duty.")
        if name == "publish":
            inst.published_by, inst.published_at = scope.username, datetime.utcnow()
    FLOW.apply(db, inst, name, scope.username, reason=reason, org_unit_code=inst.org_unit_code, step=name,
               decision={"approve": "approved", "return": "returned", "submit": "submitted", "publish": "published",
                         "withdraw": "withdrawn"}[name],
               extra_after={"content_hash": inst.content_hash} if name == "approve" else None)
    log(db, inst, {"submit": "submitted", "return": "returned", "approve": "approved", "publish": "published",
                   "withdraw": "withdrawn"}[name], scope.username, detail=reason)
    if name == "approve":
        for fmt in FORMATS:        # render and store the approved outputs once
            _stored_output(db, inst, fmt, scope.username)
    return inst


def _meta(db: Session, inst: ReportInstance) -> dict:
    from app.core.tenant import tenant
    from app.database import OrgProfile
    tpl = db.get(ReportTemplate, inst.template_id)
    profile = db.query(OrgProfile).filter(OrgProfile.id == 1).first()
    return {"id": inst.id, "title": inst.title, "status": inst.status, "audience": inst.audience,
            "template": tpl.name, "template_version": inst.template_version, "data_version": inst.data_version,
            "data_hash": inst.data_hash or "", "content_hash": inst.content_hash,
            "approved_by": inst.approved_by, "approved_at": inst.approved_at.isoformat() if inst.approved_at else None,
            "organisation": (profile and profile.org_name) or tenant.identity.name}


def blocks(db: Session, inst: ReportInstance, status_override: str | None = None) -> list[dict]:
    meta = _meta(db, inst)
    if status_override:
        meta["status"] = status_override
    return layout.build(meta, inst.data, inst.commentary)


def _render(db: Session, inst: ReportInstance, fmt: str, status: str | None = None) -> bytes:
    meta = _meta(db, inst)
    if status:
        meta["status"] = status
    fn, _ = render.RENDERERS[fmt]
    return fn(layout.build(meta, inst.data, inst.commentary), meta)


def _stored_output(db: Session, inst: ReportInstance, fmt: str, actor: str) -> ReportOutput:
    out = db.query(ReportOutput).filter_by(instance_id=inst.id, format=fmt, content_hash=inst.content_hash).first()
    if out is not None:
        return out
    # Rendered as "approved" so a later publish does not change the stored bytes.
    data = _render(db, inst, fmt, status="approved")
    name, sha, size = filestore.put(data)
    out = ReportOutput(instance_id=inst.id, format=fmt, content_hash=inst.content_hash, sha256=sha, size=size,
                       storage_name=name, generated_by=actor)
    db.add(out)
    db.flush()
    log(db, inst, "generated", actor, output_id=out.id, detail=f"{fmt} sha256 {sha[:16]}")
    return out


def output(db: Session, scope: Scope, inst_id: int, fmt: str, download: bool) -> tuple[bytes, str, str]:
    if fmt not in FORMATS:
        raise Invalid(f"Format must be one of {', '.join(FORMATS)}.")
    inst = _get(db, scope, inst_id)
    if not inst.data:
        raise Invalid("The report has no frozen data yet.")
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in inst.title)[:80].strip() or "report"
    filename = f"{safe} (#{inst.id}).{fmt}"
    if inst.status in ("approved", "published"):
        out = _stored_output(db, inst, fmt, scope.username)
        data = filestore.get(out.storage_name, out.sha256)
        log(db, inst, "downloaded" if download else "previewed", scope.username, output_id=out.id, detail=fmt)
    else:
        data = _render(db, inst, fmt)
        log(db, inst, "previewed" if not download else "downloaded_draft", scope.username, detail=fmt)
    return data, render.RENDERERS[fmt][1], filename


def instance_dict(db: Session, inst: ReportInstance, scope: Scope, full: bool = False) -> dict:
    tpl = db.get(ReportTemplate, inst.template_id)
    period = periods.get(db, inst.period_id)
    author = inst.created_by == scope.username
    manager = scope.has_function("report_manager") and not scope.read_only
    allowed = []
    for t in FLOW.allowed(inst.status):
        if t == "submit" and (author or manager) and not scope.read_only:
            allowed.append(t)
        elif t in ("approve", "return") and not scope.read_only and (
                scope.can(inst.org_unit_code, "approver") or manager) and not (t == "approve" and scope.username in (
                inst.created_by, inst.submitted_by)):
            allowed.append(t)
        elif t in ("publish", "withdraw") and manager:
            allowed.append(t)
    d = {"id": inst.id, "title": inst.title, "template": {"id": tpl.id, "code": tpl.code, "name": tpl.name,
                                                             "kind": tpl.kind, "version": inst.template_version},
         "plan_id": inst.plan_id, "period_id": inst.period_id, "period": period.label,
         "org_unit_code": inst.org_unit_code, "audience": inst.audience, "status": inst.status,
         "data_version": inst.data_version, "data_hash": inst.data_hash, "content_hash": inst.content_hash,
         "frozen_at": inst.frozen_at.isoformat() if inst.frozen_at else None,
         "score_approved": bool(((inst.data or {}).get("score") or {}).get("source", {}).get("approved")),
         "needs_approved_score": tpl.kind in NEEDS_APPROVED_SCORE,
         "created_by": inst.created_by, "created_at": inst.created_at.isoformat() if inst.created_at else None,
         "approved_by": inst.approved_by, "approved_at": inst.approved_at.isoformat() if inst.approved_at else None,
         "published_by": inst.published_by, "published_at": inst.published_at.isoformat() if inst.published_at else None,
         "allowed": allowed, "can_edit": inst.status == "draft" and (author or manager) and not scope.read_only,
         "commentary_sections": [{"key": k, "title": t} for k, t in layout.COMMENTARY_SECTIONS[tpl.kind]],
         "commentary": inst.commentary or {}}
    if full:
        d["approvals"] = approval_history(db, "report_instance", inst.id)
        d["outputs"] = [{"id": o.id, "format": o.format, "sha256": o.sha256, "size": o.size,
                         "generated_at": o.generated_at.isoformat() if o.generated_at else None}
                        for o in db.query(ReportOutput).filter_by(instance_id=inst.id).order_by(ReportOutput.id)]
        d["access_log"] = [{"action": r.action, "actor": r.actor, "detail": r.detail,
                            "at": r.at.isoformat() if r.at else None}
                           for r in db.query(ReportAccessLog).filter_by(instance_id=inst.id)
                           .order_by(ReportAccessLog.id.desc()).limit(200)]
    return d


def visible(db: Session, scope: Scope, status: str | None = None) -> list[ReportInstance]:
    q = scope.filter(db.query(ReportInstance), ReportInstance.org_unit_code)
    if status:
        q = q.filter(ReportInstance.status == status)
    return [r for r in q.order_by(ReportInstance.id.desc()).limit(500) if can_view(scope, r)]


def fingerprint_matches(inst: ReportInstance) -> bool:
    return bool(inst.data) and engine.inputs_hash(inst.data) == inst.data_hash


def _dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)
