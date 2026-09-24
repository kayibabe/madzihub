"""Budget variance: tenant-neutral tariff handling, money text and missing data."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests._app_loader import TemporaryDirectory, fresh_app
from tests.fixtures.synthetic_dataset import build_records


def _boot(tmpdir: str):
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'budget.db'}"
    os.environ["MADZI_ENV"] = "development"
    os.environ["MADZI_SECRET_KEY"] = "k"
    os.environ["MADZI_TENANT"] = "demo"
    return fresh_app()


class BudgetVarianceTests(unittest.TestCase):
    def _client(self, d, *, budget=None, tariff=None, extra_records=()):
        main, database, auth, _ = _boot(d)
        client = TestClient(main.app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        db = database.SessionLocal()
        db.add(database.User(username="b", password_hash=auth.hash_password("x"), role="admin"))
        db.add_all(build_records(database.Record))
        db.add_all(database.Record(**r) for r in extra_records)
        db.add(database.FiscalYear(year=2025, label="FY2024/25", start_date="2024-07-01",
                                   end_date="2025-06-30", status="historical", tariff_per_m3=tariff))
        for cat, val in (budget or {}).items():
            db.add(database.BudgetLine(year=2025, category=cat, value=val, unit="USD"))
        db.commit()
        db.close()
        headers = {"Authorization": f"Bearer {auth.create_access_token('b', 'admin')}"}
        return client, headers

    def test_no_tariff_falls_back_to_realised_average(self):
        with TemporaryDirectory() as d:
            c, h = self._client(d)
            v = c.get("/api/budget/variance?year=2025", headers=h).json()
            self.assertEqual(v["meta"]["tariff_source"], "realised_billed_per_m3")
            self.assertIn("No tariff configured", v["revenue"][0]["note"])
            self.assertNotIn("1,450", str(v))
            # July-start tenant: the period starts in July, not a hardcoded April.
            self.assertTrue(v["meta"]["period"].startswith("July 2024"), v["meta"]["period"])

    def test_configured_tariff_and_scaled_money_text(self):
        with TemporaryDirectory() as d:
            c, h = self._client(d, tariff=1.4, budget={"electricity": 610_000, "chemicals": 2_400_000_000})
            v = c.get("/api/budget/variance?year=2025", headers=h).json()
            self.assertEqual(v["meta"]["tariff_source"], "configured")
            self.assertEqual(v["meta"]["tariff_per_m3"], 1.4)
            self.assertIn("Fixed tariff $ 1.40/m³", v["revenue"][0]["note"])
            notes = " ".join(r["note"] for r in v["costs"])
            self.assertIn("Budget $ 610.00K", notes)
            self.assertIn("Budget $ 2.40B", notes)

    def test_month_uploaded_without_nrw_does_not_crash(self):
        # The upload inserts only the file's columns, so a workbook with no NRW column
        # leaves nrw NULL (the ORM default of 0 never applies). When that holds for a
        # whole zone-month, SUM(nrw) is NULL: this used to 500 the budget page.
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "DataEntry"
        ws.append([None] * 5)
        ws.append(["Zone", "Scheme", "Month", "Year", "Volume Produced (m³)"])
        ws.append(["Outlying", "Gapville", "August", 2025, 50000])
        buf = io.BytesIO()
        wb.save(buf)
        with TemporaryDirectory() as d:
            c, h = self._client(d)
            files = {"file": ("gap.xlsx", buf.getvalue(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            token = c.post("/api/upload/preview", headers=h, files=files).json()["preview_token"]
            committed = c.post("/api/upload/commit", headers=h, json={"preview_token": token}).json()
            self.assertEqual(committed["rows_inserted"], 1)
            r = c.get("/api/budget/variance?year=2026", headers=h)  # August 2025 is in FY2026
            self.assertEqual(r.status_code, 200, r.text[:300])
            self.assertIn("Outlying", {z["zone"] for z in r.json()["zones"]})

    def tearDown(self):
        os.environ.pop("MADZI_TENANT", None)


if __name__ == "__main__":
    unittest.main()
