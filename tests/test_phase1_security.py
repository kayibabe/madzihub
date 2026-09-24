from __future__ import annotations

import os
from importlib import reload
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


def _bootstrap_app(tmpdir: str):
    os.environ["SRWB_ENV"] = "development"
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'test.db'}"
    os.environ["SRWB_SECRET_KEY"] = "test-secret-key"
    os.environ["SRWB_ALLOWED_ORIGINS"] = "http://localhost:8000"

    import app.core.config as config
    reload(config)
    import app.database as database
    reload(database)
    import app.auth as auth
    reload(auth)
    import app.routers.users as users
    reload(users)
    import app.main as main
    reload(main)
    return main.app, database.SessionLocal, auth


def test_protected_routes_require_auth():
    with TemporaryDirectory() as tmpdir:
        app, _, _ = _bootstrap_app(tmpdir)
        client = TestClient(app)
        r = client.get("/api/reports/summary")
        assert r.status_code in {401, 404}


def test_debug_status_requires_admin():
    with TemporaryDirectory() as tmpdir:
        app, _, auth = _bootstrap_app(tmpdir)
        client = TestClient(app)

        token = auth.create_access_token("viewer", "viewer")
        r = client.get("/api/debug/db-status", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401 or r.status_code == 403
