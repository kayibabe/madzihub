"""Regulator packs: source-cited drafts, verification blockers, second-officer approval, returns, league tables."""
from __future__ import annotations

import copy
import io
import unittest
import zipfile

from sqlalchemy import text

from tests._access import add_user
from tests._app_loader import TemporaryDirectory
from tests._fixture import AppFixture, boot


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as d:
            boot(d)
        from app.modules.regulatory import engine
        cls.e = engine

    def content(self):
        return {"verification": {"source_checked": True},
                "groups": [{"code": "K", "share_pct": 60, "verified": True}, {"code": "C", "share_pct": 40, "verified": True}],
                "indicators": [
                    {"code": "NRW", "group": "K", "polarity": "lower", "weight": 2, "verified": True,
                     "scoring": {"type": "bands", "bands": [{"max": 25, "points": 10, "label": "good"},
                                                            {"min": 25, "max": 35, "points": 5, "label": "acceptable"},
                                                            {"min": 35, "points": 0, "label": "not acceptable"}]}},
                    {"code": "COV", "group": "K", "polarity": "higher", "weight": 1, "verified": True,
                     "scoring": {"type": "peer_interpolation", "min_points": 0, "median_points": 5, "best_points": 10}},
                    {"code": "LEVY", "group": "C", "polarity": "yes_no", "weight": 1, "verified": True,
                     "scoring": {"type": "yes_no", "points": 10}}]}

    def test_blockers_list_everything_unverified_or_missing(self):
        c = self.content()
        self.assertEqual(self.e.blockers(c), [])
        c["indicators"][0]["verified"] = False
        c["indicators"][1]["weight"] = None
        c["groups"][0]["share_pct"] = 50
        problems = " ".join(self.e.blockers(c))
        for text_ in ("NRW: not verified", "COV: weight missing", "add up to 90"):
            self.assertIn(text_, problems)

    def test_scoring_and_ranking(self):
        c = self.content()
        peers = [{"name": "Peer A", "values": {"NRW": 40, "COV": 60, "LEVY": 0}},
                 {"name": "Peer B", "values": {"NRW": 30, "COV": 90, "LEVY": 1}}]
        out = self.e.league(c, "Us", {"NRW": 22, "COV": 75, "LEVY": 1}, peers)
        us = next(r for r in out["entities"] if r["own"])
        nrw = next(i for i in us["indicators"] if i["code"] == "NRW")
        self.assertEqual((nrw["points"], nrw["label"]), (10, "good"))
        cov = next(i for i in us["indicators"] if i["code"] == "COV")
        self.assertEqual(cov["label"], "above median")      # median of 60, 75, 90 is 75
        self.assertAlmostEqual(cov["points"], 5)
        k = next(g for g in us["groups"] if g["code"] == "K")
        self.assertAlmostEqual(k["score_pct"], (2 * 10 + 5) / 30 * 100, places=3)
        self.assertEqual([r["name"] for r in out["entities"]], ["Us", "Peer B", "Peer A"])
        self.assertEqual([r["rank"] for r in out["entities"]], [1, 2, 3])
        self.assertEqual(self.e.validate_value({"validation": {"min": 0, "max": 100}}, 120), ["above the maximum 100"])


class PackTests(AppFixture):
    def setUp(self):
        super().setUp()
        self.o1 = add_user(self.database, self.auth, "reg1", "user", {"org": "viewer"}, functions=("regulatory_officer",))
        self.o2 = add_user(self.database, self.auth, "reg2", "user", {"org": "viewer"}, functions=("regulatory_officer",))

    def test_shipped_packs_import_as_drafts_that_cannot_be_used_until_verified(self):
        files = {f["file"]: f for f in self.get("/api/regulatory/pack-files", self.o1)}
        self.assertIn("wasreb/impact17-fy2023-24.yaml", files)
        self.assertIn("ewura/fy2023-24.yaml", files)
        self.assertEqual(self.status("post", "/api/regulatory/packs/import", self.nate, {"file": "wasreb/impact17-fy2023-24.yaml"}), 403)
        self.assertEqual(self.status("post", "/api/regulatory/packs/import", self.o1, {"file": "../../tenant.yaml"}), 404)
        for f in files:
            p = self.post("/api/regulatory/packs/import", self.o1, {"file": f}, 201)
            self.assertEqual(p["status"], "draft")
            self.assertTrue(p["blockers"])
            self.assertEqual(p["verified_count"], 0)
            r = self.c.post(f"/api/regulatory/packs/{p['id']}/approve", headers=self.o2, json={})
            self.assertEqual(r.status_code, 409)
            self.assertIn("cannot be approved yet", r.json()["detail"])
            self.assertEqual(self.status("post", "/api/regulatory/returns", self.o1,
                                         {"pack_id": p["id"], "period_label": "FY2025/26"}), 409)
        self.assertEqual(self.status("get", "/api/regulatory/packs", self.nick), 404)     # region user

    def test_verified_pack_second_officer_return_and_league_run(self):
        p = self.post("/api/regulatory/packs/import", self.o1, {"file": "wasreb/impact17-fy2023-24.yaml"}, 201)
        content = copy.deepcopy(p["content"])
        content["verification"]["source_checked"] = True
        for ind in content["indicators"]:
            ind.update(verified=True, weight=1, in_score=ind["code"] in ("NRW", "MR"),
                       scoring={"type": "bands", "bands": [{"max": 50, "points": 0}, {"min": 50, "points": 10}]}
                       if ind["polarity"] == "higher" else
                       {"type": "bands", "bands": [{"max": 25, "points": 10}, {"min": 25, "points": 0}]})
        url = f"/api/regulatory/packs/{p['id']}"
        self.assertEqual(self.status("put", url, self.o1, {"content": content, "reason": " "}), 422)
        edited = self.put(url, self.o1, {"content": content, "reason": "Test figures, not WASREB's"})
        self.assertEqual(edited["blockers"], [])
        self.assertEqual(self.status("post", f"{url}/approve", self.o1, {}), 403)        # importer / editor
        approved = self.post(f"{url}/approve", self.o2, {"note": "Checked"})
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.status("put", url, self.o1, {"content": content, "reason": "x"}), 409)

        r = self.post("/api/regulatory/returns", self.o1, {"pack_id": p["id"], "period_label": "FY2025/26"}, 201)
        rurl = f"/api/regulatory/returns/{r['id']}"
        self.assertEqual(self.status("put", f"{rurl}/values", self.o1, [{"code": "NRW", "value": 130}]), 422)
        self.assertEqual(self.status("post", f"{rurl}/submit", self.o1), 422)             # values missing
        self.put(f"{rurl}/values", self.o1, [{"code": "NRW", "value": 31}, {"code": "MR", "value": 80}])
        self.put(f"{rurl}/values", self.o1, [{"code": "NRW", "value": 22, "note": "Corrected water balance"}])
        # A draft return's values can still change: no saved league table may rest on them.
        league = {"pack_id": p["id"], "return_id": r["id"], "peers": [{"name": "Peer utility", "values": {"NRW": 40, "MR": 60}}]}
        draft_run = self.c.post("/api/regulatory/league-runs", headers=self.o1, json=league)
        self.assertEqual(draft_run.status_code, 409)
        self.assertIn("Submit the return", draft_run.json()["detail"])
        self.assertEqual(self.get("/api/regulatory/league-runs", self.o1), [])
        out = self.post(f"{rurl}/submit", self.o1)
        self.assertEqual((out["status"], out["revisions"]), ("submitted", 3))
        self.assertEqual(next(v for v in out["values"] if v["code"] == "NRW")["value"], 22)
        self.assertEqual(self.status("put", f"{rurl}/values", self.o1, [{"code": "NRW", "value": 20}]), 409)
        x = self.c.get(f"{rurl}/export", headers=self.vic)
        self.assertEqual(x.status_code, 200)
        self.assertIn("xl/workbook.xml", zipfile.ZipFile(io.BytesIO(x.content)).namelist())
        run = self.post("/api/regulatory/league-runs", self.o1, league, 201)
        self.assertEqual(run["results"]["entities"][0]["own"], True)
        self.assertIn("not an official", run["note"])
        with self.database.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM return_values")).scalar(), 3)


if __name__ == "__main__":
    unittest.main()
