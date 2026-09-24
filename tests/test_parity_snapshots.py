"""API parity snapshots.

Seeds a deterministic synthetic dataset, calls a fixed set of read endpoints
and compares the JSON to tests/snapshots/. The snapshots were recorded on the
unmodified opsapp import, so any diff means a refactor changed behaviour.

Re-record deliberately with:  MADZI_RECORD_SNAPSHOTS=1 python -m unittest tests.test_parity_snapshots
"""
from __future__ import annotations

import json
import os
import re
import unittest
from importlib import reload
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from tests.fixtures.synthetic_dataset import build_records

SNAP_DIR = Path(__file__).parent / "snapshots"
RECORD = os.getenv("MADZI_RECORD_SNAPSHOTS") == "1"

ENDPOINTS = [
    "/api/analytics/kpi", "/api/analytics/kpi?year=2025", "/api/analytics/monthly?year=2025",
    "/api/analytics/by-zone?year=2025", "/api/analytics/by-scheme?year=2025",
    "/api/analytics/nrw-trend", "/api/analytics/customers?year=2025",
    "/api/benchmarking/indicators?year=2025", "/api/benchmarking/monthly?year=2025",
    "/api/budget/variance?year=2025",
    "/api/catalogue/zones", "/api/catalogue/zone-schemes", "/api/catalogue/summary",
    "/api/catalogue/months", "/api/catalogue/years", "/api/catalogue/fiscal-years",
    "/api/catalogue/data-quality",
    "/api/compliance/overview", "/api/compliance/kpi-definitions",
    "/api/fiscal-years/",
    "/api/insights/summary?year=2025",
    "/api/strategic/scorecard?year=2025",
    "/api/reports/monthly?year=2025",
] + [f"/api/panels/{p}?year=2025" for p in (
    "production", "wt-ei", "customers", "connections", "stuck", "connectivity",
    "breakdowns", "pipelines", "billed", "collections", "charges", "expenses",
    "debtors", "segment-revenue", "workforce", "class-connections", "stuck-classes",
    "pipe-materials", "executive", "nrw", "metering", "profitability",
    "disconnections", "staff-productivity", "supply-continuity",
)] + [f"/api/reports/{p}?year=2025" for p in (
    "board-pack", "operations", "financial", "hra", "infrastructure",
    "zone-comparison", "nrw-analysis", "scheme-performance", "scorecard",
    "recommendations",
)]

# Keys whose values depend on wall-clock time, not on data.
_VOLATILE = re.compile(r"(generated|timestamp|as_of|_at$|^now$|run_date|report_date|last_login)", re.I)


def _normalise(obj):
    if isinstance(obj, dict):
        return {k: ("<volatile>" if _VOLATILE.search(k) else _normalise(v)) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_normalise(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def _slug(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", path.strip("/")).strip("_") + ".json"


def bootstrap(tmpdir: str, tenant: str | None = None):
    os.environ["MADZI_ENV"] = os.environ["SRWB_ENV"] = "development"
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'parity.db'}"
    os.environ["MADZI_SECRET_KEY"] = os.environ["SRWB_SECRET_KEY"] = "test-secret-key"
    if tenant:
        os.environ["MADZI_TENANT"] = tenant
    else:
        os.environ.pop("MADZI_TENANT", None)
    import app.core.config as config
    reload(config)
    try:
        import app.core.tenant as tenant_mod
        reload(tenant_mod)
    except ImportError:
        pass
    import app.database as database
    reload(database)
    import app.auth as auth
    reload(auth)
    import app.main as main
    reload(main)
    return main, database, auth


class ParitySnapshotTest(unittest.TestCase):
    maxDiff = None

    def test_endpoints_match_snapshots(self):
        with TemporaryDirectory() as tmpdir:
            main, database, auth = bootstrap(tmpdir)
            with TestClient(main.app) as client:
                db = database.SessionLocal()
                db.add(database.User(username="parity", password_hash=auth.hash_password("x"),
                                     role="admin", full_name="Parity", is_active=True))
                db.add_all(build_records(database.Record))
                db.commit()
                db.close()
                headers = {"Authorization": f"Bearer {auth.create_access_token('parity', 'admin')}"}

                SNAP_DIR.mkdir(exist_ok=True)
                failures = []
                for path in ENDPOINTS:
                    r = client.get(path, headers=headers)
                    body = {"status": r.status_code, "json": _normalise(r.json()) if r.headers.get("content-type", "").startswith("application/json") else None}
                    snap = SNAP_DIR / _slug(path)
                    text = json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
                    if RECORD or not snap.exists():
                        snap.write_text(text, encoding="utf-8")
                        continue
                    if snap.read_text(encoding="utf-8") != text:
                        failures.append(path)
                self.assertEqual(failures, [], "Endpoints diverged from parity snapshots")


if __name__ == "__main__":
    unittest.main()
