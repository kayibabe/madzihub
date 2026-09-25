"""A running demo app with an org tree and people in different scopes, for module tests.

Tree:   org ─┬─ north ── north.alpha
             ├─ central
             └─ south
People: boss (admin) · planner (org approver + strategy/report manager duties)
        nick (north contributor) · nora (north reviewer) · nate (north approver)
        sam (south contributor) · sue (south approver) · vic (org viewer, read-only account)
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests._access import add_user
from tests._app_loader import TemporaryDirectory, fresh_app


def boot(tmpdir: str, **env):
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'app.db'}"
    os.environ["MADZI_SECRET_FILE"] = str(Path(tmpdir) / "secret")
    os.environ["MADZI_FILE_STORE"] = str(Path(tmpdir) / "files")
    os.environ.update({"MADZI_ENV": "development", "MADZI_SECRET_KEY": "k", "MADZI_TENANT": "demo", **env})
    return fresh_app()


class AppFixture(unittest.TestCase):
    extra_env: dict = {}

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.main, self.database, self.auth, _ = boot(self._tmp.name, **self.extra_env)
        self.c = TestClient(self.main.app)
        self.c.__enter__()
        u = lambda *a, **k: add_user(self.database, self.auth, *a, **k)  # noqa: E731
        self.admin = u("boss", "admin")
        self.ok(self.c.post("/api/platform/org-units/sync", headers=self.admin))
        self.ok(self.c.post("/api/integration/org-units", headers=self.admin,
                            json=[{"code": "north.alpha", "name": "Alpha", "parent_code": "north"}]))
        self.planner = u("planner", "user", {"org": "approver"}, functions=("strategy_manager", "report_manager"))
        self.nick = u("nick", "user", {"north": "contributor"})
        self.nora = u("nora", "user", {"north": "reviewer"})
        self.nate = u("nate", "user", {"north": "approver"})
        self.sam = u("sam", "user", {"south": "contributor"})
        self.sue = u("sue", "user", {"south": "approver"})
        self.vic = u("vic", "viewer", {"org": "viewer"})

    def tearDown(self):
        self.c.__exit__(None, None, None)
        self._tmp.cleanup()

    def ok(self, r, code=None):
        if code is not None:
            self.assertEqual(r.status_code, code, r.text)
        else:
            self.assertLess(r.status_code, 300, r.text)
        return r.json()

    def get(self, url, h):
        return self.ok(self.c.get(url, headers=h))

    def post(self, url, h, body=None, code=None):
        return self.ok(self.c.post(url, headers=h, json=body if body is not None else {}), code)

    def put(self, url, h, body, code=None):
        return self.ok(self.c.put(url, headers=h, json=body), code)

    def status(self, method, url, h, body=None):
        return getattr(self.c, method)(url, headers=h, **({"json": body} if body is not None else {})).status_code

    def db(self):
        return self.database.SessionLocal()
