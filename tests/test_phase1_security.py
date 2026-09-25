from __future__ import annotations

import os
from importlib import reload
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


def _bootstrap_app(tmpdir: str):
    os.environ["MADZI_ENV"] = "development"
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'test.db'}"
    os.environ["MADZI_SECRET_KEY"] = "test-secret-key"
    os.environ["MADZI_ALLOWED_ORIGINS"] = "http://localhost:8000"

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


def test_first_run_banner_survives_a_cp1252_console(monkeypatch):
    # A standard Windows console cannot encode the box drawing; the one-time password must still print.
    import io
    import re
    import sys
    from unittest import mock

    from app import auth

    db = mock.MagicMock()
    db.query.return_value.count.return_value = 0          # no users yet: first run
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    auth.ensure_default_admin(db)
    console.flush()
    db.commit.assert_called_once()
    out = raw.getvalue().decode("cp1252")
    assert "+====" in out and "MadziHub - First-Run Setup" in out
    assert re.search(r"Password : [A-Za-z0-9_-]{16}", out)
