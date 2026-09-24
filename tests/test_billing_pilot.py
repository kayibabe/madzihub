"""Billing pilot pack: the documented configuration works end to end against a simulated billing view.

The "billing system" is a SQLite database holding v_madzi_monthly exactly as the
contract in docs/pilots/BILLING_PILOT.md §3 describes. source.json and
metrics.json are loaded from the pack itself, so the documentation cannot drift
from what the software accepts.
"""
from __future__ import annotations

import json
import os
import sqlite3
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests._app_loader import TemporaryDirectory, fresh_app

PACK = Path(__file__).resolve().parents[1] / "docs" / "pilots" / "billing"

VIEW_ROWS = [
    # branch, month,        billed m3, billed amt, cash,  active, new, disc, updated_at
    ("BR01", "2026-05-01", 1000.0, 5000.0, 4500.0, 400, 5, 2, "2026-06-02T01:00:00"),
    ("BR02", "2026-05-01", 3000.0, 15000.0, 12000.0, 900, 9, 4, "2026-06-02T01:00:00"),
    ("BR01", "2026-06-01", 1100.0, 5500.0, 5000.0, 403, 4, 1, "2026-07-02T01:00:00"),
    ("BR02", "2026-06-01", None, 16000.0, 12500.0, 905, 7, 2, "2026-07-02T01:00:00"),  # volume not known yet
    ("BR99", "2026-06-01", 50.0, 250.0, 200.0, 10, 0, 0, "2026-07-02T01:00:00"),         # branch nobody mapped
]


class BillingPilotPackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        billing = tmp / "billing.db"
        con = sqlite3.connect(billing)
        con.execute("""CREATE TABLE v_madzi_monthly (branch_code TEXT, period_month TEXT, billed_volume_m3 REAL,
                       billed_amount REAL, cash_collected REAL, active_accounts INTEGER, new_connections INTEGER,
                       disconnections INTEGER, updated_at TEXT)""")
        con.executemany("INSERT INTO v_madzi_monthly VALUES (?,?,?,?,?,?,?,?,?)", VIEW_ROWS)
        con.commit()
        con.close()
        self.billing_db = billing
        os.environ["MADZI_SRC_BILLING_DB_URL"] = f"sqlite:///{billing}"
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'hub.db'}"
        os.environ["MADZI_SECRET_FILE"] = str(tmp / "secret")
        os.environ.update({"MADZI_ENV": "development", "MADZI_SECRET_KEY": "k", "MADZI_TENANT": "demo"})
        self.main, self.database, self.auth, _ = fresh_app()
        self.client = TestClient(self.main.app)
        self.client.__enter__()
        db = self.database.SessionLocal()
        db.add(self.database.User(username="boss", password_hash=self.auth.hash_password("x"), role="admin"))
        db.commit()
        db.close()
        self.h = {"Authorization": f"Bearer {self.auth.create_access_token('boss', 'admin')}"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        os.environ.pop("MADZI_SRC_BILLING_DB_URL", None)
        self._tmp.cleanup()

    def call(self, method, url, body=None):
        r = self.client.request(method, url, json=body, headers=self.h)
        self.assertLess(r.status_code, 300, r.text)
        return r.json()

    def _setup_per_guide(self):
        # §4 step 3: catalogue from existing returns, plus the pack's extra measure.
        self.call("POST", "/api/integration/bootstrap-legacy")
        self.call("POST", "/api/integration/org-units", [
            {"code": "north", "name": "North", "unit_type": "region", "parent_code": "org"},
            {"code": "south", "name": "South", "unit_type": "region", "parent_code": "org"}])
        self.call("POST", "/api/integration/metrics", json.loads((PACK / "metrics.json").read_text()))
        # §4 step 4: the source exactly as shipped.
        self.call("POST", "/api/integration/sources", json.loads((PACK / "source.json").read_text()))

    def test_pack_files_are_complete(self):
        for name in ("source.json", "metrics.json", "branch_mapping_template.csv", "reconciliation_template.csv",
                     "v_madzi_monthly.postgresql.sql", "v_madzi_monthly.sqlserver.sql"):
            self.assertTrue((PACK / name).is_file(), name)
        cfg = json.loads((PACK / "source.json").read_text())
        self.assertTrue(cfg["config"]["url_env"].startswith("MADZI_SRC_"))
        self.assertNotIn("password", json.dumps(cfg).lower())
        view_cols = {"branch_code", "period_month", "billed_volume_m3", "billed_amount", "cash_collected",
                     "active_accounts", "new_connections", "disconnections", "updated_at"}
        for sql in PACK.glob("v_madzi_monthly.*.sql"):
            text = sql.read_text()
            for col in view_cols:
                self.assertIn(col, text, f"{sql.name} lacks {col}")

    def test_pilot_day_by_day(self):
        self._setup_per_guide()

        # Day 1: dry run writes nothing and flags unmapped branches.
        dry = self.call("POST", "/api/integration/sources/billing/test")
        self.assertTrue(dry["ok"], dry)
        self.assertEqual(dry["rows_read"], 5)
        self.assertEqual(dry["values_mapped"], 0)  # no branch mapped yet
        self.assertEqual(dry["rows_rejected"], 5)
        self.assertIn("unknown org unit 'BR01'", dry["rejects"][0]["reason"])
        self.assertIn("billed_volume_m3", dry["columns"])
        self.assertEqual(self.call("GET", "/api/integration/runs?source=billing"), [])
        src = next(s for s in self.call("GET", "/api/integration/sources") if s["code"] == "billing")
        self.assertIsNone(src["watermark"])

        # Day 1-2: map branches (BR99 deliberately left unmapped), test again.
        self.call("PUT", "/api/integration/sources/billing/key-mappings", [
            {"kind": "org_unit", "external_key": "BR01", "internal_code": "north"},
            {"kind": "org_unit", "external_key": "BR02", "internal_code": "south"}])
        dry = self.call("POST", "/api/integration/sources/billing/test")
        self.assertEqual((dry["rows_rejected"], dry["periods"]), (1, {"first": "2026-05-01", "last": "2026-06-01"}))
        self.assertEqual(dry["metrics"], ["active_customers", "amt_billed", "cash_collected", "disconnections",
                                          "new_connections", "revenue_water"])
        limited = self.call("POST", "/api/integration/sources/billing/test?limit=2")
        self.assertEqual(limited["rows_read"], 2)

        # Day 2: first real load.
        run = self.call("POST", "/api/integration/sources/billing/run")
        self.assertEqual((run["status"], run["rows_rejected"]), ("partial", 1))
        self.assertEqual(run["watermark_after"], "2026-07-02T01:00:00")

        # Organisation figures: sums roll up, ratios computed, blanks stay missing.
        june = lambda code: self.call("GET", f"/api/position/{code}")["where_we_are"]
        self.assertEqual(june("cash_collected")["value"], 17500.0)
        self.assertEqual(june("cash_collected")["source"], "billing")
        self.assertAlmostEqual(june("collection_efficiency")["value"], 17500 / 21500 * 100)
        south_volume = self.call("GET", "/api/position/revenue_water?org_unit=south")
        self.assertEqual(south_volume["where_we_are"]["period"], "2026-05-01")  # June volume NULL: not a zero
        self.assertEqual(south_volume["where_we_are"]["value"], 3000.0)

        # A late correction moves updated_at; the nightly run replaces the value.
        con = sqlite3.connect(self.billing_db)
        con.execute("UPDATE v_madzi_monthly SET cash_collected = 5200, updated_at = '2026-07-05T01:00:00' "
                    "WHERE branch_code = 'BR01' AND period_month = '2026-06-01'")
        con.commit()
        con.close()
        rerun = self.call("POST", "/api/integration/sources/billing/run")
        self.assertEqual(rerun["rows_read"], 1)
        self.assertEqual(june("cash_collected")["value"], 17700.0)

    def test_billing_outranks_monthly_returns_and_differences_are_listed(self):
        self._setup_per_guide()
        # The monthly returns reported North's May collections differently.
        self.call("POST", "/api/integration/sources", {
            "code": "returns", "name": "Monthly returns", "connector": "file", "priority": 500,
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "Cash"}, "period": {"field": "Month"},
                        "org_unit": {"field": "Unit"}}})
        r = self.client.post("/api/integration/sources/returns/upload", headers=self.h,
                             files={"file": ("may.csv", b"Unit,Month,Cash\nnorth,2026-05-01,4300\n", "text/csv")})
        self.assertEqual(r.json()["values_loaded"], 1, r.text)
        self.call("PUT", "/api/integration/sources/billing/key-mappings", [
            {"kind": "org_unit", "external_key": "BR01", "internal_code": "north"}])
        self.call("POST", "/api/integration/sources/billing/run")
        north = self.call("GET", "/api/position/cash_collected?org_unit=north")
        may = next(p for p in north["where_we_were"] + [north["where_we_are"]] if p["period"] == "2026-05-01")
        self.assertEqual((may["value"], may["source"]), (4500.0, "billing"))  # priority 50 beats 500
        diff = self.call("GET", "/api/position/cash_collected/reconciliation?org_unit=north")
        self.assertEqual((diff[0]["period"], diff[0]["spread"]), ("2026-05-01", 200.0))

    def test_connection_failure_is_reported_without_the_url(self):
        self._setup_per_guide()
        os.environ["MADZI_SRC_BILLING_DB_URL"] = "not a url with secret-p4ss"
        dry = self.call("POST", "/api/integration/sources/billing/test")
        self.assertFalse(dry["ok"])
        self.assertIn("MADZI_SRC_BILLING_DB_URL", dry["error"])
        self.assertNotIn("secret-p4ss", dry["error"])


if __name__ == "__main__":
    unittest.main()
