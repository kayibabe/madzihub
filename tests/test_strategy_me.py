"""Strategy and M&E: plan structure, reference sheets, cycles, immutable updates, DQA, evaluations."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from sqlalchemy import text

from tests._access import add_user
from tests._fixture import AppFixture


class StrategyFixture(AppFixture):
    def setUp(self):
        super().setUp()
        self.plan = self.post("/api/strategy/plans", self.planner,
                              {"code": "SP26", "title": "Corporate Plan 2026-2030", "start_fy": 2027, "end_fy": 2030}, 201)
        pid = self.plan["id"]
        self.pillar = self.post(f"/api/strategy/plans/{pid}/nodes", self.planner,
                                {"node_type": "pillar", "code": "P1", "title": "Water security"}, 201)["id"]
        self.objective = self.post(f"/api/strategy/plans/{pid}/nodes", self.planner,
                                   {"node_type": "objective", "code": "O1", "title": "Reduce water losses",
                                    "parent_id": self.pillar}, 201)["id"]
        self.ind = self.post(f"/api/strategy/plans/{pid}/indicators", self.planner, {
            "code": "NRW", "name": "Non-revenue water", "node_id": self.objective, "unit": "%",
            "polarity": "lower", "aggregation": "avg", "frequency": "quarter", "valid_min": 0, "valid_max": 100,
            "reporting_units": ["north", "south"], "definition": "Share of produced water not billed."}, 201)
        self.quarter = next(p for p in self.get("/api/platform/periods?period_type=quarter", self.planner)
                            if p["start_date"] <= date.today().isoformat() <= p["end_date"])

    def activate(self):
        return self.post(f"/api/strategy/plans/{self.plan['id']}/transition", self.planner, {"name": "activate"})

    def open_cycle(self, **extra):
        self.activate()
        cycle = self.post(f"/api/strategy/plans/{self.plan['id']}/cycles", self.planner,
                          {"period_id": self.quarter["id"], **extra}, 201)
        self.assertEqual(self.post(f"/api/strategy/cycles/{cycle['id']}/generate", self.planner)["created"], 2)
        self.post(f"/api/strategy/cycles/{cycle['id']}/transition", self.planner, {"name": "open"})
        rows = self.get(f"/api/strategy/assignments?cycle_id={cycle['id']}&queue=all", self.planner)
        by_unit = {a["org_unit_code"]: a for a in rows}
        return cycle, by_unit["north"]["id"], by_unit["south"]["id"]


class PlanStructureTests(StrategyFixture):
    def test_only_strategy_managers_shape_the_plan(self):
        self.assertEqual(self.status("post", "/api/strategy/plans", self.nate,
                                     {"code": "X", "title": "x", "start_fy": 2027, "end_fy": 2028}), 403)
        self.assertEqual(self.status("post", f"/api/strategy/plans/{self.plan['id']}/nodes", self.admin,
                                     {"node_type": "pillar", "code": "P2", "title": "Finance"}), 201)

    def test_nesting_rules_and_configurable_labels(self):
        pid = self.plan["id"]
        bad = self.c.post(f"/api/strategy/plans/{pid}/nodes", headers=self.planner,
                          json={"node_type": "pillar", "code": "PX", "title": "x", "parent_id": self.objective})
        self.assertEqual(bad.status_code, 422)
        bad = self.c.post(f"/api/strategy/plans/{pid}/nodes", headers=self.planner,
                          json={"node_type": "initiative", "code": "I0", "title": "x", "parent_id": self.objective})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("linked, not nested", bad.json()["detail"])
        init = self.post(f"/api/strategy/plans/{pid}/nodes", self.planner,
                         {"node_type": "initiative", "code": "I1", "title": "District metering",
                          "org_unit_code": "north", "owner": "nora"}, 201)["id"]
        self.post(f"/api/strategy/nodes/{init}/contributes", self.planner, {"result_node_id": self.objective}, 201)
        self.assertEqual(self.status("post", f"/api/strategy/nodes/{self.objective}/contributes", self.planner,
                                     {"result_node_id": self.pillar}), 422)
        # A pillar cannot be moved under its own descendant.
        self.assertEqual(self.status("put", f"/api/strategy/nodes/{self.pillar}", self.planner,
                                     {"parent_id": self.objective}), 422)
        levels = self.put(f"/api/strategy/plans/{pid}/levels", self.planner,
                          [{"node_type": "pillar", "label": "Focus area"}])
        self.assertEqual(levels["pillar"]["label"], "Focus area")
        self.assertEqual(self.status("put", f"/api/strategy/plans/{pid}/levels", self.planner,
                                     [{"node_type": "pillar", "label": "Focus area", "enabled": False}]), 422)
        detail = self.get(f"/api/strategy/plans/{pid}", self.planner)
        self.assertEqual(detail["contributes"], [{"id": detail["contributes"][0]["id"], "from": init, "to": self.objective}])
        # The owner reports delivery status; only a manager may retitle.
        self.assertEqual(self.status("put", f"/api/strategy/nodes/{init}", self.nora, {"status": "at_risk"}), 200)
        self.assertEqual(self.status("put", f"/api/strategy/nodes/{init}", self.nora, {"title": "Renamed"}), 403)

    def test_region_user_sees_context_but_not_other_units(self):
        pid = self.plan["id"]
        self.post(f"/api/strategy/plans/{pid}/nodes", self.planner,
                  {"node_type": "outcome", "code": "OC-S", "title": "South meters", "parent_id": self.objective,
                   "org_unit_code": "south"}, 201)
        self.post(f"/api/strategy/plans/{pid}/nodes", self.planner,
                  {"node_type": "outcome", "code": "OC-N", "title": "North meters", "parent_id": self.objective,
                   "org_unit_code": "north"}, 201)
        seen = self.get(f"/api/strategy/plans/{pid}", self.nick)
        codes = {n["code"]: n for n in seen["nodes"]}
        self.assertNotIn("OC-S", codes)
        self.assertFalse(codes["OC-N"]["context_only"])
        self.assertTrue(codes["P1"]["context_only"])
        self.assertNotIn("owner", codes["P1"])
        self.assertEqual([i["code"] for i in seen["indicators"]], ["NRW"])   # north reports it
        self.assertEqual(self.get("/api/strategy/plans", self.nick)[0]["code"], "SP26")


class ReferenceSheetTests(StrategyFixture):
    def test_definition_changes_are_versioned_with_reason(self):
        url = f"/api/strategy/indicators/{self.ind['id']}"
        self.assertEqual(self.status("put", url, self.planner, {"definition": "New wording"}), 422)
        out = self.put(url, self.planner, {"definition": "New wording", "reason": "Align with regulator guide"})
        self.assertEqual(out["version"], 2)
        out = self.put(url, self.planner, {"dq_notes": "Bulk meters calibrated yearly"})
        self.assertEqual(out["version"], 2)   # administrative fields do not create a version
        hist = self.get(f"/api/platform/history?type=indicator&id={self.ind['id']}", self.planner)
        change = [e for e in hist if e["action"] == "indicator.update"][0]
        self.assertEqual((change["before"]["version"], change["after"]["version"], change["reason"]),
                         (1, 2, "Align with regulator guide"))

    def test_invalid_reference_sheets_are_refused(self):
        pid = self.plan["id"]
        for body in ({"code": "A1", "name": "x", "polarity": "sideways"},
                     {"code": "A2", "name": "x", "frequency": "weekly"},
                     {"code": "A3", "name": "x", "collection": "automatic", "metric_code": "no_such_measure"},
                     {"code": "A4", "name": "x", "valid_min": 10, "valid_max": 1},
                     {"code": "A5", "name": "x", "node_id": 99999},
                     {"code": "bad code!", "name": "x"}):
            self.assertEqual(self.status("post", f"/api/strategy/plans/{pid}/indicators", self.planner, body), 422, body)
        self.assertEqual(self.status("post", f"/api/strategy/plans/{pid}/indicators", self.planner,
                                     {"code": "NRW", "name": "dup"}), 409)

    def test_targets_are_on_the_fiscal_calendar_and_changes_need_reasons(self):
        url = f"/api/strategy/indicators/{self.ind['id']}/targets"
        q = self.quarter["start_date"]
        self.assertEqual(self.status("put", url, self.planner, {"targets": [
            {"period_type": "quarter", "period_start": "2026-08-01", "value": 30, "org_unit_code": "north"}]}), 422)
        rows = self.put(url, self.planner, {"targets": [
            {"period_type": "quarter", "period_start": q, "value": 30, "org_unit_code": "north"},
            {"period_type": "quarter", "period_start": q, "value": 28, "org_unit_code": "south"}]})
        self.assertEqual(sorted(r["value"] for r in rows), [28, 30])
        self.assertEqual(self.status("put", url, self.planner, {"targets": [
            {"period_type": "quarter", "period_start": q, "value": 25, "org_unit_code": "north"}]}), 422)
        self.put(url, self.planner, {"targets": [{"period_type": "quarter", "period_start": q, "value": 25,
                                                  "org_unit_code": "north"}], "reason": "Board revision"})
        seen = self.get(f"/api/strategy/indicators/{self.ind['id']}", self.nick)["targets"]
        self.assertEqual([(t["org_unit_code"], t["value"]) for t in seen], [("north", 25)])   # south hidden


class QuarterlyReviewTests(StrategyFixture):
    def test_submit_verify_approve_publish_reopen_correct(self):
        cycle, north, south = self.open_cycle()
        self.put(f"/api/strategy/indicators/{self.ind['id']}/targets", self.planner, {"targets": [
            {"period_type": "quarter", "period_start": self.quarter["start_date"], "value": 30, "org_unit_code": "north"}]})
        url = f"/api/strategy/assignments/{north}"
        # The South contributor cannot see, let alone submit, the North update.
        self.assertEqual(self.status("post", f"{url}/submit", self.sam, {"value": 1}), 404)
        self.assertEqual(self.status("post", f"{url}/submit", self.nick, {}), 422)   # no value, not pending/N/A
        out = self.post(f"{url}/submit", self.nick, {"value": 34.5, "narrative": "Meter faults in Alpha."}, 201)
        self.assertEqual((out["status"], out["latest"]["revision"]), ("submitted", 1))
        dqa = {d["check"]: d for d in out["revisions"][0]["dqa"]}
        self.assertEqual(dqa["completeness"]["result"], "warn")   # off target, no variance reason
        self.assertEqual(dqa["range"]["result"], "pass")
        self.assertEqual(self.status("post", f"{url}/transition", self.nick, {"name": "verify"}), 403)   # own
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "approve"}), 409)  # not verified
        self.assertEqual(self.status("post", f"{url}/transition", self.nora, {"name": "return"}), 422)   # reason
        self.post(f"{url}/transition", self.nora, {"name": "return", "reason": "Add the variance reason"})
        out = self.post(f"{url}/submit", self.nick, {"value": 34.5, "variance_reason": "Two bulk meters failed",
                                                     "corrective_action": "Replace meters"}, 201)
        self.assertEqual(out["latest"]["revision"], 2)
        self.post(f"{url}/transition", self.nora, {"name": "verify"})
        out = self.post(f"{url}/transition", self.nate, {"name": "approve"})
        self.assertEqual(out["status"], "approved")
        self.assertEqual([s["step"] for s in out["approvals"]], ["submit", "return", "submit", "verify", "approve"])
        # Approved value is published and read back through the catalogue like any source.
        series = self.get(f"/api/strategy/indicators/{self.ind['id']}/series?org_unit=north", self.nick)["series"]
        self.assertEqual([(s["period"], s["value"]) for s in series], [(self.quarter["start_date"], 34.5)])
        # Correction only by a reasoned reopen, then a new revision replaces the published value.
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "reopen"}), 422)
        self.post(f"{url}/transition", self.nate, {"name": "reopen", "reason": "Meter reading corrected"})
        self.post(f"{url}/submit", self.nick, {"value": 31.0, "variance_reason": "Corrected reading"}, 201)
        self.post(f"{url}/transition", self.nora, {"name": "verify"})
        self.post(f"{url}/transition", self.nate, {"name": "approve"})
        series = self.get(f"/api/strategy/indicators/{self.ind['id']}/series?org_unit=north", self.nick)["series"]
        self.assertEqual(series[-1]["value"], 31.0)
        hist = self.get(f"/api/platform/history?type=indicator&id={self.ind['id']}", self.planner)
        pubs = [e for e in hist if e["action"] == "metric_value.publish"]
        self.assertEqual([(p["before"] or {}).get("value") for p in pubs], [None, 34.5])
        # Every revision is kept, and the database refuses to edit one.
        detail = self.get(url, self.nick)
        self.assertEqual([r["revision"] for r in detail["revisions"]], [3, 2, 1])
        with self.database.engine.connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(text("UPDATE progress_updates SET value = 0"))
        # South sees only South in the cycle and the queue views.
        rows = self.get(f"/api/strategy/assignments?cycle_id={cycle['id']}&queue=all", self.sam)
        self.assertEqual([r["id"] for r in rows], [south])

    def test_locked_period_and_closed_cycle_refuse_changes(self):
        cycle, north, _ = self.open_cycle()
        year = next(p for p in self.get("/api/platform/periods?period_type=year", self.admin)
                    if p["fiscal_year"] == self.quarter["fiscal_year"])
        self.post(f"/api/platform/periods/{year['id']}/lock", self.admin, {"reason": "Year-end close"})
        r = self.c.post(f"/api/strategy/assignments/{north}/submit", headers=self.nick, json={"value": 30})
        self.assertEqual(r.status_code, 409)
        self.assertIn("locked", r.json()["detail"])
        self.post(f"/api/platform/periods/{year['id']}/reopen", self.admin, {"reason": "Late return accepted"})
        self.post(f"/api/strategy/cycles/{cycle['id']}/transition", self.planner, {"name": "close"})
        self.assertEqual(self.status("post", f"/api/strategy/assignments/{north}/submit", self.nick, {"value": 30}), 409)
        self.assertEqual(self.status("post", f"/api/strategy/cycles/{cycle['id']}/transition", self.planner,
                                     {"name": "reopen"}), 422)

    def test_zero_not_applicable_and_pending_stay_distinct(self):
        _, north, south = self.open_cycle(require_verification=False)
        self.assertEqual(self.status("post", f"/api/strategy/assignments/{south}/submit", self.sam,
                                     {"value_state": "not_applicable"}), 422)   # needs an explanation
        self.post(f"/api/strategy/assignments/{south}/submit", self.sam,
                  {"value_state": "not_applicable", "narrative": "Scheme decommissioned this quarter."}, 201)
        self.post(f"/api/strategy/assignments/{south}/transition", self.sue, {"name": "approve"})
        self.post(f"/api/strategy/assignments/{north}/submit", self.nick, {"value_state": "pending"}, 201)
        self.assertEqual(self.status("post", f"/api/strategy/assignments/{north}/transition", self.nate,
                                     {"name": "approve"}), 422)
        self.post(f"/api/strategy/assignments/{north}/submit", self.nick, {"value": 0}, 201)
        self.post(f"/api/strategy/assignments/{north}/transition", self.nate, {"name": "approve"})
        from app.integration.models import MetricValue
        db = self.db()
        try:
            rows = {r.org_unit_code: (r.status, r.value) for r in db.query(MetricValue)}
        finally:
            db.close()
        self.assertEqual(rows, {"south": ("na", None), "north": ("actual", 0.0)})

    def test_dqa_records_problems_without_changing_values(self):
        pid = self.plan["id"]
        ev = self.post(f"/api/strategy/plans/{pid}/indicators", self.planner, {
            "code": "CUST", "name": "Customer complaints resolved", "unit": "%", "frequency": "quarter",
            "valid_min": 0, "valid_max": 100, "evidence_required": True, "reporting_units": ["north"]}, 201)
        self.activate()
        cycle = self.post(f"/api/strategy/plans/{pid}/cycles", self.planner,
                          {"period_id": self.quarter["id"], "due_on": (date.today() - timedelta(days=3)).isoformat()}, 201)
        self.post(f"/api/strategy/cycles/{cycle['id']}/generate", self.planner)
        self.post(f"/api/strategy/cycles/{cycle['id']}/transition", self.planner, {"name": "open"})
        aid = next(a["id"] for a in self.get(f"/api/strategy/assignments?cycle_id={cycle['id']}&queue=all", self.nick)
                   if a["indicator"]["id"] == ev["id"])
        overdue = self.get("/api/strategy/assignments?queue=overdue", self.nick)
        self.assertIn(aid, [a["id"] for a in overdue])
        # Out of range and without evidence: refused unless the submitter acknowledges it (RJ-03).
        r = self.c.post(f"/api/strategy/assignments/{aid}/submit", headers=self.nick, json={"value": 140})
        self.assertEqual(r.status_code, 422)
        self.assertIn("140 is outside the valid range 0–100", r.json()["detail"])
        self.assertIn("Evidence is required", r.json()["detail"])
        self.assertEqual(self.get(f"/api/strategy/assignments/{aid}", self.nick)["revisions"], [])   # nothing saved
        out = self.post(f"/api/strategy/assignments/{aid}/submit", self.nick,
                        {"value": 140, "acknowledge_checks": True}, 201)
        dqa = {d["check"]: d for d in out["revisions"][0]["dqa"]}
        self.assertEqual(dqa["range"]["result"], "fail")
        self.assertEqual(dqa["evidence"]["result"], "fail")
        self.assertIn("acknowledged", dqa["range"]["reason"])
        self.assertEqual(dqa["timeliness"]["result"], "warn")
        self.assertEqual(out["latest"]["value"], 140)        # recorded as submitted, never adjusted
        self.assertTrue(out["latest"]["late"])
        hist = self.get(f"/api/platform/history?type=cycle_assignment&id={aid}", self.nora)
        submit = [e for e in hist if (e["after"] or {}).get("revision") == 1 and e["action"].endswith("submit")][0]
        self.assertEqual(submit["after"]["acknowledged_checks"], ["range", "evidence"])
        # An in-range value with evidence needs no acknowledgement, and none is recorded.
        out = self.post(f"/api/strategy/assignments/{aid}/submit", self.nick,
                        {"value": 95, "evidence_note": "CRM export", "acknowledge_checks": True}, 201)
        dqa = {d["check"]: d for d in out["revisions"][0]["dqa"]}
        self.assertEqual((dqa["range"]["result"], dqa["evidence"]["result"]), ("pass", "pass"))
        self.assertEqual(self.status("post", f"/api/strategy/assignments/{aid}/dqa", self.nick,
                                     {"check": "reviewer", "result": "fail", "reason": "x"}), 403)
        out = self.post(f"/api/strategy/assignments/{aid}/dqa", self.nora,
                        {"check": "reviewer", "result": "fail", "reason": "Above 100%: cannot be right"}, 201)
        self.assertEqual(out["revisions"][0]["dqa"][-1]["assessed_by"], "nora")

    def test_my_work_queues_and_reminders(self):
        cycle, north, _ = self.open_cycle()
        # No named contributor yet: every contributor on the unit sees it; South never does.
        self.assertEqual([a["id"] for a in self.get("/api/platform/my-work", self.nick)["updates_to_submit"]], [north])
        self.assertNotIn(north, [a["id"] for a in self.get("/api/platform/my-work", self.sam)["updates_to_submit"]])
        self.put(f"/api/strategy/assignments/{north}", self.planner, {"contributor": "nora", "reviewer": "nate"})
        self.assertEqual(self.get("/api/platform/my-work", self.nick)["updates_to_submit"], [])
        self.assertEqual(self.status("put", f"/api/strategy/assignments/{north}", self.nick, {"contributor": "nick"}), 403)
        self.put(f"/api/strategy/assignments/{north}", self.planner, {"contributor": "nick", "reviewer": "nora"})
        work = self.get("/api/platform/my-work", self.nick)
        self.assertEqual([a["id"] for a in work["updates_to_submit"]], [north])
        self.post(f"/api/strategy/assignments/{north}/submit", self.nick, {"value": 29}, 201)
        self.assertEqual([a["id"] for a in self.get("/api/platform/my-work", self.nora)["updates_to_verify"]], [north])
        notes = [n["kind"] for n in self.get("/api/platform/notifications", self.nora)]
        self.assertIn("update_submitted", notes)


class RoutingTests(StrategyFixture):
    """Slice 1c: work reaches people who can open it, and every hand-off asks the next actor."""

    def notices(self, h, unread=True):
        return [(n["kind"], n["entity_id"]) for n in
                self.get(f"/api/platform/notifications?unread_only={'true' if unread else 'false'}", h)]

    def set_contributor(self, aid, username):
        """Name someone directly, as older data or a later loss of access can leave it."""
        from app.modules.strategy.models import CycleAssignment
        db = self.db()
        try:
            db.get(CycleAssignment, aid).contributor = username
            db.commit()
        finally:
            db.close()

    def test_owner_submits_only_where_they_have_access(self):
        # RJ-01: the owner has North access only; South goes to South's own contributor.
        self.put(f"/api/strategy/indicators/{self.ind['id']}", self.planner, {"owner": "nick"})
        cycle, north, south = self.open_cycle()
        rows = {a["id"]: a for a in self.get(f"/api/strategy/cycles/{cycle['id']}", self.planner)["assignments"]}
        self.assertEqual((rows[north]["contributor"], rows[south]["contributor"]), ("nick", None))
        self.assertEqual(rows[south]["routing"]["contributor"], {"named": None, "named_can_act": True, "asked": ["sam"]})
        # South has no reviewer: its approver is asked before anyone organisation-wide.
        self.assertEqual(rows[south]["routing"]["reviewer"]["asked"], ["sue"])
        self.assertEqual(rows[north]["routing"]["approver"]["asked"], ["nate"])
        self.assertEqual(self.notices(self.nick), [("update_requested", str(north))])
        self.assertEqual(self.notices(self.sam), [("update_requested", str(south))])
        for h in (self.sue, self.planner, self.nora):      # higher roles are not asked to submit
            self.assertEqual(self.notices(h), [])
        self.assertEqual([a["id"] for a in self.get("/api/platform/my-work", self.sam)["updates_to_submit"]], [south])
        self.assertNotIn(south, [a["id"] for a in self.get("/api/platform/my-work", self.nick)["updates_to_submit"]])
        # Routing is visible to strategy managers only.
        self.assertNotIn("routing", self.get(f"/api/strategy/cycles/{cycle['id']}", self.sam)["assignments"][0])

    def test_named_person_without_access_is_flagged_and_bypassed(self):
        cycle, north, south = self.open_cycle()
        self.set_contributor(south, "nick")              # e.g. generated before this fix
        row = next(a for a in self.get(f"/api/strategy/cycles/{cycle['id']}", self.planner)["assignments"]
                   if a["id"] == south)
        self.assertEqual(row["routing"]["contributor"], {"named": "nick", "named_can_act": False, "asked": ["sam"]})
        self.assertNotIn(south, [a["id"] for a in self.get("/api/strategy/assignments?queue=submit", self.nick)])
        self.assertIn(south, [a["id"] for a in self.get("/api/strategy/assignments?queue=submit", self.sam)])
        self.assertEqual(self.status("post", f"/api/strategy/assignments/{south}/submit", self.nick, {"value": 30}), 404)
        # Only people holding the step's role on the unit can be named; read-only accounts never.
        for body in ({"contributor": "nick"}, {"reviewer": "sam"}, {"approver": "nora"}):
            r = self.c.put(f"/api/strategy/assignments/{south if 'contributor' in body else north}",
                           headers=self.planner, json=body)
            self.assertEqual(r.status_code, 422, body)
        r = self.c.put(f"/api/strategy/assignments/{north}", headers=self.planner, json={"contributor": "vic"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("read-only", r.json()["detail"])
        self.put(f"/api/strategy/assignments/{south}", self.planner, {"contributor": "sam", "approver": "sue"})
        self.put(f"/api/strategy/assignments/{north}", self.planner, {"contributor": "nora"})   # reviewers may submit

    def test_each_hand_off_asks_the_next_actor_and_closes_the_request(self):
        # RJ-02, South: submit -> sue verifies (no South reviewer) -> planner approves (no other approver).
        cycle, north, south = self.open_cycle()
        url = f"/api/strategy/assignments/{south}"
        self.post(f"{url}/submit", self.sam, {"value": 30}, 201)
        self.assertEqual(self.notices(self.sam), [])                       # the request is answered
        self.assertEqual(self.notices(self.sue), [("update_submitted", str(south))])
        self.assertEqual(self.get("/api/platform/me", self.sue)["unread_notifications"], 1)
        self.post(f"{url}/transition", self.sue, {"name": "verify"})
        self.assertEqual(self.notices(self.sue), [])
        self.assertEqual(self.notices(self.planner), [("update_verified", str(south))])
        self.post(f"{url}/transition", self.planner, {"name": "approve"})
        self.assertEqual(self.notices(self.planner), [])
        self.assertEqual(self.notices(self.sam), [("update_approved", str(south))])

        # North: a return reaches the person who actually submitted, with the reason.
        url = f"/api/strategy/assignments/{north}"
        self.put(url, self.planner, {"contributor": "nick"})
        self.post("/api/platform/notifications/read-all", self.nick)
        self.post(f"{url}/submit", self.nate, {"value": 29}, 201)           # an approver submits for the unit
        self.assertEqual(self.notices(self.nora), [("update_submitted", str(north))])
        self.assertEqual(self.notices(self.nate), [])                       # never asked to review their own
        self.post(f"{url}/transition", self.nora, {"name": "return", "reason": "Use the audited figure"})
        returned = self.get("/api/platform/notifications?unread_only=true", self.nate)
        self.assertEqual([(n["kind"], n["body"]) for n in returned], [("update_returned", "Use the audited figure")])
        self.assertEqual([n["kind"] for n in self.get("/api/platform/notifications?unread_only=true", self.nick)],
                         ["update_returned"])                                # and the named contributor
        self.assertEqual(self.notices(self.nora), [])
        # A resubmission closes the return notices and asks the reviewer again.
        self.post(f"{url}/submit", self.nick, {"value": 28}, 201)
        self.assertEqual(self.notices(self.nick), [])
        self.assertEqual(self.notices(self.nora), [("update_submitted", str(north))])

    def test_reminders_follow_routing(self):
        from app.platform.notifications import run_reminders
        cycle, north, south = self.open_cycle(due_on=(date.today() + timedelta(days=2)).isoformat())
        self.post("/api/platform/notifications/read-all", self.sam)
        db = self.db()
        try:
            run_reminders(db)
        finally:
            db.close()
        self.assertEqual(self.notices(self.sam), [("update_due_soon", str(south))])
        self.assertEqual(self.notices(self.sue), [])


    def test_strategy_manager_with_viewer_scope_can_read_assignable_users_and_reassign(self):
        # CR-01: a strategy_manager who holds only viewer role on a unit must not receive 403
        # from the assignable-users endpoint — they need it to correct routing.
        coord = add_user(self.database, self.auth, "coord", "user", {"north": "viewer"},
                         functions=("strategy_manager",))
        cycle, north, _ = self.open_cycle()
        # Viewer-scoped strategy manager can read the People list for north.
        people = self.get(f"/api/platform/assignable-users?unit=north", coord)
        usernames = [p["username"] for p in people]
        self.assertIn("nick", usernames)
        # They can also save a reassignment via the assignment PUT endpoint.
        self.put(f"/api/strategy/assignments/{north}", coord, {"contributor": "nick"})
        row = next(a for a in self.get(f"/api/strategy/cycles/{cycle['id']}", coord)["assignments"]
                   if a["id"] == north)
        self.assertEqual(row["contributor"], "nick")
        # A plain user with viewer scope on north cannot call assignable-users (403).
        self.assertEqual(self.status("get", f"/api/platform/assignable-users?unit=north", self.vic), 403)


class EvaluationTests(StrategyFixture):
    def test_findings_need_responses_and_accepted_ones_create_actions(self):
        ev = self.post(f"/api/strategy/plans/{self.plan['id']}/evaluations", self.planner,
                       {"title": "Mid-term review", "kind": "mid_term", "org_unit_code": "north", "lead": "nora",
                        "criteria": ["effectiveness", "efficiency"]}, 201)
        url = f"/api/strategy/evaluations/{ev['id']}"
        self.post(f"{url}/transition", self.nora, {"name": "start"})
        ev = self.post(f"{url}/findings", self.nora, {"finding": "Leak repairs are slow",
                                                      "recommendation": "Set a 48-hour repair standard"}, 201)
        ev = self.post(f"{url}/findings", self.nora, {"finding": "Outsource meter reading"}, 201)
        self.assertEqual(self.status("post", f"{url}/transition", self.nora, {"name": "complete"}), 422)  # no summary
        self.put(url, self.nora, {"findings_summary": "Losses fell but repairs lag."})
        r = self.c.post(f"{url}/transition", headers=self.nora, json={"name": "complete"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("need a management response", r.json()["detail"])
        first, second = ev["responses"]
        self.assertEqual(self.status("post", f"/api/strategy/responses/{first['id']}", self.nick,
                                     {"response": "accepted", "response_text": "ok", "owner": "nick"}), 403)
        self.assertEqual(self.status("post", f"/api/strategy/responses/{first['id']}", self.nate,
                                     {"response": "accepted", "response_text": "Agreed"}), 422)   # needs owner
        ev = self.post(f"/api/strategy/responses/{first['id']}", self.nate,
                       {"response": "accepted", "response_text": "Agreed; standard from next quarter.",
                        "owner": "nick", "due_date": (date.today() + timedelta(days=60)).isoformat()})
        ev = self.post(f"/api/strategy/responses/{second['id']}", self.nate,
                       {"response": "rejected", "response_text": "Reading stays in-house for data quality."})
        action_id = ev["responses"][0]["action_id"]
        self.assertIsNotNone(action_id)
        self.assertIsNone(ev["responses"][1]["action_id"])
        action = self.get(f"/api/platform/actions/{action_id}", self.nick)
        self.assertEqual((action["owner"], action["source_type"]), ("nick", "management_response"))
        self.assertTrue(any(l["relation"] == "responds_to" for l in action["links"]))
        self.post(f"{url}/transition", self.nora, {"name": "complete"})
        self.assertEqual(self.status("put", url, self.nora, {"limitations": "late"}), 409)
        self.assertEqual(self.status("get", url, self.sam), 404)   # South cannot see a North evaluation


class TenantImportTests(AppFixture):
    def test_import_tenant_plan_is_idempotent(self):
        out = self.post("/api/strategy/plans/import-tenant", self.planner)
        self.assertTrue(out["created"])
        self.assertEqual((out["pillars"], out["indicators"]), (2, 4))   # demo: Operations, Commercial
        plan = self.get(f"/api/strategy/plans/{out['plan_id']}", self.planner)
        nrw = next(i for i in plan["indicators"] if i["name"] == "Non-Revenue Water")
        self.assertEqual((nrw["polarity"], nrw["collection"], nrw["frequency"]), ("lower", "manual", "year"))
        targets = self.get(f"/api/strategy/indicators/{nrw['id']}", self.planner)["targets"]
        self.assertEqual([t["value"] for t in targets], [30, 28, 26, 25])
        self.assertEqual(targets[0]["label"], "FY2025/26")
        again = self.post("/api/strategy/plans/import-tenant", self.planner)
        self.assertFalse(again["created"])
        self.assertEqual(self.status("post", "/api/strategy/plans/import-tenant", self.nick), 403)


if __name__ == "__main__":
    unittest.main()
