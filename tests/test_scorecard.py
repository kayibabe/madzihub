"""Scorecard: the pure engine, scheme sign-off, weights, snapshots, overrides and the quarterly review."""
from __future__ import annotations

import unittest
from datetime import date

from tests._fixture import AppFixture, boot
from tests._app_loader import TemporaryDirectory


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as d:
            boot(d)
        from app.modules.scorecard import engine as e
        cls.e = e
        cls.bands = tuple(e.Band(*b) for b in [(5, "Exceeded", 110.0, None), (4, "Achieved", 100.0, 110.0),
                                               (3, "Nearly", 90.0, 100.0), (2, "Below", 70.0, 90.0),
                                               (1, "Well below", 0.0, 70.0)])
        cls.s = e.Scheme(bands=cls.bands)

    def a(self, *args, scheme=None, **kw):
        return self.e.achievement(*args, scheme=scheme or self.s, **kw)

    def test_higher_is_better_keeps_uncapped_and_caps_for_rating(self):
        self.assertEqual((self.a("higher", 90, 100).capped, self.a("higher", 90, 100).uncapped), (90, 90))
        r = self.a("higher", 150, 100)
        self.assertEqual((r.uncapped, r.capped), (150, 130))
        self.assertIn("cap", r.note)
        self.assertEqual(self.a("higher", -5, 100).capped, 0)

    def test_lower_is_better_methods_and_floors(self):
        self.assertAlmostEqual(self.a("lower", 30, 25).capped, 80)          # (2 - 30/25) * 100
        r = self.a("lower", 10, 25)
        self.assertEqual((r.uncapped, r.capped), (160, 130))
        self.assertEqual(self.a("lower", 60, 25).capped, 0)                # not below zero
        inv = self.e.Scheme(bands=self.bands, lower_method="ratio_inverse")
        self.assertAlmostEqual(self.a("lower", 30, 25, scheme=inv).capped, 83.333333, places=5)
        zero = self.a("lower", 0, 25, scheme=inv)
        self.assertEqual((zero.uncapped, zero.capped), (None, 130))       # infinite: best, rated at the cap

    def test_zero_and_negative_targets_follow_the_scheme_rule(self):
        self.assertFalse(self.a("lower", 3, 0).scored)                     # default: unscored, not divided
        binary = self.e.Scheme(bands=self.bands, zero_target_rule="binary")
        self.assertEqual(self.a("lower", 0, 0, scheme=binary).capped, 100)
        self.assertEqual(self.a("lower", 2, 0, scheme=binary).capped, 0)
        self.assertEqual(self.a("higher", 4, 0, scheme=binary).capped, 100)
        self.assertFalse(self.a("higher", 4, -10).scored)

    def test_range_milestone_yes_no_and_kri_have_their_own_rules(self):
        self.assertEqual(self.a("range", 7.0, 7.2, lower=6.5, upper=8.5).capped, 100)
        self.assertAlmostEqual(self.a("range", 6.0, 7.2, lower=6.5, upper=8.5).capped, 75)   # 0.5 of a 2.0 width
        self.assertEqual(self.a("range", 1.0, 7.2, lower=6.5, upper=8.5).capped, 0)
        self.assertFalse(self.a("range", 7, 7).scored)                                      # bounds required
        self.assertEqual(self.a("milestone", 80, 60).capped, 100)                            # never above 100
        self.assertEqual(self.a("milestone", 30, 60).capped, 50)
        self.assertEqual((self.a("yes_no", 1, 1).capped, self.a("yes_no", 0, 1).capped), (100, 0))
        self.assertEqual(self.a("kri", 4, 5, upper=8).capped, 100)
        self.assertEqual(self.a("kri", 6, 5, upper=8).capped, 50)
        self.assertEqual(self.a("kri", 9, 5, upper=8).capped, 0)
        self.assertFalse(self.a("higher", None, 5).scored)
        self.assertFalse(self.a("sideways", 1, 1).scored)

    def test_bands_rate_on_boundaries_and_are_validated(self):
        rate = lambda v: self.e.rate(v, self.s).rating
        self.assertEqual([rate(0), rate(69.99), rate(70), rate(99.999), rate(100), rate(110), rate(130)],
                         [1, 1, 2, 3, 4, 5, 5])
        self.assertEqual(self.e.validate_bands(self.bands, 130), [])
        gap = (self.e.Band(5, "a", 110, None), self.e.Band(4, "b", 100, 105), self.e.Band(3, "c", 90, 100),
               self.e.Band(2, "d", 70, 90), self.e.Band(1, "e", 0, 70))
        self.assertTrue(any("must end where" in x for x in self.e.validate_bands(gap, 130)))
        self.assertTrue(self.e.validate_bands(self.bands[:4], 130))
        mixed = (self.e.Band(5, "a", 110, None), self.e.Band(1, "b", 100, 110), self.e.Band(3, "c", 90, 100),
                 self.e.Band(2, "d", 70, 90), self.e.Band(4, "e", 0, 70))
        self.assertTrue(any("one direction" in x for x in self.e.validate_bands(mixed, 130)))
        capped_top = self.bands[1:] + (self.e.Band(5, "x", 110, 120),)
        self.assertTrue(any("above the cap" in x for x in self.e.validate_bands(capped_top, 130)))

    def C(self, key, w, ach, rating, state="scored"):
        return self.e.Child(key, key, w, ach, rating, state)

    def test_rollup_is_weighted_and_reports_its_coverage(self):
        r = self.e.rollup([self.C("a", 60, 100, 4), self.C("b", 40, 80, 2)], self.s)
        self.assertEqual((r.status, r.achievement, r.rating, r.covered_weight), ("complete", 92, 3.2, 100))
        self.assertEqual(sum(c["share_of_score"] for c in r.contributions), 92)

    def test_missing_data_is_never_silently_rescaled_or_zeroed(self):
        below = self.e.rollup([self.C("a", 60, 100, 4), self.C("b", 40, None, None, "no_value")],
                              self.e.Scheme(bands=self.bands, coverage_gate_pct=80))
        self.assertEqual((below.status, below.achievement, below.covered_weight), ("incomplete", None, 60))
        self.assertEqual([m["key"] for m in below.missing], ["b"])
        above = self.e.rollup([self.C("a", 85, 100, 4), self.C("b", 15, None, None, "no_value")],
                              self.e.Scheme(bands=self.bands, coverage_gate_pct=80))
        self.assertEqual((above.status, above.achievement), ("partial", 100))
        self.assertIn("85.0 % of weight", above.method)
        zeroed = self.e.rollup([self.C("a", 60, 100, 4), self.C("b", 40, None, None, "no_value")],
                               self.e.Scheme(bands=self.bands, missing_policy="count_as_zero"))
        self.assertEqual((zeroed.achievement, zeroed.rating), (60, 2.8))
        self.assertIn("scheme rule", zeroed.method)

    def test_not_applicable_items_leave_the_weights_visibly(self):
        r = self.e.rollup([self.C("a", 50, 100, 4), self.C("b", 50, None, None, "not_applicable")], self.s)
        self.assertEqual((r.status, r.achievement, r.total_weight, r.excluded_weight), ("complete", 100, 50, 50))
        self.assertIn("excluded", r.method)

    def test_weights_must_sum_to_100_or_be_left_blank(self):
        self.assertEqual(self.e.rollup([self.C("a", 60, 100, 4), self.C("b", 30, 80, 2)], self.s).status,
                         "invalid_weights")
        self.assertEqual(self.e.rollup([self.C("a", 60, 100, 4), self.C("b", None, 80, 2)], self.s).status,
                         "invalid_weights")
        eq = self.e.rollup([self.C("a", None, 100, 4), self.C("b", None, 80, 2)], self.s)
        self.assertEqual((eq.weighting, eq.achievement), ("equal", 90))

    def test_tree_overrides_propagate_and_keep_the_calculated_value(self):
        inputs = {"nodes": [{"key": "n1", "parent": None, "code": "P1", "title": "P", "node_type": "pillar", "weight": None}],
                  "indicators": [{"key": "i1", "node": "n1", "code": "A", "name": "A", "polarity": "higher", "weight": None,
                                  "state": "measured", "actual": 80, "target": 100}]}
        plain = self.e.evaluate_tree(inputs, self.s)
        self.assertEqual((plain["items"]["i1"]["rating"], plain["root"]["rating"]), (2, 2))
        over = self.e.evaluate_tree(inputs, self.s, {"i1": {"rating": 4, "reason": "Meter error"}})
        self.assertEqual((over["items"]["i1"]["rating"], over["items"]["i1"]["calculated_rating"]), (4, 2))
        self.assertEqual(over["root"]["rating"], 4)
        self.assertEqual(over["items"]["i1"]["achievement"], 80)       # the calculation stays visible

    def test_nested_items_roll_up_level_by_level(self):
        """pillar → objective (60) + objective (40); one objective has no data this period."""
        inputs = {"nodes": [
            {"key": "n1", "parent": None, "code": "P1", "title": "P", "node_type": "pillar", "weight": None},
            {"key": "n2", "parent": "n1", "code": "O1", "title": "O1", "node_type": "objective", "weight": 60},
            {"key": "n3", "parent": "n1", "code": "O2", "title": "O2", "node_type": "objective", "weight": 40},
            {"key": "n4", "parent": "n1", "code": "O3", "title": "O3 annual", "node_type": "objective", "weight": 0}],
            "indicators": [
                {"key": "i1", "node": "n2", "code": "A", "name": "A", "polarity": "higher", "weight": None,
                 "state": "measured", "actual": 105, "target": 100},
                {"key": "i2", "node": "n3", "code": "B", "name": "B", "polarity": "higher", "weight": None,
                 "state": "no_value"},
                {"key": "i3", "node": "n4", "code": "C", "name": "C", "polarity": "higher", "weight": None,
                 "state": "not_due"}]}
        out = self.e.evaluate_tree(inputs, self.s)
        self.assertEqual((out["items"]["n2"]["status"], out["items"]["n2"]["rating"]), ("complete", 4))
        self.assertEqual(out["items"]["n3"]["status"], "incomplete")
        self.assertEqual(out["items"]["n4"]["status"], "empty")          # only not-due items: excluded above
        pillar = out["items"]["n1"]
        self.assertEqual((pillar["status"], pillar["covered_weight"]), ("incomplete", 60))
        self.assertEqual([m["key"] for m in pillar["missing"]], ["n3"])
        self.assertEqual([x["key"] for x in pillar["excluded"]], ["n4"])
        # With O2 measured the pillar is complete and O3 stays excluded, not zero.
        inputs["indicators"][1].update(state="measured", actual=80, target=100)
        pillar = self.e.evaluate_tree(inputs, self.s)["items"]["n1"]
        self.assertEqual((pillar["status"], pillar["achievement"], pillar["rating"]), ("complete", 95, 3.2))

    def test_inputs_hash_is_stable(self):
        h = self.e.inputs_hash
        self.assertEqual(h({"b": 1, "a": [1, 2]}), h({"a": [1, 2], "b": 1}))
        self.assertNotEqual(h({"a": 1}), h({"a": 2}))


class ScorecardFixture(AppFixture):
    def setUp(self):
        super().setUp()
        p = self.post("/api/strategy/plans", self.planner, {"code": "SP", "title": "Plan", "start_fy": 2027, "end_fy": 2030}, 201)
        self.pid = p["id"]
        self.pillar = self.post(f"/api/strategy/plans/{self.pid}/nodes", self.planner,
                                {"node_type": "pillar", "code": "P1", "title": "Service"}, 201)["id"]
        mk = lambda code, pol, w: self.post(f"/api/strategy/plans/{self.pid}/indicators", self.planner, {
            "code": code, "name": code, "node_id": self.pillar, "polarity": pol, "frequency": "quarter",
            "reporting_units": ["north"], "weight": w}, 201)["id"]
        self.i_cov = mk("COVER", "higher", 60)
        self.i_nrw = mk("NRW", "lower", 40)
        self.q = next(x for x in self.get("/api/platform/periods?period_type=quarter", self.planner)
                      if x["start_date"] <= date.today().isoformat() <= x["end_date"])
        for iid, val in ((self.i_cov, 90), (self.i_nrw, 25)):
            self.put(f"/api/strategy/indicators/{iid}/targets", self.planner, {"targets": [
                {"period_type": "quarter", "period_start": self.q["start_date"], "value": val, "org_unit_code": "north"}]})
        self.post(f"/api/strategy/plans/{self.pid}/transition", self.planner, {"name": "activate"})
        c = self.post(f"/api/strategy/plans/{self.pid}/cycles", self.planner, {"period_id": self.q["id"]}, 201)
        self.post(f"/api/strategy/cycles/{c['id']}/generate", self.planner)
        self.post(f"/api/strategy/cycles/{c['id']}/transition", self.planner, {"name": "open"})
        self.assign = {a["indicator"]["id"]: a["id"] for a in
                       self.get(f"/api/strategy/assignments?cycle_id={c['id']}&queue=all", self.planner)}

    def report(self, iid, value, approve=True):
        aid = self.assign[iid]
        self.post(f"/api/strategy/assignments/{aid}/submit", self.nick, {"value": value, "variance_reason": "n/a"}, 201)
        if approve:
            self.post(f"/api/strategy/assignments/{aid}/transition", self.nora, {"name": "verify"})
            self.post(f"/api/strategy/assignments/{aid}/transition", self.nate, {"name": "approve"})

    def preview(self, h=None):
        return self.get(f"/api/scorecard/preview?plan_id={self.pid}&period_id={self.q['id']}&org_unit=north",
                        h or self.planner)


class QuarterlyReviewExitTest(ScorecardFixture):
    def test_full_quarterly_review_submit_verify_approve_snapshot_lock(self):
        self.report(self.i_cov, 99)       # 110 % of target
        self.report(self.i_nrw, 30)       # lower is better: (2 - 30/25) = 80 %
        live = self.preview()
        items = live["tree"]["items"]
        self.assertEqual((items[f"i{self.i_cov}"]["achievement"], items[f"i{self.i_cov}"]["rating_label"]),
                         (110, "Exceeded"))
        self.assertEqual((items[f"i{self.i_nrw}"]["achievement"], items[f"i{self.i_nrw}"]["rating"]), (80, 2))
        root = live["tree"]["root"]
        self.assertEqual((root["status"], root["achievement"], root["rating"]), ("complete", 98, 3.8))
        self.assertTrue(live["provisional"])                  # default scheme not yet signed off

        schemes = self.get("/api/scorecard/schemes", self.planner)
        self.assertEqual([(s["code"], s["status"]) for s in schemes], [("madzihub-default", "draft")])
        snap = self.post("/api/scorecard/snapshots", self.planner,
                         {"plan_id": self.pid, "period_id": self.q["id"], "org_unit_code": "north"}, 201)
        self.assertTrue(snap["provisional"])
        self.assertEqual(self.status("post", f"/api/scorecard/snapshots/{snap['id']}/approve", self.nate), 409)

        # Sign-off: by a strategy manager who is not the author (the default was created by the system).
        self.post(f"/api/scorecard/schemes/{schemes[0]['id']}/transition", self.planner, {"name": "approve"})
        snap = self.post("/api/scorecard/snapshots", self.planner,
                         {"plan_id": self.pid, "period_id": self.q["id"], "org_unit_code": "north"}, 201)
        self.assertFalse(snap["provisional"])
        # Traceability: value and target ids, and a hash that matches the frozen inputs.
        inp = next(i for i in snap["inputs"]["indicators"] if i["id"] == self.i_cov)
        self.assertTrue(inp["value_refs"] and inp["target_id"])
        self.assertEqual(inp["dq"]["fails"], 0)
        from app.modules.scorecard import engine
        self.assertEqual(snap["inputs_hash"], engine.inputs_hash(
            {"inputs": snap["inputs"], "scheme": snap["scheme"], "engine": engine.ENGINE_VERSION}))
        self.assertEqual(self.status("post", f"/api/scorecard/snapshots/{snap['id']}/approve", self.planner), 403)
        approved = self.post(f"/api/scorecard/snapshots/{snap['id']}/approve", self.nate, {"note": "Q review"})
        self.assertEqual((approved["status"], approved["rating"], approved["approved_by"]), ("approved", 3.8, "nate"))
        self.assertEqual(self.status("post", f"/api/scorecard/snapshots/{snap['id']}/override", self.planner,
                                     {"key": f"i{self.i_nrw}", "rating": 4, "reason": "x"}), 409)

        # Recalculation makes a new snapshot; an override needs a reason and propagates upward.
        again = self.post("/api/scorecard/snapshots", self.planner,
                          {"plan_id": self.pid, "period_id": self.q["id"], "org_unit_code": "north"}, 201)
        self.assertEqual(self.status("post", f"/api/scorecard/snapshots/{again['id']}/override", self.planner,
                                     {"key": f"i{self.i_nrw}", "rating": 4, "reason": " "}), 422)
        over = self.post(f"/api/scorecard/snapshots/{again['id']}/override", self.planner,
                         {"key": f"i{self.i_nrw}", "rating": 4, "reason": "Bulk meter under-registered; NRW overstated"})
        self.assertEqual(over["rating"], 4.6)
        self.assertEqual(over["tree"]["items"][f"i{self.i_nrw}"]["calculated_rating"], 2)
        self.post(f"/api/scorecard/snapshots/{again['id']}/approve", self.nate)
        first = self.get(f"/api/scorecard/snapshots/{snap['id']}", self.planner)
        self.assertEqual(first["status"], "superseded")        # never rewritten, only superseded
        self.assertEqual(first["rating"], 3.8)

        # Lock the period: no more snapshots or approvals for it.
        year = next(p for p in self.get("/api/platform/periods?period_type=year", self.admin)
                    if p["fiscal_year"] == self.q["fiscal_year"])
        self.post(f"/api/platform/periods/{self.q['id']}/lock", self.admin, {"reason": "Quarter closed"})
        self.assertEqual(self.status("post", "/api/scorecard/snapshots", self.planner,
                                     {"plan_id": self.pid, "period_id": self.q["id"], "org_unit_code": "north"}), 409)
        self.assertTrue(year)
        # Region isolation: South cannot see North's scores.
        self.assertEqual(self.status("get", f"/api/scorecard/snapshots/{snap['id']}", self.sam), 404)
        self.assertEqual(self.get("/api/scorecard/snapshots", self.sam), [])
        trail = self.get("/api/platform/audit?entity_type=score_snapshot", self.admin)
        self.assertIn("score_snapshot.override", [e["action"] for e in trail])


class CoverageAndWeightsTests(ScorecardFixture):
    def test_incomplete_when_coverage_is_below_the_gate(self):
        self.report(self.i_cov, 99)
        self.report(self.i_nrw, 30, approve=False)        # submitted, not approved: no published value
        tree = self.preview()["tree"]
        pillar = tree["items"][f"n{self.pillar}"]
        self.assertEqual((pillar["status"], pillar["achievement"], pillar["covered_weight"]), ("incomplete", None, 60))
        self.assertEqual([m["key"] for m in pillar["missing"]], [f"i{self.i_nrw}"])
        self.assertIn("below the scheme's 80 % gate", pillar["method"])
        # An incomplete pillar is missing at the plan level too: nothing is scored as zero.
        root = tree["root"]
        self.assertEqual((root["status"], root["achievement"]), ("incomplete", None))
        self.assertEqual([m["key"] for m in root["missing"]], [f"n{self.pillar}"])

    def test_incomplete_score_is_signed_off_only_as_an_explicit_override(self):
        self.report(self.i_cov, 99)
        self.report(self.i_nrw, 30, approve=False)        # 60 % coverage, below the 80 % gate
        scheme = self.get("/api/scorecard/schemes", self.planner)[0]
        self.post(f"/api/scorecard/schemes/{scheme['id']}/transition", self.planner, {"name": "approve"})
        snap = self.post("/api/scorecard/snapshots", self.planner,
                         {"plan_id": self.pid, "period_id": self.q["id"], "org_unit_code": "north"}, 201)
        url = f"/api/scorecard/snapshots/{snap['id']}"
        view = self.get(url, self.nate)
        self.assertFalse(view["can_approve"])
        self.assertIn("incomplete", view["approval_blocker"])
        r = self.c.post(f"{url}/approve", headers=self.nate, json={})
        self.assertEqual(r.status_code, 409)
        self.assertIn("overall-rating override", r.json()["detail"])
        self.assertEqual(self.get(url, self.nate)["status"], "draft")
        # The exception: an overall-rating override, with a reason, then a second person signs off.
        self.post(f"{url}/override", self.planner, {"key": "plan", "rating": 3,
                                                    "reason": "NRW return delayed by the regulator; board accepts COVER alone"})
        view = self.get(url, self.nate)
        self.assertEqual((view["can_approve"], view["approval_blocker"]), (True, None))
        done = self.post(f"{url}/approve", self.nate)
        self.assertEqual((done["status"], done["rating"], done["tree"]["root"]["status"]), ("approved", 3, "incomplete"))

    def test_weight_editor_enforces_100_per_level(self):
        groups = self.get(f"/api/scorecard/plans/{self.pid}/weights", self.planner)
        level = next(g for g in groups if g["parent_id"] == self.pillar)
        self.assertEqual((level["sum"], level["mode"]), (100, "set"))
        bad = self.c.put(f"/api/scorecard/plans/{self.pid}/weights", headers=self.planner, json={"items": [
            {"type": "indicator", "id": self.i_cov, "weight": 70}]})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("110", bad.json()["detail"])
        ok = self.put(f"/api/scorecard/plans/{self.pid}/weights", self.planner, {"items": [
            {"type": "indicator", "id": self.i_cov, "weight": None}, {"type": "indicator", "id": self.i_nrw, "weight": None}],
            "reason": "Equal weighting agreed"})
        self.assertEqual(next(g for g in ok if g["parent_id"] == self.pillar)["mode"], "equal")
        self.assertEqual(self.status("put", f"/api/scorecard/plans/{self.pid}/weights", self.nate, {"items": []}), 403)

    def test_scheme_versions_need_a_second_person_to_sign_off(self):
        base = self.get("/api/scorecard/schemes", self.planner)[0]
        v2 = self.post("/api/scorecard/schemes", self.planner, {"from_scheme_id": base["id"]}, 201)
        self.assertEqual((v2["version"], v2["status"]), (2, "draft"))
        bands = v2["bands"]
        bands[0]["min_achievement"] = 120            # leaves a gap between 110 and 120
        self.assertEqual(self.status("put", f"/api/scorecard/schemes/{v2['id']}", self.planner, {"bands": bands}), 422)
        self.put(f"/api/scorecard/schemes/{v2['id']}", self.planner, {"cap_pct": 120, "coverage_gate_pct": 100})
        self.assertEqual(self.status("post", f"/api/scorecard/schemes/{v2['id']}/transition", self.planner,
                                     {"name": "approve"}), 403)       # author cannot sign off
        self.assertEqual(self.status("post", f"/api/scorecard/schemes/{v2['id']}/transition", self.admin,
                                     {"name": "approve"}), 200)
        self.assertEqual(self.status("put", f"/api/scorecard/schemes/{v2['id']}", self.planner, {"cap_pct": 125}), 409)


if __name__ == "__main__":
    unittest.main()
