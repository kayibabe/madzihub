"""Integration hub: mapping rules, connectors, pipeline, position API and access control.

All sources here are simulated locally (a SQLite "billing" database, CSV bytes,
a mocked OData API, JSON pushes). No real SAP/Maximo/SCADA system is contacted.
"""
from __future__ import annotations

import os
import sqlite3
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient

from tests._app_loader import fresh_app


def _boot(tmpdir: str):
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'hub.db'}"
    os.environ["MADZI_SECRET_FILE"] = str(Path(tmpdir) / "secret")
    os.environ["MADZI_INTEGRATION_DROP_DIR"] = str(Path(tmpdir) / "drop")
    os.environ.update({"MADZI_ENV": "development", "MADZI_SECRET_KEY": "k", "MADZI_TENANT": "demo"})
    return fresh_app()


class MappingRuleTests(unittest.TestCase):
    """Pure mapping logic: no database, no app."""

    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as d:
            _boot(d)
        from app.integration import mapping
        cls.m = mapping
        cls.resolver = mapping.Resolver(
            org_codes={"org", "north", "north.a"},
            metric_codes={"vol_produced", "active_customers", "energy_kwh"},
            key_map={("org_unit", "CC-1001"): "north.a", ("metric", "PLANT1.FLOW.TOT"): "vol_produced"},
        )

    def test_wide_rows_translate_keys_and_skip_blanks(self):
        rows = [
            {"CostCentre": "CC-1001", "Date": "2026-01-15", "Prod": "1,200", "Cust": ""},
            {"CostCentre": "CC-1001", "Date": "2026-01-20", "Prod": 300, "Cust": 50},
        ]
        mapping = {"layout": "wide", "metrics": {"vol_produced": "Prod", "active_customers": "Cust"},
                   "period": {"field": "Date"}, "org_unit": {"field": "CostCentre"}}
        res = self.m.map_rows(rows, mapping, self.resolver, {"vol_produced": "sum", "active_customers": "last"})
        got = {(v.metric_code, v.org_unit_code, v.period_start): v.value for v in res.values}
        self.assertEqual(got[("vol_produced", "north.a", date(2026, 1, 1))], 1500.0)
        # Blank customer cell was skipped, not stored as zero; the later row supplies the value.
        self.assertEqual(got[("active_customers", "north.a", date(2026, 1, 1))], 50.0)
        self.assertEqual(res.rows_rejected, 0)

    def test_long_rows_aggregate_telemetry_and_ignore_unmapped_tags(self):
        rows = [
            {"Tag": "PLANT1.FLOW.TOT", "Value": 10, "Time": "2026-02-01T00:00:00Z", "Site": "north"},
            {"Tag": "PLANT1.FLOW.TOT", "Value": 15, "Time": "2026-02-01T12:00:00Z", "Site": "north"},
            {"Tag": "PLANT1.PRESSURE", "Value": 3.2, "Time": "2026-02-01T12:00:00Z", "Site": "north"},
        ]
        mapping = {"layout": "long", "metric_field": "Tag", "value_field": "Value", "ignore_unmapped_metrics": True,
                   "period": {"field": "Time"}, "period_type": "day", "org_unit": {"field": "Site"}}
        res = self.m.map_rows(rows, mapping, self.resolver, {"vol_produced": "sum"})
        self.assertEqual([(v.metric_code, v.period_start, v.value) for v in res.values],
                         [("vol_produced", date(2026, 2, 1), 25.0)])
        self.assertEqual(res.rows_rejected, 0)

    def test_rejects_explain_bad_rows(self):
        rows = [
            {"Org": "nowhere", "Y": 2026, "M": "March", "Prod": 1},
            {"Org": "north", "Y": 2026, "M": "Smarch", "Prod": 1},
            {"Org": "north", "Y": 2026, "M": "Mar", "Prod": "lots"},
            {"Org": "north", "Y": 2026, "M": "3", "Prod": "(5)"},
        ]
        mapping = {"layout": "wide", "metrics": {"vol_produced": "Prod"},
                   "period": {"year_field": "Y", "month_field": "M"}, "org_unit": {"field": "Org"}}
        res = self.m.map_rows(rows, mapping, self.resolver, {})
        reasons = [r["reason"] for r in res.rejects]
        self.assertEqual(res.rows_rejected, 3)
        self.assertIn("unknown org unit 'nowhere'", reasons[0])
        self.assertIn("unrecognised month", reasons[1])
        self.assertIn("not a number", reasons[2])
        self.assertEqual(res.values[0].value, -5.0)  # accounting negative

    def test_fiscal_periods_follow_tenant_calendar(self):
        # Demo tenant: fiscal year starts in July.
        self.assertEqual(self.m.period_start(date(2026, 2, 10), "year"), date(2025, 7, 1))
        self.assertEqual(self.m.period_start(date(2026, 8, 10), "year"), date(2026, 7, 1))
        self.assertEqual(self.m.period_start(date(2026, 9, 30), "quarter"), date(2026, 7, 1))
        self.assertEqual(self.m.period_start(date(2026, 1, 5), "quarter"), date(2026, 1, 1))

    def test_odata_v2_dates(self):
        d = self.m.parse_period({"PostingDate": "/Date(1767225600000)/"}, {"field": "PostingDate"})
        self.assertEqual(d, date(2026, 1, 1))


class _HubFixture(unittest.TestCase):
    """Running app with an admin, a viewer and a small org tree (org → north, south)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = self._tmp.name
        self.main, self.database, self.auth, _ = _boot(self.tmp)
        self.client = TestClient(self.main.app)
        self.client.__enter__()
        db = self.database.SessionLocal()
        db.add(self.database.User(username="boss", password_hash=self.auth.hash_password("x"), role="admin"))
        db.add(self.database.User(username="look", password_hash=self.auth.hash_password("x"), role="viewer"))
        db.commit()
        db.close()
        self.admin = {"Authorization": f"Bearer {self.auth.create_access_token('boss', 'admin')}"}
        self.viewer = {"Authorization": f"Bearer {self.auth.create_access_token('look', 'viewer')}"}
        self._seed_catalogue()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self._tmp.cleanup()

    def post(self, url, json=None, **kw):
        r = self.client.post(url, json=json, headers=kw.pop("headers", self.admin), **kw)
        self.assertLess(r.status_code, 300, r.text)
        return r.json()

    def _seed_catalogue(self):
        self.post("/api/integration/org-units", [
            {"code": "org", "name": "Lakeside", "unit_type": "organisation"},
            {"code": "north", "name": "North", "unit_type": "region", "parent_code": "org"},
            {"code": "south", "name": "South", "unit_type": "region", "parent_code": "org"},
        ])
        self.post("/api/integration/metrics", [
            {"code": "cash_collected", "name": "Cash collected", "unit": "USD", "aggregation": "sum"},
            {"code": "nrw_pct", "name": "NRW %", "unit": "%", "aggregation": "avg", "direction": "lower"},
        ])

    def _billing_db(self, rows):
        path = Path(self.tmp) / "billing.db"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE IF NOT EXISTS receipts (branch TEXT, paid_on TEXT, amount REAL, changed TEXT)")
        con.executemany("INSERT INTO receipts VALUES (?,?,?,?)", rows)
        con.commit()
        con.close()
        os.environ["MADZI_SRC_TEST_BILLING_URL"] = f"sqlite:///{path}"

    def _billing_source(self, priority=50):
        self.post("/api/integration/sources", {
            "code": "billing", "name": "Billing system", "system_type": "billing", "connector": "sql",
            "priority": priority, "schedule_minutes": 60,
            "config": {"url_env": "MADZI_SRC_TEST_BILLING_URL", "watermark_field": "changed",
                       "query": "SELECT branch, paid_on, amount, changed FROM receipts WHERE changed > :since"},
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "amount"},
                        "period": {"field": "paid_on"}, "org_unit": {"field": "branch"}},
        })
        self.client.put("/api/integration/sources/billing/key-mappings", headers=self.admin,
                        json=[{"kind": "org_unit", "external_key": "BR-N", "internal_code": "north"},
                              {"kind": "org_unit", "external_key": "BR-S", "internal_code": "south"}])


class HubApiTests(_HubFixture):
    def test_sql_pull_is_incremental_and_idempotent(self):
        self._billing_db([("BR-N", "2026-01-03", 100, "2026-01-04T00:00"),
                          ("BR-N", "2026-01-20", 50, "2026-01-21T00:00"),
                          ("BR-S", "2026-01-09", 70, "2026-01-10T00:00"),
                          ("BR-X", "2026-01-09", 1, "2026-01-10T00:00")])
        self._billing_source()
        run = self.post("/api/integration/sources/billing/run")
        self.assertEqual((run["status"], run["rows_read"], run["values_loaded"], run["rows_rejected"]),
                         ("partial", 4, 2, 1))
        self.assertIn("BR-X", run["rejects"][0]["reason"])
        self.assertEqual(run["watermark_after"], "2026-01-21T00:00")

        # A late correction arrives: only rows changed since the watermark are read.
        self._billing_db([("BR-N", "2026-02-02", 30, "2026-02-03T00:00")])
        run = self.post("/api/integration/sources/billing/run")
        self.assertEqual(run["rows_read"], 1)

        # Full reload after resetting the watermark updates rows in place, no duplicates.
        self.client.put("/api/integration/sources/billing", headers=self.admin, json={"reset_watermark": True})
        self.post("/api/integration/sources/billing/run")
        p = self.client.get("/api/position/cash_collected?org_unit=north", headers=self.viewer).json()
        self.assertEqual([(s["period"], s["value"]) for s in p["where_we_were"] + [p["where_we_are"]]],
                         [("2026-01-01", 150.0), ("2026-02-01", 30.0)])
        self.assertEqual(p["where_we_are"]["source"], "billing")

    def test_rollup_priority_reconciliation_and_targets(self):
        self._billing_db([("BR-N", "2026-01-03", 100, "a"), ("BR-S", "2026-01-09", 70, "a")])
        self._billing_source(priority=50)
        self.post("/api/integration/sources/billing/run")

        # A finance spreadsheet reports the same measure; billing has priority.
        self.post("/api/integration/sources", {
            "code": "finance-xls", "name": "Finance monthly report", "system_type": "file", "connector": "file",
            "priority": 200, "config": {"path": "finance/*.csv"},
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "Cash"},
                        "period": {"year_field": "Year", "month_field": "Month"}, "org_unit": {"field": "Region"}},
        })
        csv = b"Region,Year,Month,Cash\nnorth,2026,January,90\nsouth,2026,Jan,70\n"
        r = self.client.post("/api/integration/sources/finance-xls/upload", headers=self.admin,
                             files={"file": ("jan.csv", csv, "text/csv")})
        self.assertEqual(r.json()["values_loaded"], 2, r.text)

        # Organisation has no own value: it rolls up from regions using the preferred source.
        p = self.client.get("/api/position/cash_collected", headers=self.viewer).json()
        self.assertTrue(p["rolled_up"])
        self.assertEqual(p["where_we_are"]["value"], 170.0)
        self.assertEqual(p["where_we_are"]["units_reporting"], 2)

        rec = self.client.get("/api/position/cash_collected/reconciliation?org_unit=north", headers=self.viewer).json()
        self.assertEqual(rec[0]["spread"], 10.0)

        # Averages are never rolled up by adding.
        self.assertIsNone(self.client.get("/api/position/nrw_pct", headers=self.viewer).json()["where_we_are"])

        self.post("/api/integration/targets", [
            {"metric_code": "cash_collected", "org_unit_code": "org", "period_type": "month",
             "period_start": "2026-01-01", "value": 200},
            {"metric_code": "cash_collected", "org_unit_code": "org", "period_type": "month",
             "period_start": "2026-06-01", "value": 260},
        ])
        p = self.client.get("/api/position/cash_collected", headers=self.viewer).json()
        self.assertEqual(p["gap_to_target"]["difference"], -30.0)
        self.assertFalse(p["gap_to_target"]["on_track"])
        self.assertEqual([t["value"] for t in p["where_we_are_going"]], [260.0])

        overview = self.client.get("/api/position", headers=self.viewer).json()
        self.assertIn("cash_collected", [m["metric"]["code"] for m in overview["measures"]])

    def test_file_source_polls_drop_folder_once_per_file_version(self):
        drop = Path(self.tmp) / "drop" / "returns"
        drop.mkdir(parents=True)
        (drop / "feb.csv").write_text("Region,Date,Cash\nnorth,2026-02-01,5\n")
        self.post("/api/integration/sources", {
            "code": "returns", "name": "Returns folder", "connector": "file", "system_type": "file",
            "config": {"path": "returns/*.csv"},
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "Cash"},
                        "period": {"field": "Date"}, "org_unit": {"field": "Region"}},
        })
        self.assertEqual(self.post("/api/integration/sources/returns/run")["values_loaded"], 1)
        self.assertEqual(self.post("/api/integration/sources/returns/run")["rows_read"], 0)

    def test_file_source_cannot_escape_drop_folder(self):
        self.post("/api/integration/sources", {
            "code": "sneaky", "name": "x", "connector": "file", "config": {"path": "../../etc/*"},
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "c"}, "period": {"field": "d"}},
        })
        run = self.post("/api/integration/sources/sneaky/run")
        self.assertEqual(run["status"], "failed")
        self.assertIn("inside the integration drop folder", run["error"])

    def test_rest_odata_paging_and_incremental_filter(self):
        import httpx

        seen = []

        def handler(request: httpx.Request):
            seen.append(str(request.url))
            if "skiptoken" not in str(request.url):
                return httpx.Response(200, json={"d": {"results": [
                    {"Plant": "north", "PostingDate": "/Date(1767225600000)/", "Amount": "10.5", "Changed": "2026-01-02"}],
                    "__next": "https://sap.example/odata/Receipts?$skiptoken=2"}})
            return httpx.Response(200, json={"d": {"results": [
                {"Plant": "south", "PostingDate": "/Date(1767225600000)/", "Amount": "4", "Changed": "2026-01-05"}]}})

        real_client = httpx.Client
        os.environ["MADZI_SRC_TEST_SAP_USER"], os.environ["MADZI_SRC_TEST_SAP_PASS"] = "u", "p"
        self.post("/api/integration/sources", {
            "code": "sap-fi", "name": "SAP receipts", "system_type": "erp", "connector": "rest",
            "config": {"base_url": "https://sap.example/odata", "path": "Receipts",
                       "auth": {"type": "basic", "username_env": "MADZI_SRC_TEST_SAP_USER", "password_env": "MADZI_SRC_TEST_SAP_PASS"},
                       "params": {"$format": "json", "$filter": "Changed gt '{since}'"},
                       "records_path": "d.results", "next_link_path": "d.__next", "watermark_field": "Changed"},
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "Amount"},
                        "period": {"field": "PostingDate"}, "org_unit": {"field": "Plant"}},
        })
        with mock.patch("httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            first = self.post("/api/integration/sources/sap-fi/run")
            self.assertEqual((first["rows_read"], first["values_loaded"], first["watermark_after"]), (2, 2, "2026-01-05"))
            self.assertNotIn("filter", seen[0])  # first load is a full load
            self.post("/api/integration/sources/sap-fi/run")
            self.assertIn("2026-01-05", seen[-2])  # incremental filter uses the watermark

    def test_rest_missing_secret_fails_run_readably(self):
        self.post("/api/integration/sources", {
            "code": "maximo", "name": "Maximo", "system_type": "eam", "connector": "rest",
            "config": {"base_url": "https://maximo.example", "auth": {"type": "header", "token_env": "MADZI_SRC_NOPE"}},
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "x"}, "period": {"field": "d"}},
        })
        run = self.post("/api/integration/sources/maximo/run")
        self.assertEqual(run["status"], "failed")
        self.assertIn("MADZI_SRC_NOPE", run["error"])

    def test_source_config_cannot_read_app_secrets(self):
        self.post("/api/integration/sources", {
            "code": "leak", "name": "x", "connector": "sql",
            "config": {"url_env": "MADZI_SECRET_KEY", "query": "SELECT 1"},
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "c"}, "period": {"field": "d"}},
        })
        run = self.post("/api/integration/sources/leak/run")
        self.assertEqual(run["status"], "failed")
        self.assertIn("MADZI_SRC_", run["error"])
        self.assertNotIn(os.environ["MADZI_SECRET_KEY"] + "/", run["error"])

        os.environ["MADZI_SRC_BAD_URL"] = "not-a-url-hunter2"
        self.client.put("/api/integration/sources/leak", headers=self.admin,
                        json={"config": {"url_env": "MADZI_SRC_BAD_URL", "query": "SELECT 1"}})
        run = self.post("/api/integration/sources/leak/run")
        self.assertEqual(run["status"], "failed")
        self.assertNotIn("hunter2", run["error"])

    def test_push_feed_requires_its_token(self):
        self.post("/api/integration/metrics", [{"code": "energy_kwh", "name": "Energy", "unit": "kWh"}])
        self.post("/api/integration/sources", {
            "code": "scada", "name": "SCADA gateway", "system_type": "scada", "connector": "push",
            "mapping": {"layout": "long", "metric_field": "tag", "value_field": "v", "period": {"field": "t"},
                        "period_type": "day", "org_unit": {"field": "site"}},
        })
        token = self.post("/api/integration/sources/scada/token")["token"]
        body = {"rows": [{"tag": "energy_kwh", "v": 5, "t": "2026-03-01T01:00:00", "site": "north"},
                         {"tag": "energy_kwh", "v": 7, "t": "2026-03-01T02:00:00", "site": "north"}]}
        self.assertEqual(self.client.post("/api/ingest/scada", json=body).status_code, 401)
        self.assertEqual(self.client.post("/api/ingest/scada", json=body,
                                          headers={"X-Madzi-Ingest-Token": "mzi_wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/ingest/nosuch", json=body,
                                          headers={"X-Madzi-Ingest-Token": token}).status_code, 401)
        r = self.client.post("/api/ingest/scada", json=body, headers={"X-Madzi-Ingest-Token": token})
        self.assertEqual(r.json()["values_loaded"], 1, r.text)
        p = self.client.get("/api/position/energy_kwh?org_unit=north&period_type=day", headers=self.viewer).json()
        self.assertEqual(p["where_we_are"]["value"], 12.0)

    def test_viewers_cannot_administer_sources(self):
        self.assertEqual(self.client.get("/api/integration/sources", headers=self.viewer).status_code, 403)
        self.assertEqual(self.client.post("/api/integration/targets", json=[], headers=self.viewer).status_code, 403)
        self.assertEqual(self.client.get("/api/position/sources/freshness").status_code, 401)

    def test_viewers_can_list_units_for_the_scorecard(self):
        units = self.client.get("/api/position/org-units", headers=self.viewer).json()
        self.assertEqual({u["code"]: u["parent_code"] for u in units}, {"org": None, "north": "org", "south": "org"})

    def test_org_unit_cycle_rejected(self):
        self.post("/api/integration/org-units", [{"code": "north.a", "name": "A", "parent_code": "north"}])
        r = self.client.post("/api/integration/org-units", headers=self.admin,
                             json=[{"code": "north", "name": "North", "parent_code": "north.a"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("cycle", r.text)

    def test_freshness_flags_overdue_sources(self):
        self._billing_db([])
        self._billing_source()
        f = {s["code"]: s for s in self.client.get("/api/position/sources/freshness", headers=self.viewer).json()}
        self.assertTrue(f["billing"]["overdue"])  # scheduled hourly, never succeeded
        self.post("/api/integration/sources/billing/run")
        f = {s["code"]: s for s in self.client.get("/api/position/sources/freshness", headers=self.viewer).json()}
        self.assertFalse(f["billing"]["overdue"])
        self.assertEqual(f["billing"]["last_status"], "success")


class FormulaEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as d:
            _boot(d)
        from app.integration import formulas
        cls.f = formulas

    def test_evaluates_and_treats_missing_or_zero_division_as_missing(self):
        self.assertAlmostEqual(self.f.evaluate("nrw / vol_produced * 100", {"nrw": 25, "vol_produced": 100}), 25.0)
        self.assertAlmostEqual(self.f.evaluate("max(a, b) - abs(-c)", {"a": 1, "b": 4, "c": 2}), 2.0)
        self.assertIsNone(self.f.evaluate("a / b", {"a": 1, "b": 0}))
        self.assertIsNone(self.f.evaluate("a / b", {"a": 1}))
        self.assertEqual(self.f.references("(a + b) / min(c, 2)"), {"a", "b", "c"})

    def test_rejects_anything_but_arithmetic(self):
        # Bare names are only ever looked up as catalogue codes, never executed.
        for bad in ("__import__('os').system('x')", "a.real", "a ** 2", "a[0]", "lambda: 1", "'x'",
                    "a if b else c", "a and b", "max(a, key=b)", "", "a +"):
            with self.subTest(bad=bad), self.assertRaises(self.f.FormulaError):
                self.f.parse(bad)

    def test_trend_ignores_negligible_changes(self):
        from app.integration.position import _trend
        flat = [{"value": 36.9}] * 3 + [{"value": 36.9 + 1e-12}] * 3
        self.assertIsNone(_trend(flat, "lower")["improving"])
        worse = [{"value": 30.0}] * 3 + [{"value": 33.0}] * 3
        self.assertFalse(_trend(worse, "lower")["improving"])

    def test_validation_catches_unknown_and_circular_references(self):
        with self.assertRaisesRegex(self.f.FormulaError, "unknown measure"):
            self.f.validate("x", "a / zz", {"a", "x"}, {})
        with self.assertRaisesRegex(self.f.FormulaError, "circular"):
            self.f.check_catalogue({"x": "y + 1", "y": "x * 2"}, {"x", "y"})
        self.f.check_catalogue({"x": "a / b", "y": "x * 100"}, {"a", "b", "x", "y"})  # chains are fine


class FormulaPositionTests(_HubFixture):

    def _load_water(self, rows):
        self.post("/api/integration/metrics", [
            {"code": "vol_produced", "name": "Produced", "unit": "m³"},
            {"code": "nrw", "name": "NRW volume", "unit": "m³", "direction": "lower"},
            {"code": "nrw_ratio", "name": "NRW", "unit": "%", "direction": "lower", "aggregation": "avg",
             "formula": "nrw / vol_produced * 100"},
            {"code": "billed_est", "name": "Billed (derived)", "unit": "m³",
             "formula": "vol_produced - nrw"},  # default aggregation "sum": accumulates
        ])
        existing = {s["code"] for s in self.client.get("/api/integration/sources", headers=self.admin).json()}
        if "ops" not in existing:
            self.post("/api/integration/sources", {
                "code": "ops", "name": "Operations returns", "connector": "file", "system_type": "file",
                "mapping": {"layout": "wide", "metrics": {"vol_produced": "Produced", "nrw": "NRW"},
                            "period": {"field": "Month"}, "org_unit": {"field": "Region"}},
            })
        body = "Region,Month,Produced,NRW\n" + "".join(f"{r},{m},{p},{n}\n" for r, m, p, n in rows)
        r = self.client.post("/api/integration/sources/ops/upload", headers=self.admin,
                             files={"file": ("ops.csv", body.encode(), "text/csv")})
        self.assertEqual(r.json()["status"], "success", r.text)

    def test_formula_api_validation(self):
        r = self.client.post("/api/integration/metrics", headers=self.admin,
                             json=[{"code": "bad", "name": "Bad", "formula": "cash_collected / nothing"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("unknown measure", r.text)
        r = self.client.post("/api/integration/metrics", headers=self.admin, json=[
            {"code": "p", "name": "P", "formula": "q + 1"}, {"code": "q", "name": "Q", "formula": "p + 1"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("circular", r.text)
        r = self.client.post("/api/integration/metrics", headers=self.admin,
                             json=[{"code": "evil", "name": "E", "formula": "__import__('os')"}])
        self.assertEqual(r.status_code, 400)

    def test_formula_measures_cannot_be_loaded(self):
        self._load_water([("north", "2026-01-01", 100, 10)])
        self.post("/api/integration/sources", {
            "code": "direct", "name": "x", "connector": "file",
            "mapping": {"layout": "wide", "metrics": {"nrw_ratio": "Pct"}, "period": {"field": "M"},
                        "org_unit": {"field": "R"}},
        })
        r = self.client.post("/api/integration/sources/direct/upload", headers=self.admin,
                             files={"file": ("x.csv", b"R,M,Pct\nnorth,2026-01-01,12\n", "text/csv")})
        self.assertEqual(r.json()["values_loaded"], 0)
        self.assertIn("not in the catalogue", r.json()["rejects"][0]["reason"])

    def test_ratio_rolls_up_volume_weighted(self):
        # North 10% of 100 m³, South 30% of 300 m³. Organisation NRW is 100/400 = 25%, not the 20% average.
        self._load_water([("north", "2026-01-01", 100, 10), ("south", "2026-01-01", 300, 90)])
        p = self.client.get("/api/position/nrw_ratio", headers=self.viewer).json()
        self.assertEqual(p["derived"], "formula")
        self.assertTrue(p["rolled_up"])
        self.assertAlmostEqual(p["where_we_are"]["value"], 25.0)
        self.assertEqual(p["where_we_are"]["inputs"], {"nrw": 100.0, "vol_produced": 400.0})
        north = self.client.get("/api/position/nrw_ratio?org_unit=north", headers=self.viewer).json()
        self.assertAlmostEqual(north["where_we_are"]["value"], 10.0)

    def test_fiscal_year_view_marks_year_to_date(self):
        # Demo tenant: FY starts July. Two months of FY2026 (starting 2025-07-01) reported.
        self._load_water([("north", "2025-07-01", 100, 20), ("north", "2025-08-01", 100, 30)])
        self.post("/api/integration/targets", [
            {"metric_code": "vol_produced", "org_unit_code": "north", "period_type": "year",
             "period_start": "2025-07-01", "value": 1200},
            {"metric_code": "nrw_ratio", "org_unit_code": "north", "period_type": "year",
             "period_start": "2025-07-01", "value": 20},
        ])
        prod = self.client.get("/api/position/vol_produced?org_unit=north&period_type=year", headers=self.viewer).json()
        self.assertEqual(prod["derived"], "from_month")
        cur = prod["where_we_are"]
        self.assertEqual((cur["period"], cur["value"], cur["months_reporting"], cur["months_expected"]),
                         ("2025-07-01", 200.0, 2, 12))
        # 200 against 1,200 is year-to-date, not a miss.
        self.assertIsNone(prod["gap_to_target"]["on_track"])
        self.assertFalse(prod["gap_to_target"]["period_complete"])
        self.assertIn("year-to-date", prod["gap_to_target"]["note"])

        ratio = self.client.get("/api/position/nrw_ratio?org_unit=north&period_type=year", headers=self.viewer).json()
        self.assertAlmostEqual(ratio["where_we_are"]["value"], 25.0)  # 50 / 200
        self.assertEqual(ratio["where_we_are"]["months_reporting"], 2)
        self.assertFalse(ratio["gap_to_target"]["on_track"])  # a ratio YTD is still comparable
        q = self.client.get("/api/position/nrw_ratio?org_unit=north&period_type=quarter", headers=self.viewer).json()
        self.assertEqual(q["where_we_are"]["period"], "2025-07-01")

    def test_accumulating_formula_is_not_judged_year_to_date(self):
        self._load_water([("north", "2025-07-01", 100, 20), ("north", "2025-08-01", 100, 30)])
        self.post("/api/integration/targets", [
            {"metric_code": "billed_est", "org_unit_code": "north", "period_type": "year",
             "period_start": "2025-07-01", "value": 1000}])
        p = self.client.get("/api/position/billed_est?org_unit=north&period_type=year", headers=self.viewer).json()
        self.assertEqual(p["where_we_are"]["value"], 150.0)
        self.assertIsNone(p["gap_to_target"]["on_track"])
        self.assertIn("year-to-date", p["gap_to_target"]["note"])

    def test_average_measures_are_day_weighted_across_months(self):
        self.post("/api/integration/metrics", [
            {"code": "pressure_bar", "name": "Pressure", "unit": "bar", "aggregation": "avg"}])
        self.post("/api/integration/sources", {
            "code": "net", "name": "Network returns", "connector": "file",
            "mapping": {"layout": "wide", "metrics": {"pressure_bar": "P"}, "period": {"field": "M"},
                        "org_unit": {"field": "R"}},
        })
        r = self.client.post("/api/integration/sources/net/upload", headers=self.admin,
                             files={"file": ("p.csv", b"R,M,P\nnorth,2026-01-01,10\nnorth,2026-02-01,20\n", "text/csv")})
        self.assertEqual(r.json()["values_loaded"], 2, r.text)
        q = self.client.get("/api/position/pressure_bar?org_unit=north&period_type=quarter", headers=self.viewer).json()
        cur = q["where_we_are"]
        self.assertEqual(cur["period"], "2026-01-01")  # July fiscal year: Q3 starts in January
        self.assertAlmostEqual(cur["value"], (10 * 31 + 20 * 28) / 59)  # not the 15.0 simple mean
        self.assertEqual(cur["time_weighting"], "days_in_month")


class LegacyBridgeTests(unittest.TestCase):
    def test_existing_returns_become_history(self):
        from tests.fixtures.synthetic_dataset import build_records

        with TemporaryDirectory() as d:
            main, database, auth, _ = _boot(d)
            with TestClient(main.app) as c:
                db = database.SessionLocal()
                db.add_all(build_records(database.Record, zones={"North": ["Alpha", "Beta"]}))
                db.add(database.User(username="boss", password_hash=auth.hash_password("x"), role="admin"))
                db.commit()
                expected = sum(r.vol_produced for r in db.query(database.Record)
                               .filter_by(year=2025, month_no=4))
                db.close()
                h = {"Authorization": f"Bearer {auth.create_access_token('boss', 'admin')}"}

                created = c.post("/api/integration/bootstrap-legacy", headers=h).json()
                self.assertEqual(created["org_units"], 4)  # org, north, north.alpha, north.beta
                # Demo plan: NRW %, production and new connections, four years each.
                self.assertEqual(created["targets"], 12)
                self.assertTrue(c.post("/api/integration/bootstrap-legacy", headers=h).json()["org_units"] == 0)

                run = c.post("/api/integration/sources/legacy-returns/run", headers=h).json()
                self.assertEqual(run["status"], "success", run)
                p = c.get("/api/position/vol_produced", headers=h).json()
                self.assertTrue(p["rolled_up"])
                self.assertEqual(p["where_we_are"]["period"], "2025-04-01")
                self.assertAlmostEqual(p["where_we_are"]["value"], expected)
                self.assertEqual(len(p["where_we_were"]), 24)
                self.assertIsNotNone(p["trend"])

                # Organisation NRW % is total NRW over total production, from the same records.
                db = database.SessionLocal()
                recs = db.query(database.Record).filter_by(year=2025, month_no=4).all()
                want = sum(r.nrw for r in recs) / sum(r.vol_produced for r in recs) * 100
                db.close()
                nrw = c.get("/api/position/nrw_pct", headers=h).json()
                self.assertAlmostEqual(nrw["where_we_are"]["value"], want)
                going = c.get("/api/position/nrw_pct?period_type=year", headers=h).json()["where_we_are_going"]
                self.assertEqual([t["period"] for t in going][:1], ["2025-07-01"])  # FY2026 in a July-start plan

                again = c.post("/api/integration/sources/legacy-returns/run", headers=h).json()
                self.assertEqual(again["values_loaded"], run["values_loaded"])
                db = database.SessionLocal()
                from app.integration.models import MetricValue
                self.assertEqual(db.query(MetricValue).count(), run["values_loaded"])
                db.close()


if __name__ == "__main__":
    unittest.main()
