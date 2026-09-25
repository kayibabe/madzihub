"""
Governance and risk rules.

Meetings and resolutions (board secretary duty)
    meeting: scheduled → held → minutes_approved (needs the minutes document)
    resolution: open ──implement (owner, note)──► implemented ──close (secretary, not owner)──► closed
                open ──cancel (reason)──► cancelled;  implemented/closed ──reopen (reason)──► open
    A resolution with an owner creates an owned, dated action.

Audit findings: auditor and management roles are kept apart
    open ──respond (management)──► response_submitted ──accept (auditor)──► agreed
                                   └─reject_response (auditor, reason)──► open
    agreed ──request_closure (management, note)──► closure_requested ──validate (auditor)──► closed
                                                   └─reject_closure (auditor, reason)──► agreed
    closed ──reopen (auditor, reason)──► agreed
    Only auditors (duty) raise findings, rate them and validate closure; only management
    (the owner, or an approver on the unit) responds and asks for closure. An auditor can
    never write the management response, and management can never close a finding.
    Accepting a response creates the follow-up action for the owner.

Risk register (risk manager duty for criteria)
    Each organisation defines its own matrix: likelihood and impact scales of any size (2–10
    levels), score bands and their appetite. Nothing assumes a 5×5 grid. Ratings are kept as an
    append-only assessment history; treatments are actions; objectives are linked records.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.governance.models import (
    AuditFinding, Meeting, Resolution, Risk, RiskAssessment, RiskControl, RiskMatrix,
)
from app.platform import actions as platform_actions
from app.platform import audit, entities
from app.platform.errors import Conflict, Forbidden, Invalid, NotFound
from app.platform.models import Action
from app.platform.notifications import REMINDER_PRODUCERS, notify
from app.platform.scope import ROOT_ORG, Scope, check_unit
from app.platform.workflow import Transition, Workflow, approval_history

FINDING_RATINGS = ("critical", "high", "medium", "low")
FINDING_SOURCES = ("internal_audit", "external_audit", "regulator", "other")
APPETITES = ("within", "tolerance", "outside")

MEETING_FLOW = Workflow("meeting", ("scheduled", "held", "minutes_approved"), [
    Transition("hold", ("scheduled",), "held"),
    Transition("approve_minutes", ("held",), "minutes_approved"),
])
RESOLUTION_FLOW = Workflow("resolution", ("open", "implemented", "closed", "cancelled"), [
    Transition("implement", ("open",), "implemented", reason_required=True),
    Transition("close", ("implemented",), "closed"),
    Transition("reopen", ("implemented", "closed"), "open", reason_required=True),
    Transition("cancel", ("open",), "cancelled", reason_required=True),
])
FINDING_FLOW = Workflow("audit_finding", ("open", "response_submitted", "agreed", "closure_requested", "closed"), [
    Transition("respond", ("open",), "response_submitted"),
    Transition("accept", ("response_submitted",), "agreed"),
    Transition("reject_response", ("response_submitted",), "open", reason_required=True),
    Transition("request_closure", ("agreed",), "closure_requested", reason_required=True),
    Transition("validate", ("closure_requested",), "closed"),
    Transition("reject_closure", ("closure_requested",), "agreed", reason_required=True),
    Transition("reopen", ("closed",), "agreed", reason_required=True),
])
RISK_FLOW = Workflow("risk", ("open", "closed"), [
    Transition("close", ("open",), "closed", reason_required=True),
    Transition("reopen", ("closed",), "open", reason_required=True),
])

for key, label, model, title, page in (
        ("meeting", "Meeting", Meeting, lambda m: f"{m.body}: {m.title}", "meetings"),
        ("resolution", "Resolution", Resolution, lambda r: f"{r.number}", "meetings"),
        ("audit_finding", "Audit finding", AuditFinding, lambda f: f"{f.ref} {f.title}", "audit-findings"),
        ("risk", "Risk", Risk, lambda r: f"{r.code} {r.title}", "risks")):
    entities.register(entities.EntityType(key=key, label=label, model=model, unit_of=lambda o: o.org_unit_code,
                                          title_of=title, page=page))


def _user(db: Session, username: str | None) -> str | None:
    if not username:
        return None
    from app.database import User
    if not db.query(User.id).filter(User.username == username, User.is_active.is_(True)).first():
        raise Invalid(f"Unknown or inactive user '{username}'.")
    return username


def _next(db: Session, model, column, prefix: str, width: int = 4) -> str:
    vals = [v for (v,) in db.query(column).filter(column.like(f"{prefix}%"))]
    seq = max([int(v[len(prefix):]) for v in vals if v[len(prefix):].isdigit()] or [0]) + 1
    return f"{prefix}{seq:0{width}d}"


# ── meetings and resolutions ────────────────────────────────────────────────

def create_meeting(db: Session, scope: Scope, *, body: str, title: str, meeting_date: date,
                   org_unit_code: str = ROOT_ORG, secretary: str | None = None) -> Meeting:
    scope.require_function("board_secretary")
    unit = check_unit(db, org_unit_code)
    scope.require_see(unit)
    if not (body or "").strip() or not (title or "").strip():
        raise Invalid("A meeting needs a body (e.g. Board) and a title.")
    m = Meeting(body=body.strip()[:80], title=title.strip()[:200], meeting_date=meeting_date, org_unit_code=unit,
                secretary=_user(db, secretary) or scope.username, created_by=scope.username)
    db.add(m)
    db.flush()
    audit.record(db, scope.username, "meeting.create", "meeting", m.id, org_unit_code=unit,
                 after={"body": m.body, "title": m.title, "date": meeting_date})
    return m


def transition_meeting(db: Session, scope: Scope, meeting_id: int, name: str, minutes_document_id: int | None = None) -> Meeting:
    scope.require_function("board_secretary")
    m, _ = entities.load(db, scope, "meeting", meeting_id)
    if name == "approve_minutes":
        doc_id = minutes_document_id or m.minutes_document_id
        if not doc_id:
            raise Invalid("Attach the minutes document before approving the minutes.")
        entities.load(db, scope, "document", doc_id)
        m.minutes_document_id = doc_id
    MEETING_FLOW.apply(db, m, name, scope.username, org_unit_code=m.org_unit_code,
                       extra_after={"minutes_document_id": m.minutes_document_id} if name == "approve_minutes" else None)
    return m


def add_resolution(db: Session, scope: Scope, meeting_id: int, *, text: str, owner: str | None = None,
                   due_date: date | None = None, org_unit_code: str | None = None, number: str | None = None) -> Resolution:
    scope.require_function("board_secretary")
    m, _ = entities.load(db, scope, "meeting", meeting_id)
    if m.status == "scheduled":
        raise Conflict("Record resolutions once the meeting has been held.")
    if not (text or "").strip():
        raise Invalid("A resolution needs its text.")
    unit = check_unit(db, org_unit_code or m.org_unit_code)
    prefix = f"{''.join(w[0] for w in m.body.split()).upper()[:4]}/{m.meeting_date.year}/"
    number = (number or "").strip() or _next(db, Resolution, Resolution.number, prefix, 3)
    if db.query(Resolution.id).filter_by(number=number).first():
        raise Conflict(f"Resolution number {number} is already used.")
    r = Resolution(meeting_id=m.id, number=number, text=text.strip(), owner=_user(db, owner), due_date=due_date,
                   org_unit_code=unit, status="open", created_by=scope.username)
    db.add(r)
    db.flush()
    if r.owner:
        a = platform_actions.create(db, scope, title=f"Resolution {r.number}: {r.text[:140]}", owner=r.owner,
                                    org_unit_code=unit, due_date=due_date, description=r.text,
                                    source_type="resolution", source_id=r.id, check_role=False)
        r.action_id = a.id
    audit.record(db, scope.username, "resolution.create", "resolution", r.id, org_unit_code=unit,
                 after={"number": r.number, "owner": r.owner, "due_date": due_date, "action_id": r.action_id})
    return r


def transition_resolution(db: Session, scope: Scope, res_id: int, name: str, reason: str | None = None) -> Resolution:
    r, _ = entities.load(db, scope, "resolution", res_id)
    RESOLUTION_FLOW.check(r, name, reason)
    secretary = scope.has_function("board_secretary") and not scope.read_only
    if name == "implement":
        if not (secretary or (r.owner == scope.username and not scope.read_only)):
            raise Forbidden("The resolution's owner or the board secretary reports implementation.")
        r.implementation_note = reason
    elif name == "close":
        if not secretary:
            raise Forbidden("The board secretary closes a resolution.")
        if r.owner == scope.username:
            raise Forbidden("The owner cannot close their own resolution.")
    elif not secretary:
        raise Forbidden("This needs the board secretary duty.")
    RESOLUTION_FLOW.apply(db, r, name, scope.username, reason=reason, org_unit_code=r.org_unit_code)
    return r


# ── audit findings ──────────────────────────────────────────────────────────

AUDITOR_FIELDS = ("audit_name", "source", "title", "description", "recommendation", "rating", "owner")


def _management(scope: Scope, f: AuditFinding) -> None:
    # The auditor duty must be granted explicitly (administrators do not hold it implicitly here),
    # and a person holding it never acts for management.
    if "auditor" in scope.functions:
        raise Forbidden("Auditors cannot act for management on a finding.")
    if scope.read_only or not (f.owner == scope.username or scope.can(f.org_unit_code, "approver")):
        raise Forbidden("Only the finding's owner or an approver on the unit responds for management.")


def create_finding(db: Session, scope: Scope, data: dict) -> AuditFinding:
    if "auditor" not in scope.functions or scope.read_only:
        raise Forbidden("Only auditors (auditor duty, on an account that can make changes) raise audit findings.")
    unit = check_unit(db, data.get("org_unit_code") or ROOT_ORG)
    scope.require_see(unit)
    rating = data.get("rating")
    if rating not in FINDING_RATINGS:
        raise Invalid(f"Rating must be one of {', '.join(FINDING_RATINGS)}.")
    if data.get("source", "internal_audit") not in FINDING_SOURCES:
        raise Invalid(f"Source must be one of {', '.join(FINDING_SOURCES)}.")
    owner = _user(db, data.get("owner"))
    if not owner or owner == scope.username:
        raise Invalid("Name a management owner other than yourself.")
    if not (data.get("title") or "").strip() or not (data.get("audit_name") or "").strip():
        raise Invalid("A finding needs the audit's name and a title.")
    f = AuditFinding(ref=_next(db, AuditFinding, AuditFinding.ref, f"AF-{date.today().year}-", 3),
                     audit_name=data["audit_name"].strip(), source=data.get("source") or "internal_audit",
                     title=data["title"].strip()[:250], description=data.get("description"),
                     recommendation=data.get("recommendation"), rating=rating, org_unit_code=unit,
                     auditor=scope.username, owner=owner, status="open")
    db.add(f)
    db.flush()
    audit.record(db, scope.username, "audit_finding.create", "audit_finding", f.id, org_unit_code=unit,
                 after={k: getattr(f, k) for k in ("ref", "title", "rating", "owner")})
    notify(db, owner, "finding_raised", f"Audit finding for your response: {f.ref} {f.title}",
           entity_type="audit_finding", entity_id=f.id)
    return f


def update_finding(db: Session, scope: Scope, finding_id: int, data: dict) -> AuditFinding:
    f, _ = entities.load(db, scope, "audit_finding", finding_id)
    if "auditor" not in scope.functions or scope.read_only:
        raise Forbidden("Only auditors edit a finding's rating, description and recommendation.")
    if f.status == "closed":
        raise Conflict("A closed finding cannot be edited; reopen it with a reason.")
    unknown = set(data) - set(AUDITOR_FIELDS)
    if unknown:
        raise Forbidden(f"Auditors cannot edit {', '.join(sorted(unknown))}.")
    if "rating" in data and data["rating"] not in FINDING_RATINGS:
        raise Invalid(f"Rating must be one of {', '.join(FINDING_RATINGS)}.")
    before = audit.snapshot(f, AUDITOR_FIELDS)
    for k, v in data.items():
        setattr(f, k, _user(db, v) if k == "owner" else v)
    b, a = audit.changed(before, audit.snapshot(f, AUDITOR_FIELDS))
    if a:
        audit.record(db, scope.username, "audit_finding.update", "audit_finding", f.id, before=b, after=a,
                     org_unit_code=f.org_unit_code)
    return f


def transition_finding(db: Session, scope: Scope, finding_id: int, name: str, *, reason: str | None = None,
                       response: str | None = None, agreed_due_date: date | None = None) -> AuditFinding:
    f, _ = entities.load(db, scope, "audit_finding", finding_id)
    FINDING_FLOW.check(f, name, reason)
    if name in ("respond", "request_closure"):
        _management(scope, f)
        if name == "respond":
            if not (response or "").strip() or not agreed_due_date:
                raise Invalid("A management response needs the response and the date it will be implemented by.")
            f.management_response, f.agreed_due_date = response.strip(), agreed_due_date
            f.responded_by, f.responded_at = scope.username, datetime.utcnow()
        else:
            f.closure_note = reason
    else:
        if "auditor" not in scope.functions or scope.read_only:
            raise Forbidden("Only auditors accept responses and validate closure.")
        if scope.username == f.owner:
            raise Forbidden("The finding's owner cannot also validate it.")
        if name == "validate":
            open_actions = db.query(Action).filter(Action.source_type == "audit_finding", Action.source_id == str(f.id),
                                                   Action.status.in_(("open", "in_progress"))).count()
            if open_actions:
                raise Conflict(f"{open_actions} follow-up action(s) are still open.")
            f.validated_by, f.validated_at = scope.username, datetime.utcnow()
    FINDING_FLOW.apply(db, f, name, scope.username, reason=reason or response, org_unit_code=f.org_unit_code,
                       step=name, decision={"accept": "approved", "validate": "approved", "reject_response": "returned",
                                            "reject_closure": "returned"}.get(name, name))
    if name == "accept":
        platform_actions.create(db, scope, title=f"Audit {f.ref}: {f.title[:150]}", owner=f.owner,
                                org_unit_code=f.org_unit_code, due_date=f.agreed_due_date,
                                description=f"Recommendation: {f.recommendation or '-'}\n\nAgreed response: {f.management_response}",
                                source_type="audit_finding", source_id=f.id, check_role=False)
    notify_to = f.auditor if name in ("respond", "request_closure") else f.owner
    notify(db, notify_to, f"finding_{name}", f"{f.ref}: {name.replace('_', ' ')}", body=reason,
           entity_type="audit_finding", entity_id=f.id)
    return f


def finding_dict(db: Session, f: AuditFinding, scope: Scope, full: bool = False) -> dict:
    auditor = "auditor" in scope.functions and scope.username != f.owner and not scope.read_only
    management = not scope.read_only and not ("auditor" in scope.functions) and (
        f.owner == scope.username or scope.can(f.org_unit_code, "approver"))
    allowed = [t for t in FINDING_FLOW.allowed(f.status)
               if (t in ("respond", "request_closure") and management) or
               (t not in ("respond", "request_closure") and auditor)]
    today = date.today()
    d = {k: getattr(f, k) for k in ("id", "ref", "audit_name", "source", "title", "description", "recommendation",
                                    "rating", "org_unit_code", "auditor", "owner", "status", "management_response",
                                    "responded_by", "closure_note", "validated_by")}
    d.update(agreed_due_date=f.agreed_due_date.isoformat() if f.agreed_due_date else None,
             overdue=bool(f.agreed_due_date and f.agreed_due_date < today and f.status in ("agreed",)),
             allowed=allowed, can_edit=auditor and f.status != "closed",
             created_at=f.created_at.isoformat() if f.created_at else None)
    if full:
        d["actions"] = [platform_actions.action_dict(a, scope) for a in
                        platform_actions.query(db, scope, source_type="audit_finding", source_id=str(f.id))]
        d["decisions"] = approval_history(db, "audit_finding", f.id)
    return d


# ── risk criteria ───────────────────────────────────────────────────────────

def matrix_template(size_l: int, size_i: int) -> dict:
    """An example to start from; the organisation edits labels and bands before activating it."""
    top = size_l * size_i
    cut1, cut2, cut3 = max(1, round(top * 0.2)), max(2, round(top * 0.4)), max(3, round(top * 0.64))
    return {"name": f"{size_l}×{size_i} matrix (edit before use)",
            "likelihood_levels": [{"value": v, "label": f"Likelihood {v}"} for v in range(1, size_l + 1)],
            "impact_levels": [{"value": v, "label": f"Impact {v}"} for v in range(1, size_i + 1)],
            "bands": [{"min": 1, "max": cut1, "label": "Low", "appetite": "within"},
                      {"min": cut1 + 1, "max": cut2, "label": "Moderate", "appetite": "within"},
                      {"min": cut2 + 1, "max": cut3, "label": "High", "appetite": "tolerance"},
                      {"min": cut3 + 1, "max": top, "label": "Very high", "appetite": "outside"}]}


def _validate_matrix(data: dict) -> None:
    for key in ("likelihood_levels", "impact_levels"):
        levels = data.get(key) or []
        if not 2 <= len(levels) <= 10:
            raise Invalid("Each scale needs between 2 and 10 levels.")
        if [lv.get("value") for lv in levels] != list(range(1, len(levels) + 1)):
            raise Invalid("Scale levels are numbered 1, 2, 3 … in order.")
        if any(not str(lv.get("label", "")).strip() for lv in levels):
            raise Invalid("Every level needs a label.")
    top = len(data["likelihood_levels"]) * len(data["impact_levels"])
    bands = sorted(data.get("bands") or [], key=lambda b: b.get("min", 0))
    if not bands or bands[0].get("min") != 1 or bands[-1].get("max") != top:
        raise Invalid(f"Bands must run from a score of 1 to {top} (likelihood × impact).")
    for a, b in zip(bands, bands[1:]):
        if a.get("max") is None or a["max"] + 1 != b.get("min"):
            raise Invalid(f"Band '{a.get('label')}' must end just before '{b.get('label')}' starts.")
    for b in bands:
        if b.get("appetite") not in APPETITES or not str(b.get("label", "")).strip() or b["max"] < b["min"]:
            raise Invalid("Each band needs a label, a valid range and an appetite (within, tolerance or outside).")


def save_matrix(db: Session, scope: Scope, data: dict, matrix_id: int | None = None) -> RiskMatrix:
    scope.require_function("risk_manager")
    _validate_matrix(data)
    if matrix_id:
        m = db.get(RiskMatrix, matrix_id)
        if m is None:
            raise NotFound("Risk matrix not found.")
        if db.query(Risk.id).filter_by(matrix_id=m.id).first():
            raise Conflict("Risks are rated on this matrix; create a new matrix instead of changing it.")
    else:
        m = RiskMatrix(created_by=scope.username, active=False)
        db.add(m)
    m.name = (data.get("name") or "Risk matrix").strip()[:120]
    m.likelihood_levels, m.impact_levels, m.bands = data["likelihood_levels"], data["impact_levels"], data["bands"]
    db.flush()
    audit.record(db, scope.username, "risk_matrix.save", "risk_matrix", m.id,
                 after={"name": m.name, "size": f"{len(m.likelihood_levels)}x{len(m.impact_levels)}", "bands": m.bands})
    return m


def activate_matrix(db: Session, scope: Scope, matrix_id: int) -> RiskMatrix:
    scope.require_function("risk_manager")
    m = db.get(RiskMatrix, matrix_id)
    if m is None:
        raise NotFound("Risk matrix not found.")
    for other in db.query(RiskMatrix).filter(RiskMatrix.active.is_(True), RiskMatrix.id != m.id):
        other.active = False
    m.active, m.approved_by, m.approved_at = True, scope.username, datetime.utcnow()
    db.flush()   # sessions do not autoflush: later queries in this transaction must see the new active matrix
    audit.record(db, scope.username, "risk_matrix.activate", "risk_matrix", m.id, after={"active": True})
    return m


def active_matrix(db: Session) -> RiskMatrix | None:
    return db.query(RiskMatrix).filter_by(active=True).first()


def band_for(m: RiskMatrix, likelihood: int | None, impact: int | None) -> dict | None:
    if likelihood is None or impact is None:
        return None
    score = likelihood * impact
    b = next((b for b in m.bands if b["min"] <= score <= b["max"]), None)
    return {"score": score, "label": b["label"] if b else None, "appetite": b["appetite"] if b else None}


# ── risks ───────────────────────────────────────────────────────────────────

RISK_FIELDS = ("title", "description", "category", "cause", "consequence", "owner", "org_unit_code", "review_date")


def create_risk(db: Session, scope: Scope, data: dict) -> Risk:
    unit = check_unit(db, data.get("org_unit_code") or ROOT_ORG)
    scope.require(unit, "contributor", "the risk register")
    m = active_matrix(db)
    if m is None:
        raise Conflict("No risk criteria are active yet. A risk manager sets up and activates the organisation's "
                       "risk matrix first.")
    if not (data.get("title") or "").strip():
        raise Invalid("A risk needs a title.")
    r = Risk(code=_next(db, Risk, Risk.code, "RSK-", 3), title=data["title"].strip()[:250],
             description=data.get("description"), category=data.get("category"), cause=data.get("cause"),
             consequence=data.get("consequence"), owner=_user(db, data.get("owner")) or scope.username,
             org_unit_code=unit, matrix_id=m.id, status="open", review_date=data.get("review_date"),
             created_by=scope.username)
    db.add(r)
    db.flush()
    audit.record(db, scope.username, "risk.create", "risk", r.id, org_unit_code=unit,
                 after={k: getattr(r, k) for k in ("code", "title", "owner", "category")})
    for kind in ("inherent", "residual"):
        if data.get(f"{kind}_l") is not None and data.get(f"{kind}_i") is not None:
            assess(db, scope, r.id, kind, data[f"{kind}_l"], data[f"{kind}_i"], "Initial rating")
    return r


def _may_edit_risk(scope: Scope, r: Risk) -> bool:
    return not scope.read_only and (r.owner == scope.username or scope.has_function("risk_manager")
                                    or scope.can(r.org_unit_code, "reviewer"))


def update_risk(db: Session, scope: Scope, risk_id: int, data: dict) -> Risk:
    r, _ = entities.load(db, scope, "risk", risk_id)
    if not _may_edit_risk(scope, r):
        raise Forbidden("The risk owner, a reviewer on the unit or a risk manager edits a risk.")
    before = audit.snapshot(r, RISK_FIELDS)
    for k, v in data.items():
        if k not in RISK_FIELDS:
            raise Invalid(f"Cannot edit {k}.")
        if k == "owner":
            v = _user(db, v)
        if k == "org_unit_code":
            v = check_unit(db, v)
            scope.require(v, "contributor", "the risk register")
        setattr(r, k, v)
    b, a = audit.changed(before, audit.snapshot(r, RISK_FIELDS))
    if a:
        audit.record(db, scope.username, "risk.update", "risk", r.id, before=b, after=a, org_unit_code=r.org_unit_code)
    return r


def assess(db: Session, scope: Scope, risk_id: int, kind: str, likelihood: int, impact: int,
           note: str | None = None) -> RiskAssessment:
    r, _ = entities.load(db, scope, "risk", risk_id)
    if not _may_edit_risk(scope, r):
        raise Forbidden("The risk owner, a reviewer on the unit or a risk manager rates a risk.")
    if r.status != "open":
        raise Conflict("Reopen the risk before re-rating it.")
    if kind not in ("inherent", "residual"):
        raise Invalid("Kind is inherent or residual.")
    m = db.get(RiskMatrix, r.matrix_id)
    if not (1 <= int(likelihood) <= len(m.likelihood_levels) and 1 <= int(impact) <= len(m.impact_levels)):
        raise Invalid(f"Likelihood is 1–{len(m.likelihood_levels)} and impact 1–{len(m.impact_levels)} on this matrix.")
    band = band_for(m, int(likelihood), int(impact))
    a = RiskAssessment(risk_id=r.id, kind=kind, likelihood=int(likelihood), impact=int(impact), score=band["score"],
                       band=band["label"], note=note, assessed_by=scope.username)
    db.add(a)
    before = {"likelihood": getattr(r, f"{kind}_l"), "impact": getattr(r, f"{kind}_i")}
    setattr(r, f"{kind}_l", int(likelihood))
    setattr(r, f"{kind}_i", int(impact))
    audit.record(db, scope.username, f"risk.assess_{kind}", "risk", r.id, before=before,
                 after={"likelihood": int(likelihood), "impact": int(impact), "score": band["score"], "band": band["label"]},
                 reason=note, org_unit_code=r.org_unit_code)
    return a


def transition_risk(db: Session, scope: Scope, risk_id: int, name: str, reason: str | None = None) -> Risk:
    r, _ = entities.load(db, scope, "risk", risk_id)
    if not (scope.has_function("risk_manager") or scope.can(r.org_unit_code, "approver")) or scope.read_only:
        raise Forbidden("A risk manager or an approver on the unit closes and reopens risks.")
    RISK_FLOW.apply(db, r, name, scope.username, reason=reason, org_unit_code=r.org_unit_code)
    return r


def add_control(db: Session, scope: Scope, risk_id: int, data: dict, control_id: int | None = None) -> RiskControl:
    r, _ = entities.load(db, scope, "risk", risk_id)
    if not _may_edit_risk(scope, r):
        raise Forbidden("The risk owner, a reviewer on the unit or a risk manager records controls.")
    if data.get("control_type", "preventive") not in ("preventive", "detective", "corrective"):
        raise Invalid("Control type is preventive, detective or corrective.")
    if data.get("effectiveness", "not_tested") not in ("effective", "partly", "ineffective", "not_tested"):
        raise Invalid("Effectiveness is effective, partly, ineffective or not_tested.")
    if control_id:
        c = db.get(RiskControl, control_id)
        if c is None or c.risk_id != r.id:
            raise NotFound("Control not found.")
        before = audit.snapshot(c, ("description", "control_type", "owner", "effectiveness", "last_tested", "retired"))
    else:
        if not (data.get("description") or "").strip():
            raise Invalid("Describe the control.")
        c = RiskControl(risk_id=r.id)
        db.add(c)
        before = None
    for k in ("description", "control_type", "effectiveness", "last_tested", "retired"):
        if k in data and data[k] is not None:
            setattr(c, k, data[k])
    if "owner" in data:
        c.owner = _user(db, data["owner"])
    db.flush()
    audit.record(db, scope.username, "risk.control", "risk", r.id, before=before,
                 after=audit.snapshot(c, ("id", "description", "control_type", "owner", "effectiveness", "last_tested",
                                          "retired")), org_unit_code=r.org_unit_code)
    return c


def risk_dict(db: Session, r: Risk, scope: Scope, full: bool = False) -> dict:
    m = db.get(RiskMatrix, r.matrix_id)
    d = {k: getattr(r, k) for k in ("id", "code", "title", "description", "category", "cause", "consequence", "owner",
                                    "org_unit_code", "status", "inherent_l", "inherent_i", "residual_l", "residual_i")}
    d.update(review_date=r.review_date.isoformat() if r.review_date else None,
             review_overdue=bool(r.review_date and r.review_date < date.today() and r.status == "open"),
             inherent=band_for(m, r.inherent_l, r.inherent_i), residual=band_for(m, r.residual_l, r.residual_i),
             can_edit=_may_edit_risk(scope, r) and r.status == "open",
             can_close=not scope.read_only and (scope.has_function("risk_manager") or scope.can(r.org_unit_code, "approver")))
    d["residual_above_inherent"] = bool(d["inherent"] and d["residual"] and d["residual"]["score"] > d["inherent"]["score"])
    if full:
        d["controls"] = [{"id": c.id, "description": c.description, "control_type": c.control_type, "owner": c.owner,
                          "effectiveness": c.effectiveness, "retired": c.retired,
                          "last_tested": c.last_tested.isoformat() if c.last_tested else None}
                         for c in db.query(RiskControl).filter_by(risk_id=r.id).order_by(RiskControl.id)]
        d["assessments"] = [{"kind": a.kind, "likelihood": a.likelihood, "impact": a.impact, "score": a.score,
                             "band": a.band, "note": a.note, "assessed_by": a.assessed_by,
                             "assessed_at": a.assessed_at.isoformat() if a.assessed_at else None}
                            for a in db.query(RiskAssessment).filter_by(risk_id=r.id).order_by(RiskAssessment.id.desc())]
        d["treatments"] = [platform_actions.action_dict(a, scope) for a in
                           platform_actions.query(db, scope, source_type="risk", source_id=str(r.id))]
        d["matrix"] = matrix_dict(m)
    return d


def matrix_dict(m: RiskMatrix) -> dict:
    return {"id": m.id, "name": m.name, "likelihood_levels": m.likelihood_levels, "impact_levels": m.impact_levels,
            "bands": m.bands, "active": m.active, "approved_by": m.approved_by, "created_by": m.created_by}


def heatmap(db: Session, scope: Scope, kind: str = "residual") -> dict:
    m = active_matrix(db)
    if m is None:
        return {"matrix": None, "cells": []}
    q = scope.filter(db.query(Risk), Risk.org_unit_code).filter(Risk.status == "open", Risk.matrix_id == m.id)
    cells: dict[tuple[int, int], list[str]] = {}
    for r in q:
        l, i = (r.residual_l, r.residual_i) if kind == "residual" else (r.inherent_l, r.inherent_i)
        if l and i:
            cells.setdefault((l, i), []).append(r.code)
    return {"matrix": matrix_dict(m), "kind": kind,
            "cells": [{"likelihood": l, "impact": i, "count": len(codes), "risks": codes, **band_for(m, l, i)}
                      for (l, i), codes in sorted(cells.items())]}


# ── reminders and report section ────────────────────────────────────────────

def _governance_reminders(db: Session, today: date) -> int:
    sent = 0
    for r in db.query(Risk).filter(Risk.status == "open", Risk.review_date.isnot(None)):
        if r.review_date < today:
            sent += notify(db, r.owner, "risk_review_overdue", f"Risk review overdue: {r.code} {r.title}",
                           entity_type="risk", entity_id=r.id, dedupe_key=f"risk:{r.id}:overdue:{today.isoformat()}")
        elif r.review_date <= today + timedelta(days=14):
            sent += notify(db, r.owner, "risk_review_due", f"Risk review due {r.review_date.isoformat()}: {r.code}",
                           entity_type="risk", entity_id=r.id, dedupe_key=f"risk:{r.id}:due:{r.review_date.isoformat()}")
    for f in db.query(AuditFinding).filter(AuditFinding.status == "open"):
        if f.created_at and f.created_at.date() < today - timedelta(days=30):
            sent += notify(db, f.owner, "finding_response_overdue", f"Management response overdue: {f.ref}",
                           entity_type="audit_finding", entity_id=f.id,
                           dedupe_key=f"finding:{f.id}:response:{today.isoformat()}")
    return sent


REMINDER_PRODUCERS.append(_governance_reminders)


def risks_section(db: Session, scope: Scope, ctx: dict):
    if ctx["kind"] not in ("board_pack", "exceptions"):
        return None
    m = active_matrix(db)
    rows = []
    for r in db.query(Risk).filter(Risk.status == "open", Risk.org_unit_code.in_(sorted(ctx["units"]) or [""])):
        if not scope.can_see(r.org_unit_code):
            continue
        mm = db.get(RiskMatrix, r.matrix_id)
        res, inh = band_for(mm, r.residual_l, r.residual_i), band_for(mm, r.inherent_l, r.inherent_i)
        if ctx["kind"] == "exceptions" and not (res and res["appetite"] == "outside"):
            continue
        rows.append({"code": r.code, "title": f"{r.code} {r.title}", "owner": r.owner,
                     "inherent": f"{inh['score']} {inh['label']}" if inh else None,
                     "residual": f"{res['score']} {res['label']}" if res else None,
                     "appetite": (res or {}).get("appetite"), "score": (res or {}).get("score") or 0,
                     "review_date": r.review_date.isoformat() if r.review_date else None})
    rows.sort(key=lambda x: -x["score"])
    return ("risks", rows[:15]) if m is not None or rows else ("risks", [])
