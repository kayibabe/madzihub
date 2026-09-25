"""Performance contracts and staff appraisal: policy gate, privacy, appeals and corrections."""
from __future__ import annotations

import unittest
from datetime import date

from tests._access import add_user
from tests._fixture import AppFixture


class PeopleFixture(AppFixture):
    def setUp(self):
        super().setUp()
        self.hr = add_user(self.database, self.auth, "hana", "user", {"org": "viewer"}, functions=("hr_officer",))
        self.hr2 = add_user(self.database, self.auth, "hugo", "user", {"org": "viewer"}, functions=("hr_officer",))

    def open_gate(self, module):
        return self.post("/api/people/gate", self.hr, {"module": module, "policy_ref": "HR Manual 2026 §7 (Board res. B/2026/004)"}, 201)


class GateAndPrivacyTests(PeopleFixture):
    def test_modules_stay_off_until_hr_records_the_policy(self):
        r = self.c.get("/api/people/appraisals", headers=self.hr)
        self.assertEqual(r.status_code, 409)
        self.assertIn("approved HR policy", r.json()["detail"])
        self.assertEqual(self.status("post", "/api/people/gate", self.admin,
                                     {"module": "staff_appraisal", "policy_ref": "x"}), 403)   # admin is not HR
        self.assertEqual(self.status("post", "/api/people/gate", self.hr, {"module": "staff_appraisal", "policy_ref": " "}), 422)
        gate = self.open_gate("staff_appraisal")
        self.assertTrue(gate["staff_appraisal"]["enabled"])
        self.assertFalse(gate["performance_contracts"]["enabled"])

    def test_appraisals_are_private_and_appeals_and_corrections_are_recorded(self):
        self.open_gate("staff_appraisal")
        objectives = [{"title": "Cut unbilled connections", "weight": 60}, {"title": "Close meter backlog", "weight": 40}]
        self.assertEqual(self.status("post", "/api/people/appraisals", self.nick,
                                     {"employee": "nick", "appraiser": "nora", "period_label": "FY2026/27", "objectives": objectives}), 403)
        self.assertEqual(self.status("post", "/api/people/appraisals", self.hr,
                                     {"employee": "nick", "appraiser": "nora", "period_label": "FY2026/27",
                                      "objectives": [{"title": "x", "weight": 50}]}), 422)
        a = self.post("/api/people/appraisals", self.hr, {"employee": "nick", "appraiser": "nora",
                                                          "period_label": "FY2026/27", "objectives": objectives}, 201)
        url = f"/api/people/appraisals/{a['id']}"
        for outsider in (self.admin, self.nate, self.sam, self.planner):       # admin, unit approver, others
            self.assertEqual(self.status("get", url, outsider), 404)
        self.assertEqual([x["id"] for x in self.get("/api/people/appraisals", self.nate)], [])
        tr = lambda h, body, code=None: self.post(f"{url}/transition", h, body, code)
        self.assertEqual(self.status("post", f"{url}/transition", self.nora, {"name": "agree"}), 403)
        tr(self.nick, {"name": "agree"})
        self.assertEqual(self.status("post", f"{url}/transition", self.nick, {"name": "self_assess", "ratings": {"0": 6, "1": 3}}), 422)
        tr(self.nick, {"name": "self_assess", "ratings": {"0": 4, "1": 4}, "comment": "Both on track."})
        done = tr(self.nora, {"name": "appraise", "ratings": {"0": 3, "1": 2}, "comment": "Backlog not closed."})
        self.assertEqual(done["overall_rating"], 2.6)                          # 3×60% + 2×40%
        self.assertEqual(self.status("post", f"{url}/transition", self.nick, {"name": "appeal"}), 422)
        tr(self.nick, {"name": "appeal", "reason": "Meter stock was not delivered; outside my control."})
        self.assertEqual(self.status("post", f"{url}/transition", self.nora, {"name": "decide", "reason": "x"}), 403)
        closed = tr(self.hr, {"name": "decide", "reason": "Stock delay confirmed; objective 2 rated 3.", "overall": 3.0})
        self.assertEqual((closed["status"], closed["overall_rating"]), ("closed", 3.0))
        corrected = tr(self.hr2, {"name": "correct", "reason": "Data entry error in decision", "overall": 3.2})
        hist = [(h["action"], (h["before"] or {}).get("overall_rating"), (h["after"] or {}).get("overall_rating"))
                for h in corrected["history"] if h["action"].endswith(("decide", "correct"))]
        self.assertEqual(hist, [("staff_appraisal.decide", 2.6, 3.0), ("staff_appraisal.correct", 3.0, 3.2)])
        # The general audit trail never shows private HR records, even to auditors and admins.
        trail = self.get("/api/platform/audit?limit=2000", self.admin)
        self.assertFalse([e for e in trail if e["entity_type"] in ("staff_appraisal", "hr_policy")])


class ContractTests(PeopleFixture):
    def test_contract_signed_evaluated_on_approved_scheme_and_appealed(self):
        self.open_gate("performance_contracts")
        pid = self.post("/api/strategy/plans", self.planner, {"code": "C", "title": "C", "start_fy": 2027, "end_fy": 2028}, 201)["id"]
        ind = self.post(f"/api/strategy/plans/{pid}/indicators", self.planner,
                        {"code": "CE", "name": "Collection efficiency", "frequency": "year", "polarity": "higher",
                         "reporting_units": ["north"]}, 201)
        year = next(p for p in self.get("/api/platform/periods?period_type=year", self.planner)
                    if p["start_date"] <= date.today().isoformat() <= p["end_date"])
        self.put(f"/api/strategy/indicators/{ind['id']}/targets", self.planner, {"targets": [
            {"period_type": "year", "period_start": year["start_date"], "value": 90, "org_unit_code": "north"}]})
        from app.integration.models import DataSource, MetricValue
        db = self.db()
        try:
            src = DataSource(code="billing", name="Billing", system_type="billing", connector="push", config={}, mapping={})
            db.add(src)
            db.flush()
            db.add(MetricValue(metric_code=ind["metric_code"], org_unit_code="north", period_type="year",
                               period_start=date.fromisoformat(year["start_date"]), value=81, source_id=src.id))
            db.commit()
        finally:
            db.close()
        body = {"plan_id": pid, "period_id": year["id"], "org_unit_code": "north", "holder": "nate", "supervisor": "planner",
                "items": [{"indicator_id": ind["id"], "weight": 100}]}
        self.assertEqual(self.status("post", "/api/people/contracts", self.planner, body), 403)
        c = self.post("/api/people/contracts", self.hr, body, 201)
        url = f"/api/people/contracts/{c['id']}/transition"
        self.assertEqual(self.status("post", url, self.planner, {"name": "sign"}), 403)
        self.post(url, self.nate, {"name": "sign"})
        self.post(url, self.planner, {"name": "countersign"})
        self.assertEqual(self.status("post", url, self.planner, {"name": "evaluate"}), 409)   # no approved scheme
        scheme = self.get("/api/scorecard/schemes", self.planner)[0]
        self.post(f"/api/scorecard/schemes/{scheme['id']}/transition", self.planner, {"name": "approve"})
        ev = self.post(url, self.planner, {"name": "evaluate"})
        self.assertEqual(ev["evaluation"]["items"][0]["achievement"], 90)                   # 81 / 90
        self.assertEqual((ev["final_rating"], ev["final_label"]), (3, "Nearly achieved"))
        self.post(url, self.nate, {"name": "appeal", "reason": "Target set before the tariff freeze."})
        self.assertEqual(self.status("post", url, self.planner, {"name": "decide", "reason": "x"}), 403)
        out = self.post(url, self.hr, {"name": "decide", "reason": "Appeal upheld in part.", "adjusted_rating": 3.5})
        self.assertEqual((out["status"], out["final_rating"]), ("closed", 3.5))
        self.assertEqual(self.status("get", f"/api/people/contracts/{c['id']}", self.nora), 404)


if __name__ == "__main__":
    unittest.main()
