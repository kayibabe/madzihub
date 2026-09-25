"""The populated review year (tests/fixtures/populated_year.py) and its isolated builder.

The dataset must be internally consistent, contain each declared data state exactly
where the manifest says, and drive the missing-data contract through the real API.
The builder must never touch the working database.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import unittest
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from scripts import build_review_dataset as builder
from tests._app_loader import TemporaryDirectory, fresh_app
from tests._fixture import AppFixture
from tests.fixtures import populated_year as py

ROOT = Path(__file__).resolve().parent.parent
FY = py.POPULATED_FY


def by_scheme(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["scheme"]].append(r)
    return out


class DatasetShapeTest(unittest.TestCase):
    rows = py.build_rows()

    def test_periods_and_cases(self):
        schemes = by_scheme(self.rows)
        full = py.POPULATED_MONTHS + py.CURRENT_FY_MONTHS
        for name in py.CASES["complete"] + py.CASES["measured_zero"] + py.CASES["partial"]:
            self.assertEqual([(r["year"], r["month_no"]) for r in schemes[name]], full, name)
        valley = [(r["year"], r["month_no"]) for r in schemes["Valley"]]
        self.assertEqual(valley, [p for p in py.POPULATED_MONTHS if p <= py.STALE_LAST_MONTH])
        self.assertEqual(max((r["year"], r["month_no"]) for r in self.rows), (2026, 8))    # nothing from September 2026
        self.assertEqual(len(self.rows), 7 * 14 + 6)
        self.assertEqual({r["fiscal_year"] for r in self.rows}, {"FY2025/26", "FY2026/27"})

    def test_deterministic(self):
        self.assertEqual(py.build_rows(), self.rows)

    def test_scale_follows_the_demo_budget(self):
        fy = [r for r in self.rows if (r["year"], r["month_no"]) in py.POPULATED_MONTHS]
        produced = sum(r["vol_produced"] for r in fy)
        self.assertTrue(3.8e6 < produced < 4.6e6, produced)
        self.assertTrue(27 < sum(r["nrw"] for r in fy) / produced * 100 < 33)

    def test_relationships_hold_in_every_entered_return(self):
        cats = py.CATEGORIES
        for r in self.rows:
            key = (r["scheme"], r["year"], r["month_no"])
            self.assertAlmostEqual(r["revenue_water"] + r["nrw"], r["vol_produced"], delta=0.2, msg=key)
            self.assertAlmostEqual(r["pct_nrw"], r["nrw"] / r["vol_produced"] * 100, delta=0.01, msg=key)
            self.assertEqual(r["all_conn_cfwd"], r["all_conn_bfwd"] + r["new_connections"], key)
            self.assertLessEqual(r["active_customers"], r["total_metered"], key)
            self.assertEqual(r["total_disconnected"], r["total_metered"] - r["active_customers"], key)
            self.assertLessEqual(r["all_stuck_cfwd"], r["total_metered"], key)
            for c in cats:
                self.assertEqual(r[f"stuck_{c}_cfwd"], r[f"stuck_{c}_bfwd"] + r[f"stuck_{c}_new"]
                                 - r[f"stuck_{c}_repaired"] - r[f"stuck_{c}_replaced"], key)
            self.assertLessEqual(r["supply_hours"], 24, key)
            for k in ("cl", "turbidity", "bact", "ph"):
                self.assertLessEqual(r[f"wq_{k}_compliant"], r[f"wq_{k}_samples"], key)
            if r["pipe_breakdowns"] is not None:
                self.assertEqual(r["pipe_breakdowns"], r["pipe_pvc"] + r["pipe_gi"] + r["pipe_di"] + r["pipe_hdpe_ac"], key)
            if r["amt_billed"] is not None:
                self.assertAlmostEqual(r["amt_billed"], sum(r[f"amt_billed_{c}_pp"] for c in cats), delta=0.05, msg=key)
                self.assertAlmostEqual(r["cash_collected"], sum(r[f"cash_coll_{c}_pp"] for c in cats), delta=0.05, msg=key)
            if r["op_cost"] is not None:
                parts = ("chem_cost", "power_cost", "fuel_cost", "maintenance", "staff_costs", "wages", "other_overhead")
                self.assertAlmostEqual(r["op_cost"], sum(r[p] for p in parts), delta=0.05, msg=key)
        for rows in by_scheme(self.rows).values():                    # balances roll forward
            for prev, cur in zip(rows, rows[1:]):
                self.assertEqual(cur["all_conn_bfwd"], prev["all_conn_cfwd"])
                self.assertEqual(cur["stuck_meters"], prev["all_stuck_cfwd"])

    def test_measured_zero_is_zero_not_missing(self):
        for r in by_scheme(self.rows)["Ridgeway"]:
            for f in py.MEASURED_ZERO_FIELDS:
                self.assertEqual(r[f], 0, f)
                self.assertIsNotNone(r[f])

    def test_missing_values_only_where_declared(self):
        for r in self.rows:
            period = (r["year"], r["month_no"])
            nulls = {k for k, v in r.items() if v is None}
            if r["scheme"] not in py.CASES["partial"]:
                self.assertEqual(nulls, set(), r["scheme"])
                continue
            self.assertTrue(set(py.PARTIAL_STAFF_FIELDS) <= nulls)
            self.assertEqual("amt_billed" in nulls, period in py.PARTIAL_BILLING_MONTHS, period)
            self.assertEqual("pipe_breakdowns" in nulls, period in py.PARTIAL_BREAKDOWN_MONTHS, period)
        self.assertTrue(any(r["scheme"] == "Southport" and r["pct_nrw"] > 35 for r in self.rows))   # a poor performer exists


class DatasetThroughApiTest(AppFixture):
    """The declared cases reach the screens' data as complete, measured zero or Not assessed."""

    def setUp(self):
        super().setUp()
        with self.db() as s:
            py.load(s, self.database.Record)
            s.commit()

    def reports(self, q):
        base = f"?year={FY}{q}"
        return (self.get(f"/api/reports/board-pack{base}", self.admin)["executive_kpis"],
                self.get(f"/api/reports/infrastructure{base}", self.admin),
                self.get(f"/api/reports/hra{base}", self.admin)["summary"])

    def test_nulls_are_stored_as_not_entered(self):
        with self.db() as s:
            R = self.database.Record
            lake = s.query(R).filter_by(scheme="Lakeshore", year=2025, month_no=10).one()
            self.assertIsNone(lake.pipe_breakdowns)
            self.assertIsNone(lake.perm_staff)
            self.assertEqual(s.query(R).filter_by(scheme="Ridgeway", pipe_breakdowns=0).count(), 14)

    def test_complete_zone_is_assessed_everywhere(self):
        kpis, infra, hra = self.reports("&zones=North")
        self.assertEqual(infra["record_count"], 36)
        for key, flag in (("nrw_pct", "nrw_flag"), ("collection_rate", "collection_rate_flag"),
                          ("op_ratio", "op_ratio_flag"), ("dso", "dso_flag")):
            self.assertIsNotNone(kpis[key], key)
            self.assertIn(kpis[flag], ("GOOD", "WATCH", "HIGH"), key)
        self.assertIsNotNone(infra["summary"]["breakdowns_per_1k_customers"])
        self.assertIsNotNone(hra["payroll_cost_ratio"])

    def test_measured_zero_is_assessed_as_zero(self):
        kpi = self.get(f"/api/panels/breakdowns?year={FY}&schemes=Ridgeway", self.admin)["kpi"]
        self.assertEqual(kpi["total"], 0)
        self.assertEqual(kpi["per_1k_customers"], 0.0)

    def test_partial_zone_is_not_assessed_where_inputs_are_missing(self):
        kpis, infra, hra = self.reports("&zones=South")
        self.assertIsNotNone(kpis["nrw_pct"])                       # volumes were entered
        for key in ("collection_rate", "op_ratio", "dso"):
            self.assertIsNone(kpis[key], key)
            self.assertEqual(kpis[f"{key}_flag"], "NOT ASSESSED", key)
        self.assertIsNone(infra["summary"]["breakdowns_per_1k_customers"])
        self.assertIsNone(hra["payroll_cost_ratio"])
        # January-March has billing for every South scheme, so collection is assessed there.
        kpis, _, _ = self.reports("&zones=South&months=January,February,March")
        self.assertIsNotNone(kpis["collection_rate"])

    def test_empty_scope_assesses_nothing(self):
        infra = self.get(f"/api/reports/infrastructure?year={FY + 2}", self.admin)
        self.assertEqual(infra["record_count"], 0)
        self.assertIsNone(infra["summary"]["breakdowns_per_1k_customers"])
        self.assertIsNone(infra["summary"]["stuck_pct"])


class BuilderSafetyTest(unittest.TestCase):
    def test_refuses_the_working_data_folder(self):
        # replace=False throughout: a regression here must not be able to delete anything.
        for target in (ROOT / "data", ROOT / "data" / "review-dataset-guard"):
            with self.assertRaises(SystemExit) as refused:
                builder._prepare(target.resolve(), replace=False)
            self.assertIn("working database", str(refused.exception))
        self.assertFalse((ROOT / "data" / "review-dataset-guard").exists())

    def test_refuses_a_folder_it_did_not_build(self):
        with TemporaryDirectory() as tmp:
            keep = Path(tmp) / "keep.txt"
            keep.write_text("not ours", encoding="utf-8")
            with self.assertRaises(SystemExit):
                builder._prepare(Path(tmp), replace=False)
            with self.assertRaises(SystemExit):
                builder._prepare(Path(tmp), replace=True)
            self.assertTrue(keep.exists())

    def test_replace_removes_read_only_evidence(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "review"
            builder._prepare(out, replace=False)
            evidence = out / "files" / "ab" / "evidence"
            evidence.parent.mkdir(parents=True)
            evidence.write_bytes(b"x")
            os.chmod(evidence, stat.S_IREAD)
            builder._prepare(out, replace=True)
            self.assertFalse(evidence.exists())
            self.assertTrue((out / builder.MARKER).exists())


class BuilderEndToEndTest(unittest.TestCase):
    def setUp(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))

    def test_builds_an_isolated_populated_database(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "review"
            env = {k: v for k, v in os.environ.items() if not k.startswith("MADZI_") and k != "DATABASE_URL"}
            done = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_review_dataset.py"), "--out", str(out)],
                                  cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["records_loaded"], len(py.build_rows()))
            self.assertEqual({s["expected_freshness"] for s in manifest["sources"]}, {"current", "overdue", "failed"})
            with closing(sqlite3.connect(out / builder.DB_NAME)) as c:
                self.assertEqual(c.execute("select count(*) from records").fetchone()[0], manifest["records_loaded"])
                users = {u for (u,) in c.execute("select username from users")}
                self.assertTrue({"admin", "planner", "north.ops", "north.mgr", "south.mgr"} <= users)
                self.assertEqual(c.execute("select count(*) from records where scheme='Lakeshore' and perm_staff is null")
                                 .fetchone()[0], 14)
                # The legacy bridge published every entered value, and nothing for values not entered.
                published = ("vol_produced", "revenue_water", "nrw", "new_connections", "active_customers",
                             "amt_billed", "cash_collected")
                entered = sum(r[m] is not None for r in py.build_rows() for m in published)
                self.assertEqual(c.execute("select v.count from (select count(*) count from metric_values mv join "
                                           "data_sources s on s.id = mv.source_id where s.code='legacy-returns') v")
                                 .fetchone()[0], entered)
            # Freshness as the app computes it, from the built database.
            os.environ.update({"DATABASE_URL": f"sqlite:///{(out / builder.DB_NAME).as_posix()}",
                               "MADZI_SECRET_FILE": str(out / "secret"), "MADZI_FILE_STORE": str(out / "files"),
                               "MADZI_TENANT": "demo", "MADZI_ENV": "development"})
            _, database, _, _ = fresh_app()
            from app.integration import position
            with database.SessionLocal() as db:
                states = {s["code"]: s["freshness"] for s in position.freshness(db)}
            self.assertEqual({k: states[k] for k in ("billing-export", "scada-daily", "lims-results")},
                             {"billing-export": "current", "scada-daily": "overdue", "lims-results": "failed"})


if __name__ == "__main__":
    unittest.main()
