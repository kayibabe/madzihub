"""Governance and risk: resolutions, audit findings (protected roles), risk criteria and register."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from sqlalchemy import text

from tests._access import add_user
from tests._fixture import AppFixture


class GovFixture(AppFixture):
    def setUp(self):
        super().setUp()
        u = lambda *a, **k: add_user(self.database, self.auth, *a, **k)  # noqa: E731
        self.sec = u("sally", "user", {"org": "viewer"}, functions=("board_secretary",))
        self.aud = u("audra", "user", {"org": "viewer"}, functions=("auditor",))
        self.rm = u("rick", "user", {"org": "viewer"}, functions=("risk_manager",))


class ResolutionTests(GovFixture):
    def test_resolution_creates_an_action_and_secretary_closes_it(self):
        m = self.post("/api/governance/meetings", self.sec, {"body": "Board", "title": "Q1 board meeting",
                                                             "meeting_date": date.today().isoformat()}, 201)
        url = f"/api/governance/meetings/{m['id']}"
        self.assertEqual(self.status("post", f"{url}/resolutions", self.sec, {"text": "x"}), 409)   # not held yet
        self.assertEqual(self.status("post", "/api/governance/meetings", self.nate,
                                     {"body": "B", "title": "t", "meeting_date": date.today().isoformat()}), 403)
        self.post(f"{url}/transition", self.sec, {"name": "hold"})
        m = self.post(f"{url}/resolutions", self.sec, {"text": "Approve the NRW reduction programme budget.",
                                                        "owner": "nate", "org_unit_code": "north",
                                                        "due_date": (date.today() + timedelta(days=60)).isoformat()}, 201)
        res = m["resolutions"][0]
        self.assertEqual(res["number"], f"B/{date.today().year}/001")
        action = self.get(f"/api/platform/actions/{res['action_id']}", self.nate)
        self.assertEqual((action["owner"], action["source_type"]), ("nate", "resolution"))
        rurl = f"/api/governance/resolutions/{res['id']}/transition"
        self.assertEqual(self.status("post", rurl, self.nate, {"name": "implement"}), 422)          # note required
        self.post(rurl, self.nate, {"name": "implement", "reason": "Budget line approved in revised estimates."})
        self.assertEqual(self.status("post", rurl, self.nate, {"name": "close"}), 403)
        done = self.post(rurl, self.sec, {"name": "close"})
        self.assertEqual(done["resolutions"][0]["status"], "closed")
        # Minutes must be attached as a document before they are approved.
        self.assertEqual(self.status("post", f"{url}/transition", self.sec, {"name": "approve_minutes"}), 422)


class AuditFindingTests(GovFixture):
    def test_auditor_and_management_roles_stay_separate(self):
        body = {"audit_name": "2026 revenue audit", "title": "Unbilled bulk customers", "rating": "high",
                "owner": "nate", "org_unit_code": "north", "recommendation": "Reconcile bulk accounts monthly."}
        self.assertEqual(self.status("post", "/api/governance/findings", self.nate, body), 403)   # management
        self.assertEqual(self.status("post", "/api/governance/findings", self.admin, body), 403)  # admin is not an auditor
        f = self.post("/api/governance/findings", self.aud, body, 201)
        url = f"/api/governance/findings/{f['id']}"
        self.assertEqual(self.status("put", url, self.nate, {"rating": "low"}), 403)             # management cannot re-rate
        self.assertEqual(self.status("post", f"{url}/transition", self.aud,
                                     {"name": "respond", "response": "x", "agreed_due_date": date.today().isoformat()}), 403)
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "respond", "response": "Agreed"}), 422)
        due = (date.today() + timedelta(days=30)).isoformat()
        self.post(f"{url}/transition", self.nate, {"name": "respond", "response": "Monthly reconciliation from July.",
                                                   "agreed_due_date": due})
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "accept"}), 403)
        f = self.post(f"{url}/transition", self.aud, {"name": "accept"})
        self.assertEqual(f["status"], "agreed")
        act = f["actions"][0]
        self.assertEqual((act["owner"], act["due_date"]), ("nate", due))
        self.post(f"{url}/transition", self.nate, {"name": "request_closure", "reason": "Reconciliations running since July."})
        r = self.c.post(f"{url}/transition", headers=self.aud, json={"name": "validate"})
        self.assertEqual(r.status_code, 409)                                                     # action still open
        self.assertIn("still open", r.json()["detail"])
        self.post(f"{url}/transition", self.aud, {"name": "reject_closure", "reason": "Action not complete."})
        aurl = f"/api/platform/actions/{act['id']}/transition"
        self.post(aurl, self.nate, {"name": "complete", "note": "July and August reconciled."})
        self.post(aurl, self.nora, {"name": "close"})
        self.post(f"{url}/transition", self.nate, {"name": "request_closure", "reason": "Done; see action."})
        closed = self.post(f"{url}/transition", self.aud, {"name": "validate"})
        self.assertEqual((closed["status"], closed["validated_by"]), ("closed", "audra"))
        self.assertEqual(self.status("get", url, self.sam), 404)                                 # other region
        steps = [d["step"] for d in closed["decisions"]]
        self.assertEqual(steps, ["respond", "accept", "request_closure", "reject_closure", "request_closure", "validate"])


class RiskTests(GovFixture):
    def matrix(self, size=(4, 3)):
        t = self.get(f"/api/governance/risk-matrices/template?likelihood={size[0]}&impact={size[1]}", self.rm)
        m = self.post("/api/governance/risk-matrices", self.rm, t, 201)
        self.post(f"/api/governance/risk-matrices/{m['id']}/activate", self.rm)
        return m

    def test_no_risks_until_the_organisation_sets_its_own_criteria(self):
        r = self.c.post("/api/governance/risks", headers=self.nick, json={"title": "Pump failure", "org_unit_code": "north"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("risk matrix", r.json()["detail"])
        t = self.get("/api/governance/risk-matrices/template?likelihood=4&impact=3", self.rm)
        bad = dict(t, bands=t["bands"][:-1])
        self.assertEqual(self.status("post", "/api/governance/risk-matrices", self.rm, bad), 422)   # scores 1..12 not covered
        self.assertEqual(self.status("post", "/api/governance/risk-matrices", self.nate, t), 403)

    def test_register_with_non_5x5_matrix_history_controls_treatments_and_heatmap(self):
        m = self.matrix((4, 3))
        self.assertEqual((len(m["likelihood_levels"]), len(m["impact_levels"])), (4, 3))
        r = self.post("/api/governance/risks", self.nick, {"title": "Prolonged power outage at Alpha pumps",
                                                          "org_unit_code": "north.alpha", "category": "Operational",
                                                          "inherent_l": 4, "inherent_i": 3,
                                                          "review_date": (date.today() - timedelta(days=1)).isoformat()}, 201)
        self.assertEqual((r["code"], r["inherent"]["score"]), ("RSK-001", 12))
        self.assertEqual(r["inherent"]["appetite"], "outside")
        url = f"/api/governance/risks/{r['id']}"
        self.assertEqual(self.status("post", f"{url}/assess", self.nick, {"kind": "residual", "likelihood": 5, "impact": 1}), 422)
        r = self.post(f"{url}/assess", self.nick, {"kind": "residual", "likelihood": 2, "impact": 2,
                                                   "note": "Standby generator installed"}, 201)
        self.assertEqual((r["residual"]["score"], len(r["assessments"])), (4, 2))
        r = self.post(f"{url}/controls", self.nick, {"description": "Standby generator, tested monthly",
                                                     "effectiveness": "effective"}, 201)
        self.assertEqual(r["controls"][0]["effectiveness"], "effective")
        self.post("/api/platform/actions", self.nick, {"title": "Second feeder line", "owner": "nick",
                                                       "org_unit_code": "north", "source_type": "risk",
                                                       "source_id": str(r["id"])}, 201)
        self.assertEqual(len(self.get(url, self.nick)["treatments"]), 1)
        heat = self.get("/api/governance/risk-heatmap?kind=residual", self.nora)
        self.assertEqual([(c["likelihood"], c["impact"], c["count"]) for c in heat["cells"]], [(2, 2, 1)])
        self.assertEqual(self.get("/api/governance/risk-heatmap", self.sam)["cells"], [])      # South sees none
        self.assertEqual(self.status("post", f"{url}/transition", self.nick, {"name": "close", "reason": "x"}), 403)
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "close"}), 422)
        # Matrices with rated risks cannot be changed underneath them.
        t = self.get("/api/governance/risk-matrices/template?likelihood=4&impact=3", self.rm)
        self.assertEqual(self.status("put", f"/api/governance/risk-matrices/{m['id']}", self.rm, t), 409)
        with self.database.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM risk_assessments")).scalar(), 2)
            with self.assertRaises(Exception):
                conn.execute(text("UPDATE risk_assessments SET score = 1"))
        # The daily job warns the owner that the review date has passed.
        from app.platform.notifications import run_reminders
        db = self.db()
        try:
            run_reminders(db)
        finally:
            db.close()
        self.assertIn("risk_review_overdue", [n["kind"] for n in self.get("/api/platform/notifications", self.nick)])

    def test_board_pack_includes_principal_risks(self):
        self.matrix((3, 3))
        self.post("/api/governance/risks", self.nick, {"title": "Chemical supply disruption", "org_unit_code": "north",
                                                      "residual_l": 3, "residual_i": 3, "inherent_l": 3, "inherent_i": 3}, 201)
        pid = self.post("/api/strategy/plans", self.planner, {"code": "G", "title": "G", "start_fy": 2027, "end_fy": 2028}, 201)["id"]
        q = self.get("/api/platform/periods?period_type=quarter", self.planner)[0]
        tpl = {t["kind"]: t["id"] for t in self.get("/api/reports-hub/templates", self.planner)}
        r = self.post("/api/reports-hub/instances", self.planner, {"template_id": tpl["board_pack"], "period_id": q["id"],
                                                                   "org_unit_code": "north", "plan_id": pid}, 201)
        html = self.c.get(f"/api/reports-hub/instances/{r['id']}/output/html", headers=self.planner).text
        self.assertIn("Principal risks", html)
        self.assertIn("Chemical supply disruption", html)


if __name__ == "__main__":
    unittest.main()
