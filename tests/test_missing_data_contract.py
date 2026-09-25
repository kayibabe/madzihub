"""UX-01 missing-data contract: no performance verdict without sufficient inputs.

Covers absent keys, explicit nulls, genuine zeros, zero denominators, partial
scope, stale (carried-forward) data and complete data, including zone and
fiscal-month roll-ups. A zero or missing denominator is Not assessed (None),
never a measured 0 and never GOOD/WATCH/HIGH/CRITICAL.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.assessment import complete, divide, flag
from tests._fixture import AppFixture

YEAR = 2025                       # demo FY runs July-June: FY2024/25
FIELDS = dict(                    # every flow input the HR/Infra/alert ratios read
    vol_produced=1000.0, nrw=300.0, revenue_water=700.0, amt_billed=5000.0, cash_collected=4500.0,
    op_cost=3000.0, total_debtors=1000.0, staff_costs=400.0, wages=600.0, fuel_used_litres=50.0,
    distances_km=500.0, pipe_breakdowns=2, pump_breakdowns=1, queries_received=10.0, power_kwh=500.0,
    total_vol_billed_pp=600.0, total_vol_billed_prepaid=100.0, supply_hours=600.0, days_to_connect=10.0,
    active_customers=1000, total_metered=1250, stuck_meters=50, perm_staff=8, temp_staff=2,
)
MONTHS = {7: ("July", "Q1"), 8: ("August", "Q1"), 1: ("January", "Q3"), 2: ("February", "Q3")}


class DivideTest(unittest.TestCase):
    def test_zero_or_missing_denominator_is_not_assessed(self):
        self.assertIsNone(divide(5, 0))
        self.assertIsNone(divide(5, None))
        self.assertIsNone(divide(None, 10))
        self.assertIsNone(divide(5, -1))
        self.assertEqual(flag(divide(0, 0), 5, 8, lower=True), "NOT ASSESSED")

    def test_measured_zero_numerator_is_a_real_zero(self):
        self.assertEqual(divide(0, 1250), 0.0)
        self.assertEqual(flag(divide(0, 1250), 5, 8, lower=True), "GOOD")

    def test_scale_and_digits(self):
        self.assertEqual(divide(10, 1000, scale=1000), 10.0)
        self.assertEqual(divide(1, 3, scale=1, digits=2), 0.33)

    def test_explicit_null_is_not_replaced_by_a_default(self):
        # dict.get(key, 0) keeps an explicit None: consumers must test for None, not rely on the default.
        self.assertIsNone({"stuck_pct": None}.get("stuck_pct", 0))
        self.assertFalse(complete([SimpleNamespace(wages=None)], "wages"))


class MissingDataContractTest(AppFixture):
    def setUp(self):
        super().setUp()
        self.h = self.admin

    def add(self, zone="North", scheme="Northgate", month=1, **over):
        name, quarter = MONTHS[month]
        values = {**FIELDS, **over}
        nulls = {k: None for k, v in values.items() if v is None}
        Record = self.database.Record
        with self.db() as s:
            row = Record(zone=zone, scheme=scheme, year=YEAR if month < 7 else YEAR - 1, month_no=month, month=name,
                         quarter=quarter, fiscal_year=f"FY{YEAR - 1}/{str(YEAR)[-2:]}",
                         **{k: v for k, v in values.items() if v is not None})
            s.add(row)
            s.flush()
            # The ORM substitutes column defaults for None; store a real NULL ("not entered") as the importer does.
            if nulls:
                from sqlalchemy import update
                s.execute(update(Record).where(Record.id == row.id).values(**nulls))
            s.commit()

    def hra(self, q=""):
        return self.get(f"/api/reports/hra?year={YEAR}{q}", self.h)

    def infra(self, q=""):
        return self.get(f"/api/reports/infrastructure?year={YEAR}{q}", self.h)

    def alerts(self):
        return self.get(f"/api/insights/summary?year={YEAR}", self.h)

    def test_empty_scope_returns_no_ratios_and_a_zero_record_count(self):
        hr, inf = self.hra(), self.infra()
        self.assertEqual((hr["record_count"], inf["record_count"]), (0, 0))
        for key in ("staff_per_1000_conn", "payroll_cost_ratio", "m3_per_staff", "wages_per_staff", "fuel_per_km"):
            self.assertIsNone(hr["summary"][key], key)
        for key in ("breakdowns_per_1k_customers", "stuck_pct", "active_conn_ratio"):
            self.assertIsNone(inf["summary"][key], key)
        a = self.alerts()
        self.assertEqual((a["alerts"], a["kpi_snapshot"]), ([], {}))

    def test_zero_denominators_are_not_assessed(self):
        self.add(active_customers=0, total_metered=0, perm_staff=0, temp_staff=0, amt_billed=0.0, distances_km=0.0)
        hr, inf = self.hra()["summary"], self.infra()["summary"]
        self.assertEqual(hr["total_staff"], 0)
        for key in ("staff_per_1000_conn", "payroll_cost_ratio", "m3_per_staff", "wages_per_staff", "fuel_per_km"):
            self.assertIsNone(hr[key], key)
        for key in ("breakdowns_per_1k_customers", "stuck_pct", "active_conn_ratio"):
            self.assertIsNone(inf[key], key)
        ex = self.get(f"/api/panels/executive?year={YEAR}", self.h)
        for key in ("stuck_pct", "meter_read_rate", "complaints_1000"):
            self.assertIsNone(ex["service"][key], key)
        self.assertEqual(ex["service"]["complaints_flag"], "NOT ASSESSED")
        self.assertIsNone(ex["financial"]["rev_per_conn"])
        self.assertIsNone(self.get(f"/api/panels/staff-productivity?year={YEAR}", self.h)["kpi"]["staff_per_1000conn"])
        self.assertIsNone(self.get(f"/api/panels/breakdowns?year={YEAR}", self.h)["kpi"]["per_1k_customers"])
        self.assertIsNone(self.get(f"/api/panels/stuck?year={YEAR}", self.h)["kpi"]["per_1k_customers"])
        a = self.alerts()
        self.assertIsNone(a["kpi_snapshot"]["stuck_pct"])
        self.assertIn("Stuck-meter rate", a["not_assessed"])       # an empty list is not "all assessed"
        self.assertFalse([x for x in a["alerts"] if x["metric"] == "stuck_meters"])

    def test_measured_zero_stays_zero(self):
        self.add(stuck_meters=0, pipe_breakdowns=0, pump_breakdowns=0)
        inf = self.infra()["summary"]
        self.assertEqual((inf["stuck_pct"], inf["breakdowns_per_1k_customers"]), (0.0, 0.0))
        self.assertEqual(self.alerts()["kpi_snapshot"]["stuck_pct"], 0.0)

    def test_explicit_null_inputs_are_not_assessed(self):
        self.add(pipe_breakdowns=None, wages=None, fuel_used_litres=None)
        hr, inf = self.hra()["summary"], self.infra()["summary"]
        self.assertIsNone(inf["breakdowns_per_1k_customers"])
        for key in ("payroll_cost_ratio", "wages_per_staff", "fuel_per_km"):
            self.assertIsNone(hr[key], key)
        self.assertEqual(hr["staff_per_1000_conn"], 10.0)            # unrelated measures are still assessed

    def test_partial_scope_and_zone_rollup(self):
        self.add()                                                             # North: complete
        self.add(zone="South", scheme="Southport", perm_staff=0, temp_staff=0)  # South: no staff recorded
        zones = {z["zone"]: z for z in self.hra()["staff_by_zone"]}
        self.assertEqual(zones["North"]["m3_per_staff"], 100.0)
        self.assertIsNone(zones["South"]["m3_per_staff"])
        # A month missing a flow input makes the scope's ratio unassessed rather than understated...
        self.add(month=2, wages=None)
        self.assertIsNone(self.hra()["summary"]["payroll_cost_ratio"])
        # ...while a month window that excludes it is still assessed.
        self.assertIsNotNone(self.hra("&months=January")["summary"]["payroll_cost_ratio"])

    def test_stock_balance_carried_into_a_month_window_is_assessed(self):
        self.add(month=7)                                                      # July: stock booked
        self.add(month=8, active_customers=0, total_metered=0, stuck_meters=0, perm_staff=0, temp_staff=0)
        inf = self.infra("&months=August")["summary"]
        self.assertEqual((inf["stuck_pct"], inf["active_conn_ratio"]), (4.0, 80.0))

    def test_complete_data_and_screens_agree(self):
        self.add()
        hr, inf = self.hra()["summary"], self.infra()["summary"]
        self.assertEqual(hr["staff_per_1000_conn"], 10.0)                      # 10 staff per 1,000 active
        self.assertEqual(hr["payroll_cost_ratio"], 20.0)                       # 1,000 of 5,000 billed
        self.assertEqual((hr["m3_per_staff"], hr["wages_per_staff"], hr["fuel_per_km"]), (100.0, 60.0, 0.1))
        self.assertEqual(inf["breakdowns_per_1k_customers"], 3.0)
        self.assertEqual((inf["stuck_pct"], inf["active_conn_ratio"]), (4.0, 80.0))
        # Same measure, scope and period: dashboard, panel and alert engine agree.
        ex = self.get(f"/api/panels/executive?year={YEAR}", self.h)
        a = self.alerts()
        self.assertEqual(ex["service"]["stuck_pct"], inf["stuck_pct"])
        self.assertEqual(a["kpi_snapshot"]["stuck_pct"], inf["stuck_pct"])
        self.assertEqual(a["not_assessed"], [])

    def test_narrative_context_states_missing_metrics(self):
        self.add(nrw=None, total_metered=0)
        from app.services import narrative_engine as ne
        with self.db() as s:
            ctx = ne._build_context(s, YEAR)
        self.assertIsNone(ctx["nrw_pct"])
        self.assertIsNone(ctx["stuck_pct"])
        prompt = ne._build_prompt(ctx)
        self.assertIn("NRW Rate: not assessed", prompt)
        self.assertNotIn("None", prompt)


if __name__ == "__main__":
    unittest.main()
