"""Slice 1b: source freshness (UX-03), comparator provenance and consistency (UX-11).

Dates are fixed in every case, so nothing depends on the calendar or the demo seed.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime

from tests.test_integration_hub import _HubFixture
from tests._app_loader import TemporaryDirectory, fresh_app


class FreshnessStateTests(_HubFixture):
    def fresh(self):
        return {s["code"]: s for s in self.client.get("/api/position/sources/freshness", headers=self.viewer).json()}

    def test_never_ingested_and_unscheduled_sources_are_not_called_current(self):
        from app.integration.models import DataSource, MetricValue
        self._billing_db([])
        self._billing_source()                      # scheduled hourly, never succeeded
        self.post("/api/integration/sources", {
            "code": "drops", "name": "Monthly workbook", "connector": "file", "system_type": "file",
            "mapping": {"layout": "wide", "metrics": {"cash_collected": "Cash"},
                        "period": {"field": "Month"}, "org_unit": {"field": "Region"}}})
        with self.database.SessionLocal() as db:
            src = DataSource(code="strategy-updates", name="Approved progress updates", system_type="other",
                             connector="push", priority=400, config={}, mapping={}, enabled=True)
            db.add(src)
            db.flush()
            db.add(MetricValue(metric_code="nrw_pct", org_unit_code="north", period_type="quarter",
                               period_start=date(2026, 7, 1), value=31.4, source_id=src.id,
                               source_ref="progress_update:1", loaded_at=datetime(2026, 9, 1, 8, 0)))
            db.commit()
        f = self.fresh()
        self.assertEqual((f["billing"]["freshness"], f["billing"]["feed"]), ("overdue", "scheduled"))
        self.assertEqual((f["drops"]["freshness"], f["drops"]["feed"]), ("no_ingestion", "unscheduled"))
        approved = f["strategy-updates"]
        self.assertEqual((approved["freshness"], approved["feed"]), ("not_scheduled", "approved_updates"))
        self.assertIsNone(approved["last_success_at"])            # it never "runs"...
        self.assertEqual(approved["last_value_at"], "2026-09-01T08:00:00")   # ...but values were published

    def test_scheduled_source_that_succeeded_is_current_and_disabled_is_disabled(self):
        self._billing_db([("BR-N", "2026-01-15", 90.0, "2026-01-16")])
        self._billing_source()
        self.post("/api/integration/sources/billing/run")
        self.assertEqual(self.fresh()["billing"]["freshness"], "current")
        with self.database.SessionLocal() as db:
            from app.integration.models import DataSource
            db.query(DataSource).filter_by(code="billing").update({"enabled": False})
            db.commit()
        self.assertEqual(self.fresh()["billing"]["freshness"], "disabled")

    def test_approved_updates_source_name_matches_the_strategy_module(self):
        from app.integration.position import APPROVED_UPDATES_SOURCE
        from app.modules.strategy.service import MANUAL_SOURCE
        self.assertEqual(APPROVED_UPDATES_SOURCE, MANUAL_SOURCE)


class ExceptionsReportSourcesTests(unittest.TestCase):
    """Governed report layout: new freezes use explicit states; approved ones render as frozen."""

    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as d:
            import os
            os.environ.update({"DATABASE_URL": f"sqlite:///{d}/l.db", "MADZI_ENV": "development",
                               "MADZI_SECRET_KEY": "k", "MADZI_TENANT": "demo"})
            fresh_app()
        from app.modules.reporting import layout
        cls.blocks = staticmethod(layout._source_blocks)

    def texts(self, data):
        return [b.get("text") or b.get("caption") for b in self.blocks(data)]

    def test_legacy_frozen_report_renders_exactly_as_approved(self):
        legacy = {"sources": [{"name": "Approved updates", "overdue": None, "last_status": None,
                               "last_success_at": None}]}
        self.assertEqual(self.texts(legacy), ["Stale or failing data sources", "All connected sources are current."])

    def test_new_freeze_never_claims_current_for_unscheduled_or_empty_sources(self):
        new = {"sources_contract": 2, "sources": [
            {"name": "Approved updates", "freshness": "not_scheduled", "last_success_at": None,
             "last_value_at": "2026-09-01T08:00:00", "overdue": None, "last_status": None},
            {"name": "Billing", "freshness": "current", "last_success_at": "2026-09-24T00:00:00",
             "last_value_at": "2026-09-24T00:00:00", "overdue": False, "last_status": "success"}]}
        blocks = self.blocks(new)
        self.assertEqual(blocks[0]["text"], "Data source freshness")
        self.assertEqual(blocks[1]["rows"], [["Approved updates", "No schedule; freshness not assessed",
                                              "never", "2026-09-01T08:00:00"]])
        only_current = {"sources_contract": 2, "sources": new["sources"][1:]}
        self.assertEqual(self.texts(only_current)[1], "All enabled sources are scheduled and current.")
        self.assertEqual(self.texts({"sources_contract": 2, "sources": []})[1],
                         "No enabled sources are connected; freshness is not assessed.")


class PositionComparatorTests(_HubFixture):
    def setUp(self):
        super().setUp()
        self.post("/api/integration/sources", {
            "code": "ops", "name": "Operations returns", "connector": "file", "system_type": "file",
            "mapping": {"layout": "wide", "metrics": {"nrw_pct": "NRW"},
                        "period": {"field": "Month"}, "org_unit": {"field": "Region"}}})
        r = self.client.post("/api/integration/sources/ops/upload", headers=self.admin,
                             files={"file": ("q.csv", b"Region,Month,NRW\nnorth,2026-07-01,31.4\n", "text/csv")})
        self.assertLess(r.status_code, 300, r.text)

    def pos(self):
        return self.client.get("/api/position/nrw_pct?org_unit=north&period_type=month", headers=self.viewer).json()

    def target(self, period, value, basis="strategic_plan"):
        self.post("/api/integration/targets", [{"metric_code": "nrw_pct", "org_unit_code": "north", "period_type": "month",
                                                "period_start": period, "value": value, "basis": basis}])

    def test_gap_carries_its_comparator_provenance(self):
        self.target("2026-07-01", 28)
        g = self.pos()["gap_to_target"]
        self.assertAlmostEqual(g["difference"], 3.4)
        self.assertFalse(g["on_track"])
        c = g["comparator"]
        self.assertEqual((c["type"], c["label"], c["unit"], c["org_unit"], c["period"], c["period_type"]),
                         ("strategic_plan", "Strategic plan target", "%", "north", "2026-07-01", "month"))
        self.assertTrue(c["source"])
        self.assertRegex(c["version"], r"^target #\d+")

    def test_an_earlier_periods_target_is_never_carried_forward(self):
        self.target("2026-06-01", 28)
        p = self.pos()
        self.assertIsNone(p["gap_to_target"])
        self.assertIn("No strategic-plan target for this period", p["target_note"])
        self.assertIn("2026-06-01", p["target_note"])

    def test_each_basis_is_resolved_separately_and_the_plan_is_primary(self):
        self.target("2026-07-01", 35, basis="regulator")
        self.target("2026-07-01", 28)
        p = self.pos()
        self.assertEqual((p["gap_to_target"]["basis"], p["gap_to_target"]["target"]), ("strategic_plan", 28))
        self.assertEqual([(o["basis"], o["target"], o["on_track"]) for o in p["other_comparators"]],
                         [("regulator", 35, True)])
        # Without a plan target the regulator figure is shown, never promoted to the primary verdict.
        with self.database.SessionLocal() as db:
            from app.integration.models import MetricTarget
            db.query(MetricTarget).filter_by(basis="strategic_plan").delete()
            db.commit()
        p = self.pos()
        self.assertIsNone(p["gap_to_target"])
        self.assertEqual([o["basis"] for o in p["other_comparators"]], ["regulator"])


class GovernedComparatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with TemporaryDirectory() as d:
            import os
            os.environ.update({"DATABASE_URL": f"sqlite:///{d}/c.db", "MADZI_ENV": "development",
                               "MADZI_SECRET_KEY": "k", "MADZI_TENANT": "demo"})
            fresh_app()
        from app.services import comparators
        cls.c = comparators

    def test_rules_come_from_tenant_configuration_with_origin(self):
        nrw = self.c.rule("nrw_pct")
        self.assertEqual((nrw["good"], nrw["warn"]), (27.0, 35.0))
        self.assertEqual(nrw["good_comparator"]["type"], "corporate_target")
        self.assertEqual(nrw["good_comparator"]["origin"], "tenant targets.nrw_pct")
        self.assertEqual(nrw["warn_comparator"]["type"], "operational_band")
        self.assertEqual(nrw["context"][0]["type"], "benchmark")      # IWA 20 is context, not the verdict
        coll = self.c.rule("collection_rate")
        self.assertEqual((coll["good"], coll["warn"]), (90.0, 75.0))
        self.assertIn("config", nrw["version"])

    def test_boundaries_and_missing_values(self):
        a = self.c.assess
        self.assertEqual([a("staff_per_1000_conn", v) for v in (13, 13.1, 20, 20.5)], ["GOOD", "WATCH", "WATCH", "HIGH"])
        self.assertEqual([a("collection_rate", v) for v in (90, 89.9, 75, 74.9)], ["GOOD", "WATCH", "WATCH", "HIGH"])
        self.assertEqual(a("nrw_pct", None), "NOT ASSESSED")
        self.assertEqual(a("unknown_measure", 5), "NOT ASSESSED")      # no silent fallback rule

    def test_benchmark_text_names_the_comparator(self):
        self.assertEqual(self.c.benchmark_text("staff_per_1000_conn"), "≤13 (Staffing target)")


class ReportAndDashboardAgreementTests(unittest.TestCase):
    """The report scorecard and the injected dashboard rules use the same boundaries."""

    def test_scorecard_flags_use_the_governed_rules(self):
        from tests.test_missing_data_contract import FIELDS, MONTHS  # noqa: F401  (shared realistic inputs)
        from tests._fixture import boot
        from fastapi.testclient import TestClient
        from tests._access import add_user
        with TemporaryDirectory() as d:
            main, database, auth, _ = boot(d)
            with TestClient(main.app) as client:
                h = add_user(database, auth, "boss", "admin")
                with database.SessionLocal() as s:
                    s.add(database.Record(zone="North", scheme="Northgate", year=2025, month_no=1, month="January",
                                          quarter="Q3", fiscal_year="FY2024/25",
                                          **{**FIELDS, "perm_staff": 10, "temp_staff": 5, "supply_hours": 21.0}))
                    s.commit()
                sc = client.get("/api/reports/scorecard?year=2025", headers=h).json()
                metrics = {m["name"]: m for d in sc["domains"] for m in d["metrics"]}
                staff = metrics["Staff/1k Connections"]
                # 15 staff per 1,000 connections: WATCH against the 13 target / 20 band, as on the Board.
                self.assertEqual((staff["value"], staff["flag"], staff["benchmark"]), ("15.0", "WATCH", "≤13 (Staffing target)"))
                js = client.get("/static/assets/js/app-core.js").text
                from tests.test_tenant_config import _comparators
                rules = _comparators(js)
                self.assertEqual((rules["staff_per_1000_conn"]["good"], rules["staff_per_1000_conn"]["warn"]), (13.0, 20.0))
                sup = client.get("/api/panels/supply-continuity?year=2025", headers=h).json()["kpi"]
                self.assertEqual(sup["target_hours"], rules["supply_hours"]["good"])

    def test_supply_continuity_empty_scope_does_not_fail(self):
        from tests._fixture import boot
        from fastapi.testclient import TestClient
        from tests._access import add_user
        with TemporaryDirectory() as d:
            main, database, auth, _ = boot(d)
            with TestClient(main.app) as client:
                h = add_user(database, auth, "boss", "admin")
                r = client.get("/api/panels/supply-continuity?year=2025", headers=h)
                self.assertEqual(r.status_code, 200, r.text)
                k = r.json()["kpi"]
                self.assertEqual((k["supply_hours"], k["gap_to_target"], k["supply_flag"]), (None, None, "NOT ASSESSED"))


if __name__ == "__main__":
    unittest.main()
