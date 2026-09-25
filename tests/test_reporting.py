"""Reporting hub: frozen instances, approval rules, stored hashed outputs, access log and scope."""
from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import text

from tests.test_scorecard import ScorecardFixture


class ReportingFixture(ScorecardFixture):
    def setUp(self):
        super().setUp()
        self.report(self.i_cov, 99)
        self.report(self.i_nrw, 30)
        self.tpl = {t["kind"]: t["id"] for t in self.get("/api/reports-hub/templates", self.planner)}

    def approve_score(self):
        scheme = self.get("/api/scorecard/schemes", self.planner)[0]
        if scheme["status"] == "draft":
            self.post(f"/api/scorecard/schemes/{scheme['id']}/transition", self.planner, {"name": "approve"})
        s = self.post("/api/scorecard/snapshots", self.planner,
                      {"plan_id": self.pid, "period_id": self.q["id"], "org_unit_code": "north"}, 201)
        self.post(f"/api/scorecard/snapshots/{s['id']}/approve", self.nate)
        return s["id"]

    def new(self, kind, h=None, unit="north"):
        return self.post("/api/reports-hub/instances", h or self.planner,
                         {"template_id": self.tpl[kind], "period_id": self.q["id"], "org_unit_code": unit,
                          "plan_id": self.pid}, 201)

    def out(self, rid, fmt, h, download=False):
        return self.c.get(f"/api/reports-hub/instances/{rid}/output/{fmt}?download={'true' if download else 'false'}",
                          headers=h)


class BoardPackTests(ReportingFixture):
    def test_board_pack_needs_an_approved_score_and_a_second_person(self):
        r = self.new("board_pack")
        self.assertEqual((r["status"], r["data_version"], r["score_approved"]), ("draft", 1, False))
        url = f"/api/reports-hub/instances/{r['id']}"
        self.put(f"{url}/commentary", self.planner, {"commentary": {"summary": "Losses rose in Alpha.",
                                                                    "decisions": "Approve meter budget."}})
        self.assertEqual(self.status("put", f"{url}/commentary", self.planner, {"commentary": {"bogus": "x"}}), 422)
        self.post(f"{url}/transition", self.planner, {"name": "submit"})
        r2 = self.c.post(f"{url}/transition", headers=self.nate, json={"name": "approve"})
        self.assertEqual(r2.status_code, 409)
        self.assertIn("score snapshot", r2.json()["detail"])
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "return"}), 422)
        self.post(f"{url}/transition", self.nate, {"name": "return", "reason": "Score not approved yet"})

        snap_id = self.approve_score()
        fresh = self.post(f"{url}/freeze", self.planner)
        self.assertEqual((fresh["data_version"], fresh["score_approved"]), (2, True))
        self.post(f"{url}/transition", self.planner, {"name": "submit"})
        self.assertEqual(self.status("post", f"{url}/transition", self.planner, {"name": "approve"}), 403)   # author
        done = self.post(f"{url}/transition", self.nate, {"name": "approve"})
        self.assertEqual(done["status"], "approved")
        self.assertEqual(sorted(o["format"] for o in done["outputs"]), ["html", "pdf", "xlsx"])
        self.assertEqual(self.status("post", f"{url}/freeze", self.planner), 409)   # frozen for good

        html = self.out(r["id"], "html", self.nick)       # contributor may read approved reports
        self.assertEqual(html.status_code, 200)
        body = html.text
        self.assertIn('<html lang="en">', body)
        self.assertIn("<h2>Executive summary</h2>", body)
        self.assertIn("Losses rose in Alpha.", body)
        self.assertIn(f"Approved snapshot #{snap_id}", body)
        self.assertNotIn("NOT APPROVED", body)
        self.assertIn("default-src 'none'", html.headers["content-security-policy"])
        pdf = self.out(r["id"], "pdf", self.nick, download=True)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertIn("attachment", pdf.headers["content-disposition"])
        xlsx = self.out(r["id"], "xlsx", self.nick, download=True)
        names = zipfile.ZipFile(io.BytesIO(xlsx.content)).namelist()
        self.assertIn("xl/workbook.xml", names)
        # Served from storage: same bytes every time and matching the recorded hash.
        import hashlib
        stored = {o["format"]: o for o in self.get(url, self.planner)["outputs"]}
        self.assertEqual(hashlib.sha256(pdf.content).hexdigest(), stored["pdf"]["sha256"])
        self.assertEqual(self.out(r["id"], "pdf", self.nick, download=True).content, pdf.content)
        log = [e["action"] for e in self.get(url, self.planner)["access_log"]]
        for action in ("created", "frozen", "submitted", "returned", "approved", "generated", "downloaded", "previewed"):
            self.assertIn(action, log)

        # Publish and withdraw are for report managers; withdrawing needs a reason.
        self.assertEqual(self.status("post", f"{url}/transition", self.nate, {"name": "publish"}), 403)
        self.post(f"{url}/transition", self.planner, {"name": "publish"})
        self.assertEqual(self.status("post", f"{url}/transition", self.planner, {"name": "withdraw"}), 422)
        self.post(f"{url}/transition", self.planner, {"name": "withdraw", "reason": "Superseded by revised pack"})
        self.assertIn("NOT APPROVED", self.out(r["id"], "html", self.planner).text)

    def test_stored_output_tampering_is_detected(self):
        self.approve_score()
        r = self.new("scorecard_detail")
        url = f"/api/reports-hub/instances/{r['id']}"
        self.post(f"{url}/transition", self.planner, {"name": "submit"})
        self.post(f"{url}/transition", self.nate, {"name": "approve"})
        from app.modules.reporting.models import ReportOutput
        from app.platform import filestore
        db = self.db()
        try:
            out = db.query(ReportOutput).filter_by(instance_id=r["id"], format="html").one()
            path = Path(filestore.root()) / out.storage_name[:2] / out.storage_name[2:4] / out.storage_name
        finally:
            db.close()
        path.chmod(0o666)
        path.write_bytes(b"<html>forged</html>")
        res = self.out(r["id"], "html", self.planner)
        self.assertEqual(res.status_code, 409)
        self.assertIn("Integrity check failed", res.json()["detail"])


class DraftAndScopeTests(ReportingFixture):
    def test_drafts_are_marked_and_limited_to_authors_and_reviewers(self):
        r = self.new("submission_dq", self.nora)      # a North reviewer may create unit reports
        url = f"/api/reports-hub/instances/{r['id']}"
        html = self.out(r["id"], "html", self.nora).text
        self.assertIn("NOT APPROVED", html)
        self.assertIn("Submissions", html)
        self.assertTrue(self.out(r["id"], "pdf", self.nora).content.startswith(b"%PDF"))
        self.assertEqual(self.status("get", url, self.nick), 404)     # contributor: drafts hidden
        self.assertEqual(self.status("get", url, self.sam), 404)      # other region
        self.assertEqual(self.status("post", "/api/reports-hub/instances", self.nick,
                                     {"template_id": self.tpl["exceptions"], "period_id": self.q["id"],
                                      "org_unit_code": "north", "plan_id": self.pid}), 403)
        self.assertEqual(self.status("post", "/api/reports-hub/instances", self.nora,
                                     {"template_id": self.tpl["exceptions"], "period_id": self.q["id"],
                                      "org_unit_code": "south", "plan_id": self.pid}), 404)
        self.assertEqual([x["id"] for x in self.get("/api/reports-hub/instances", self.sam)], [])
        # South's own exception report never contains North's rows.
        mine = self.new("exceptions", self.planner, unit="south")
        south_html = self.out(mine["id"], "html", self.sue).text
        self.assertNotIn("COVER", south_html)
        with self.database.engine.connect() as conn:
            with self.assertRaises(Exception):
                conn.execute(text("DELETE FROM report_access_log"))

    def test_exception_report_lists_missing_submissions_and_overdue_actions(self):
        from datetime import date, timedelta
        self.post("/api/platform/actions", self.nora, {"title": "Fix leaking valve", "owner": "nick",
                                                       "org_unit_code": "north",
                                                       "due_date": (date.today() - timedelta(days=3)).isoformat()}, 201)
        r = self.new("exceptions")
        blocks_html = self.out(r["id"], "html", self.planner).text
        self.assertIn("Overdue actions", blocks_html)
        self.assertIn("Fix leaking valve", blocks_html)
        self.assertIn("Indicators off target", blocks_html)


if __name__ == "__main__":
    unittest.main()
