from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from tests._app_loader import fresh_app
from tests.fixtures.synthetic_dataset import build_records

DEMO_ZONES = {"North": ["Lakeview", "Hillside"], "Central": ["Market"], "South": ["Riverside"]}


def _boot(tmpdir: str, tenant: str):
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 't.db'}"
    os.environ["MADZI_ENV"] = "development"
    os.environ["MADZI_SECRET_KEY"] = "k"
    os.environ["MADZI_TENANT"] = tenant
    return fresh_app()


def _utils_for(start_month: int):
    """Import app.utils against a throwaway tenant with the given FY start month."""
    import yaml
    tmp = TemporaryDirectory()
    path = Path(tmp.name) / "tenant.yaml"
    path.write_text(yaml.safe_dump({"identity": {"name": "T", "short_name": "T"},
                                    "fiscal_year": {"start_month": start_month}}))
    os.environ["MADZI_TENANT"] = str(path)
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    utils = importlib.import_module("app.utils")
    tmp.cleanup()
    return utils


class FiscalCalendarTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("MADZI_TENANT", None)

    def test_april_start_matches_legacy_behaviour(self):
        u = _utils_for(4)
        self.assertEqual(u.MONTHS_ORDER[0], "April")
        self.assertEqual(u.FY_MONTH_NOS, [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3])
        self.assertEqual(u.fy_label(2026), "FY2025/26")
        self.assertEqual(u.fy_end_year(2025, 4), 2026)
        self.assertEqual(u.fy_end_year(2026, 3), 2026)
        self.assertEqual(u.fy_quarter(4), "Q1")
        self.assertEqual(u.fy_quarter(3), "Q4")
        self.assertEqual(u.fy_dates(2026), ("2025-04-01", "2026-03-31"))
        self.assertEqual(u.fy_calendar_year(2026, 5), 2025)

    def test_july_start(self):
        u = _utils_for(7)
        self.assertEqual(u.MONTHS_LBL[:2], ["Jul", "Aug"])
        self.assertEqual(u.fy_end_year(2025, 7), 2026)
        self.assertEqual(u.fy_end_year(2026, 6), 2026)
        self.assertEqual(u.fy_quarter(9), "Q1")
        self.assertEqual(u.fy_quarter(1), "Q3")
        self.assertEqual(u.fy_dates(2026), ("2025-07-01", "2026-06-30"))
        self.assertEqual(u.fy_label_for(2025, 8), "FY2025/26")

    def test_calendar_year(self):
        u = _utils_for(1)
        self.assertEqual(u.fy_end_year(2025, 12), 2025)
        self.assertEqual(u.fy_label(2025), "FY2025")
        self.assertEqual(u.fy_dates(2024), ("2024-01-01", "2024-12-31"))
        self.assertEqual(u.fy_calendar_year(2025, 1), 2025)
        self.assertEqual(u.fy_quarter(12), "Q4")


class DemoTenantTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("MADZI_TENANT", None)

    def test_demo_tenant_end_to_end(self):
        with TemporaryDirectory() as d:
            main, database, auth, _ = _boot(d, "demo")
            with TestClient(main.app) as c:
                db = database.SessionLocal()
                db.add(database.User(username="u", password_hash=auth.hash_password("x"), role="admin"))
                db.add_all(build_records(database.Record, zones=DEMO_ZONES, fy_start=7))
                db.commit()
                db.close()
                h = {"Authorization": f"Bearer {auth.create_access_token('u', 'admin')}"}

                pub = c.get("/api/config/public").json()
                self.assertEqual(pub["short_name"], "LWU")
                self.assertNotIn("identity", pub)
                self.assertEqual(c.get("/api/config").status_code, 401)

                cfg = c.get("/api/config", headers=h).json()
                self.assertEqual(cfg["currency"]["code"], "USD")
                self.assertEqual(cfg["fiscal_year"]["months"][0], "July")
                self.assertEqual(cfg["hierarchy"]["levels"][0]["label"], "Region")
                self.assertFalse(cfg["ai_enabled"])

                logo = c.get("/api/config/logo")
                self.assertEqual(logo.status_code, 200)
                self.assertIn("svg", logo.headers["content-type"])

                html = c.get("/").text
                self.assertIn("<title>Lakeside Performance Hub</title>", html)
                self.assertNotIn("SRWB", html)
                self.assertNotIn("MWK", html)
                self.assertNotIn("__ORG_SHORT__", html)

                nrw = c.get("/api/panels/nrw?year=2025", headers=h).json()
                self.assertEqual(nrw["kpi"]["target_nrw"], 25.0)
                self.assertEqual({z["zone"] for z in nrw["by_zone"]}, set(DEMO_ZONES))
                self.assertEqual(nrw["by_zone"][0]["color"].lower()[:1], "#")

                sp = c.get("/api/strategic/scorecard", headers=h).json()
                self.assertEqual(sp["plan"], "Demo Corporate Plan 2025-2029")
                self.assertEqual(sp["fy"], "FY2025/26")

                self.assertIn("disabled", c.get("/api/insights/narrative", headers=h).json()["error"])

                years = c.get("/api/catalogue/years", headers=h).json()
                self.assertIn(2025, years)  # July 2024 .. June 2025

    def test_org_profile_overrides_yaml_identity(self):
        with TemporaryDirectory() as d:
            main, database, _, _ = _boot(d, "srwb")
            with TestClient(main.app) as c:
                self.assertEqual(c.get("/api/config/public").json()["short_name"], "SRWB")
                db = database.SessionLocal()
                db.add(database.OrgProfile(id=1, short_name="SRWB-X"))
                db.commit()
                prof = db.query(database.OrgProfile).first()
                self.assertEqual(prof.org_name, "Southern Region Water Board")  # tenant default
                self.assertEqual(prof.reporting_currency, "MWK")
                db.close()
                self.assertEqual(c.get("/api/config/public").json()["short_name"], "SRWB-X")
                self.assertIn('alt="SRWB-X"', c.get("/").text)


if __name__ == "__main__":
    unittest.main()
