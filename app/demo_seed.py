"""Seed the fictional demo tenant with people, access and governance records.

    python -m app.demo_seed            add demo users, grants and sample records (idempotent)

Only runs when MADZI_TENANT is ``demo``: it must never touch a real utility's data.
Demo accounts get random passwords, printed once; nothing here is a real person.
Each module adds its own seeding step to ``STEPS``.
"""
from __future__ import annotations

import secrets
import sys
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import model_registry as _models  # noqa: F401
from app.database import SessionLocal, User

DEMO_USERS = [
    # username, full name, account role, {unit: role}, duties
    ("planner", "Pat Planner (demo)", "user", {"org": "approver"}, ("strategy_manager", "report_manager")),
    ("north.ops", "Nia North (demo)", "user", {"north": "contributor"}, ()),
    ("north.mgr", "Noah North (demo)", "user", {"north": "reviewer"}, ()),
    ("south.mgr", "Sade South (demo)", "user", {"south": "approver"}, ()),
    ("auditor", "Ada Auditor (demo)", "user", {"org": "viewer"}, ("auditor",)),
    ("board", "Ben Board (demo)", "viewer", {"org": "viewer"}, ()),
]

STEPS: list = []


def _users(db: Session) -> dict[str, str]:
    from app.auth import hash_password
    from app.platform.models import UserFunction, UserOrgRole

    created = {}
    for username, full_name, role, grants, duties in DEMO_USERS:
        if db.query(User).filter_by(username=username).first():
            continue
        password = secrets.token_urlsafe(9)
        u = User(username=username, full_name=full_name, role=role, password_hash=hash_password(password),
                 created_by="demo_seed", must_change_password=False)
        db.add(u)
        db.flush()
        for unit, scope_role in grants.items():
            db.add(UserOrgRole(user_id=u.id, org_unit_code=unit, role=scope_role, granted_by="demo_seed"))
        for duty in duties:
            db.add(UserFunction(user_id=u.id, function=duty, granted_by="demo_seed"))
        created[username] = password
    return created


def _tree(db: Session) -> None:
    from app.integration.models import OrgUnit
    from app.platform.bootstrap import ensure_org_tree

    ensure_org_tree(db)
    db.flush()
    by_code = {u.code: u for u in db.query(OrgUnit)}
    for parent, code, name in (("north", "north.hilltop", "Hilltop"), ("north", "north.riverside", "Riverside"),
                               ("central", "central.market", "Market Town"), ("south", "south.bay", "Bay Area")):
        if code not in by_code and parent in by_code:
            db.add(OrgUnit(code=code, name=name, unit_type="service area", parent_id=by_code[parent].id))
    db.flush()


def _actions(db: Session) -> None:
    from app.platform import actions
    from app.platform.models import Action
    from app.platform.scope import resolve_scope

    if db.query(Action).count():
        return
    admin = db.query(User).filter_by(role="admin").order_by(User.id).first()
    scope = resolve_scope(db, admin)
    today = date.today()
    for title, owner, unit, due, priority in (
        ("Replace faulty bulk meter at Hilltop reservoir", "north.ops", "north.hilltop", today + timedelta(days=21), "high"),
        ("Clear backlog of new-connection quotations", "north.ops", "north", today - timedelta(days=5), "medium"),
        ("Publish the customer service charter", "south.mgr", "south", today + timedelta(days=45), "low"),
    ):
        actions.create(db, scope, title=title, owner=owner, org_unit_code=unit, due_date=due, priority=priority)


def _admin_scope(db: Session):
    from app.platform.scope import resolve_scope
    return resolve_scope(db, db.query(User).filter_by(role="admin").order_by(User.id).first())


def _as(db: Session, username: str):
    from app.platform.scope import resolve_scope
    return resolve_scope(db, db.query(User).filter_by(username=username).one())


def _strategy(db: Session) -> None:
    from app.modules.strategy import importer, service
    from app.modules.strategy.models import Plan, PlanNode
    from app.platform.models import Period

    if db.query(Plan).count():
        return
    scope = _admin_scope(db)
    out = importer.import_tenant_plan(db, scope)
    plan = db.get(Plan, out["plan_id"])
    obj = service.create_node(db, scope, plan.id, {"node_type": "objective", "code": "O1.1",
                                                   "title": "Cut water losses in every region",
                                                   "parent_id": db.query(PlanNode).filter_by(plan_id=plan.id,
                                                                                            code="P1").one().id})
    ind = service.create_indicator(db, scope, plan.id, {
        "code": "Q-NRW", "name": "Quarterly non-revenue water", "node_id": obj.id, "unit": "%",
        "polarity": "lower", "aggregation": "avg", "frequency": "quarter", "valid_min": 0, "valid_max": 100,
        "reporting_units": ["north", "south"], "owner": "north.ops", "evidence_required": True,
        "definition": "Water produced but not billed, as a share of production, for the quarter.",
        "source": "Regional water balance workbook"})
    init = service.create_node(db, scope, plan.id, {"node_type": "initiative", "code": "I-DMA",
                                                    "title": "District metered areas in Hilltop", "org_unit_code": "north.hilltop",
                                                    "owner": "north.mgr", "status": "on_track"})
    from app.platform import links
    links.add_link(db, scope, "plan_node", init.id, "plan_node", obj.id, relation="contributes_to")
    service.transition_plan(db, scope, plan.id, "activate")
    today = date.today()
    quarter = db.query(Period).filter(Period.period_type == "quarter", Period.start_date <= today,
                                      Period.end_date >= today).one()
    service.set_targets(db, scope, ind.id, [
        {"period_type": "quarter", "period_start": quarter.start_date, "value": 28, "org_unit_code": "north"},
        {"period_type": "quarter", "period_start": quarter.start_date, "value": 30, "org_unit_code": "south"}])
    cycle = service.create_cycle(db, scope, plan.id, period_id=quarter.id)
    service.generate_assignments(db, scope, cycle.id)
    service.transition_cycle(db, scope, cycle.id, "open")
    north = next(a for a in db.query(service.CycleAssignment).filter_by(cycle_id=cycle.id, org_unit_code="north"))
    service.submit_update(db, _as(db, "north.ops"), north.id, {
        "value": 31.4, "narrative": "Two bulk meters were out of service for three weeks.",
        "variance_reason": "Estimated consumption during the meter outage.",
        "corrective_action": "Meters replaced; readings back from next month.",
        "evidence_note": "Water balance workbook, sheet Q1, rows 4-18."})


def _scorecard(db: Session) -> None:
    from app.modules.scorecard import service as sc
    from app.modules.scorecard.models import ScoreSnapshot
    from app.modules.strategy import service as st
    from app.modules.strategy.models import CycleAssignment, Plan

    if db.query(ScoreSnapshot).count():
        return
    plan = db.query(Plan).filter_by(status="active").first()
    a = db.query(CycleAssignment).filter_by(org_unit_code="north", status="submitted").first()
    if plan is None or a is None:
        return
    st.review_update(db, _as(db, "north.mgr"), a.id, "verify")
    st.review_update(db, _as(db, "planner"), a.id, "approve")
    scheme = sc.ensure_default_scheme(db) or sc.pick_scheme(db, None)
    if scheme.status == "draft":
        sc.transition_scheme(db, _as(db, "planner"), scheme.id, "approve", "Demo sign-off of the proposed default")
    cycle = db.get(st.ReportingCycle, a.cycle_id)
    snap = sc.create_snapshot(db, _as(db, "planner"), plan.id, cycle.period_id, "north", scheme.id, "Demo quarter review")
    sc.approve_snapshot(db, _admin_scope(db), snap.id, "Demo approval")


def _reports(db: Session) -> None:
    from app.modules.reporting import service as rp
    from app.modules.reporting.models import ReportInstance, ReportTemplate
    from app.modules.scorecard.models import ScoreSnapshot

    snap = db.query(ScoreSnapshot).filter_by(status="approved").first()
    if db.query(ReportInstance).count() or snap is None:
        return
    rp.ensure_templates(db)
    tpl = db.query(ReportTemplate).filter_by(code="board-pack").one()
    planner = _as(db, "planner")
    inst = rp.create(db, planner, template_id=tpl.id, period_id=snap.period_id, org_unit_code="north",
                     plan_id=snap.plan_id, audience="board")
    rp.set_commentary(db, planner, inst.id, {
        "summary": "North is below target on water losses after a three-week bulk-meter outage; meters are replaced.",
        "decisions": "Note the corrective action; no decision is required this quarter."})
    rp.transition(db, planner, inst.id, "submit")
    rp.transition(db, _admin_scope(db), inst.id, "approve")


def _documents(db: Session) -> None:
    from app.modules.documents import service as ds
    from app.modules.documents.models import Document, DocumentType
    from app.modules.strategy.models import CycleAssignment

    if db.query(Document).count():
        return
    ds.ensure_types(db)
    admin = _admin_scope(db)
    pol = ds.create(db, admin, type_id=db.query(DocumentType).filter_by(code="policy").one().id,
                    title="Non-revenue water management policy", org_unit_code="org", owner="planner",
                    approver="south.mgr", tags=["nrw", "operations"])
    ds.add_version(db, _as(db, "planner"), pol.id, "nrw-policy.docx", _demo_docx(
        "Every region measures non-revenue water monthly and reports it quarterly with its water balance."),
        "First issue")
    ds.transition(db, _as(db, "south.mgr"), pol.id, "approve")
    ds.transition(db, _as(db, "planner"), pol.id, "make_effective")
    a = db.query(CycleAssignment).filter_by(org_unit_code="north").first()
    if a is not None:
        ds.attach_evidence(db, _as(db, "north.ops"), "cycle_assignment", a.id, "water-balance-q1.csv",
                           b"month,produced_m3,billed_m3\nJul,410000,281000\nAug,398000,273500\nSep,405500,279000\n",
                           "Q1 water balance (North)")


def _demo_docx(text: str) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                                          'package/2006/content-types"/>')
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
                                        "</w:document>")
    return buf.getvalue()


def _governance(db: Session) -> None:
    from app.modules.governance import service as gv
    from app.modules.governance.models import Meeting, RiskMatrix

    if db.query(RiskMatrix).count() or db.query(Meeting).count():
        return
    admin = _admin_scope(db)
    t = gv.matrix_template(4, 4)
    t["name"] = "Demo utility risk criteria (4 x 4)"
    t["likelihood_levels"] = [{"value": v, "label": lbl} for v, lbl in
                              enumerate(("Unlikely", "Possible", "Likely", "Almost certain"), start=1)]
    t["impact_levels"] = [{"value": v, "label": lbl} for v, lbl in
                          enumerate(("Minor", "Moderate", "Major", "Severe"), start=1)]
    m = gv.save_matrix(db, admin, t)
    gv.activate_matrix(db, admin, m.id)
    gv.create_risk(db, _as(db, "north.ops"), {
        "title": "Prolonged power outage at Hilltop pumping station", "org_unit_code": "north.hilltop",
        "category": "Operational", "cause": "Grid instability", "consequence": "Supply interruption to 4,000 customers",
        "inherent_l": 3, "inherent_i": 4, "residual_l": 2, "residual_i": 3, "review_date": date.today() + timedelta(days=60)})
    gv.create_risk(db, _as(db, "south.mgr"), {
        "title": "Revenue loss from illegal connections", "org_unit_code": "south", "category": "Financial",
        "inherent_l": 4, "inherent_i": 3, "residual_l": 3, "residual_i": 3, "review_date": date.today() + timedelta(days=30)})
    meeting = gv.create_meeting(db, admin, body="Board", title="Quarterly board meeting",
                                meeting_date=date.today() - timedelta(days=7))
    gv.transition_meeting(db, admin, meeting.id, "hold")
    gv.add_resolution(db, admin, meeting.id, text="Management to present a costed NRW reduction programme.",
                      owner="planner", org_unit_code="org", due_date=date.today() + timedelta(days=45))
    gv.create_finding(db, _as(db, "auditor"), {
        "audit_name": "2026 revenue assurance audit (demo)", "title": "Bulk customer accounts not reconciled monthly",
        "rating": "high", "owner": "south.mgr", "org_unit_code": "south",
        "recommendation": "Reconcile bulk customer accounts against meter readings every month."})


def _regulatory(db: Session) -> None:
    from app.modules.regulatory import service as rg
    from app.modules.regulatory.models import RegulatorPack

    if db.query(RegulatorPack).count():
        return
    admin = _admin_scope(db)
    for f in rg.available_files():
        if not f.get("error"):
            rg.import_pack(db, admin, f["file"])      # drafts: they stay unusable until verified and approved


STEPS += [_tree, _users, _actions, _strategy, _scorecard, _reports, _documents, _governance, _regulatory]


def run(db: Session) -> dict[str, str]:
    passwords: dict[str, str] = {}
    for step in STEPS:
        out = step(db)
        if isinstance(out, dict):
            passwords.update(out)
        db.flush()
    db.commit()
    return passwords


def main() -> int:
    from app.core.tenant import tenant
    from app.database import create_tables

    if tenant.key != "demo":
        print(f"Refusing to seed: tenant is '{tenant.key}', not 'demo'.", file=sys.stderr)
        return 1
    create_tables()
    db = SessionLocal()
    try:
        from app.auth import ensure_default_admin
        from app.platform.bootstrap import at_startup
        ensure_default_admin(db)
        at_startup(db)
        passwords = run(db)
    finally:
        db.close()
    if passwords:
        print("Demo accounts created (fictional people; passwords shown once):")
        for user, pw in passwords.items():
            print(f"  {user:<12} {pw}")
    else:
        print("Demo data is in place (no new accounts were needed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
