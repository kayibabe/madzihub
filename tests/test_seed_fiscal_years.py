"""scripts/seed_fiscal_years.py: tenant budget.yaml → fiscal-year tables."""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
import unittest
from pathlib import Path

from tests._app_loader import TemporaryDirectory

RIVERBEND = str(Path(__file__).parent / "fixtures" / "tenants" / "riverbend" / "tenant.yaml")


def _fresh_seed(tmpdir: str, tenant: str):
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'seed.db'}"
    os.environ["MADZI_ENV"] = "development"
    os.environ["MADZI_TENANT"] = tenant
    for name in list(sys.modules):
        if name == "app" or name.startswith("app.") or name == "scripts.seed_fiscal_years":
            del sys.modules[name]
    seed = importlib.import_module("scripts.seed_fiscal_years")
    return seed, importlib.import_module("app.database")


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        fn(*args, **kwargs)
    return out.getvalue()


class SeedFiscalYearsTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("MADZI_TENANT", None)

    def test_demo_budget_seeds_and_is_idempotent(self):
        with TemporaryDirectory() as d:
            seed, database = _fresh_seed(d, "demo")
            _quiet(seed.seed)
            _quiet(seed.seed)  # second run must not duplicate anything
            db = database.SessionLocal()
            try:
                years = {fy.year: fy for fy in db.query(database.FiscalYear)}
                self.assertEqual(sorted(years), list(range(2022, 2031)))
                self.assertEqual(years[2027].status, "current")
                self.assertEqual(years[2026].status, "historical")
                self.assertEqual(years[2028].status, "future")
                # July-start tenant: dates follow the tenant calendar, not April.
                self.assertEqual((years[2027].start_date, years[2027].end_date), ("2026-07-01", "2027-06-30"))
                self.assertEqual(years[2027].tariff_per_m3, 1.4)

                lines = {b.category: b for b in db.query(database.BudgetLine).filter_by(year=2027)}
                self.assertEqual(lines["water_sales"].unit, "USD")        # money lines default to the tenant currency
                self.assertEqual(lines["vol_produced"].unit, "m3")
                self.assertEqual((lines["tariff_per_m3"].value, lines["tariff_per_m3"].unit), (1.4, "USD/m3"))
                self.assertEqual(db.query(database.BudgetLine).filter_by(year=2027, category="water_sales").count(), 1)
                shares = db.query(database.BudgetZoneShare).filter_by(year=2027).all()
                self.assertAlmostEqual(sum(s.rev_share for s in shares), 1.0)
                self.assertEqual({s.zone for s in shares}, {"North", "Central", "South"})
            finally:
                db.close()

    def test_refresh_replaces_one_year(self):
        with TemporaryDirectory() as d:
            seed, database = _fresh_seed(d, "demo")
            _quiet(seed.seed)
            db = database.SessionLocal()
            db.query(database.BudgetLine).filter_by(year=2027, category="water_sales").one().value = 1.0
            db.commit()
            db.close()
            out = _quiet(seed.seed, refresh_fy=2027)
            self.assertIn("cleared FY2027", out)
            db = database.SessionLocal()
            self.assertEqual(db.query(database.BudgetLine).filter_by(year=2027, category="water_sales").one().value, 4_116_000)
            db.close()

    def test_tenant_without_budget_file_is_skipped(self):
        with TemporaryDirectory() as d:
            seed, database = _fresh_seed(d, RIVERBEND)
            out = _quiet(seed.seed)
            self.assertIn("[SKIP]", out)


if __name__ == "__main__":
    unittest.main()
