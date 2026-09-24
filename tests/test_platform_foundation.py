"""Shared governance foundation: scope (deny by default), audit, periods, actions, links, notices.

Journeys use a demo install with the tree  org -> north (-> north.alpha), central, south
and three people: an administrator, a North-only reviewer and a South-only contributor.
"""
from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests._access import add_user
from tests._app_loader import TemporaryDirectory, fresh_app


def boot(tmpdir: str):
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'p.db'}"
    os.environ["MADZI_SECRET_FILE"] = str(Path(tmpdir) / "secret")
    os.environ.update({"MADZI_ENV": "development", "MADZI_SECRET_KEY": "k", "MADZI_TENANT": "demo"})
    return fresh_app()


class PlatformFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.main, self.database, self.auth, _ = boot(self._tmp.name)
        self.c = TestClient(self.main.app)
        self.c.__enter__()
        self.admin = add_user(self.database, self.auth, "boss", "admin")
        r = self.c.post("/api/platform/org-units/sync", headers=self.admin)
        self.assertEqual(r.json()["created"], 4, r.text)          # org, north, central, south
        self.ok(self.c.post("/api/integration/org-units", headers=self.admin,
                            json=[{"code": "north.alpha", "name": "Alpha", "parent_code": "north"}]))
        self.north = add_user(self.database, self.auth, "nora", "user", {"north": "reviewer"})
        self.north2 = add_user(self.database, self.auth, "nick", "user", {"north": "contributor"})
        self.south = add_user(self.database, self.auth, "sam", "user", {"south": "contributor"})
        self.nobody = add_user(self.database, self.auth, "nemo", "user")

    def tearDown(self):
        self.c.__exit__(None, None, None)
        self._tmp.cleanup()

    def ok(self, r, code=None):
        if code is not None:
            self.assertEqual(r.status_code, code, r.text)
        else:
            self.assertLess(r.status_code, 300, r.text)
        return r.json()

    def action(self, headers, unit, owner, **extra):
        body = {"title": f"Fix {unit}", "owner": owner, "org_unit_code": unit, **extra}
        return self.ok(self.c.post("/api/platform/actions", json=body, headers=headers), 201)


class ScopeTests(PlatformFixture):
    def test_no_grant_means_no_access(self):
        me = self.ok(self.c.get("/api/platform/me", headers=self.nobody))
        self.assertFalse(me["org_wide"])
        self.assertEqual(me["units"], {})
        r = self.c.get("/api/catalogue/zones", headers=self.nobody)
        self.assertEqual(r.status_code, 403)
        self.assertIn("organisation_scope_required", r.json()["detail"])
        self.action(self.admin, "north", "nora")
        self.assertEqual(self.ok(self.c.get("/api/platform/actions", headers=self.nobody)), [])
        self.assertEqual(self.ok(self.c.get("/api/platform/org-units", headers=self.nobody)), [])
        self.assertEqual(self.c.get("/api/position?org_unit=org", headers=self.nobody).status_code, 404)

    def test_region_scoped_user_never_sees_another_region(self):
        south_action = self.action(self.admin, "south", "sam")
        north_action = self.action(self.admin, "north.alpha", "nora")   # below the grant: covered
        listed = self.ok(self.c.get("/api/platform/actions", headers=self.north))
        self.assertEqual([a["id"] for a in listed], [north_action["id"]])
        sid = south_action["id"]
        for url in (f"/api/platform/actions/{sid}", f"/api/platform/history?type=action&id={sid}",
                    f"/api/platform/comments?type=action&id={sid}", f"/api/platform/links?type=action&id={sid}",
                    "/api/position?org_unit=south", "/api/position/vol_produced?org_unit=south"):
            self.assertEqual(self.c.get(url, headers=self.north).status_code, 404, url)
        # Writes into the other region are refused the same way.
        r = self.c.post("/api/platform/actions", headers=self.north,
                        json={"title": "x", "owner": "nora", "org_unit_code": "south"})
        self.assertEqual(r.status_code, 404)
        r = self.c.post("/api/platform/comments", headers=self.north,
                        json={"entity_type": "action", "entity_id": str(sid), "body": "peek"})
        self.assertEqual(r.status_code, 404)
        r = self.c.post(f"/api/platform/actions/{sid}/transition", headers=self.north, json={"name": "start"})
        self.assertEqual(r.status_code, 404)
        # Organisation-wide dashboards, reports and exports are closed to a region-scoped user.
        for url in ("/api/catalogue/zones", "/api/analytics/kpi", "/api/records/export/csv",
                    "/api/strategic/scorecard", "/api/reports/board-pack"):
            self.assertEqual(self.c.get(url, headers=self.north).status_code, 403, url)
        units = {u["code"] for u in self.ok(self.c.get("/api/platform/org-units", headers=self.north))}
        self.assertEqual(units, {"north", "north.alpha"})
        units = {u["code"] for u in self.ok(self.c.get("/api/position/org-units", headers=self.north))}
        self.assertEqual(units, {"north", "north.alpha"})
        # An owner outside the unit's scope cannot be assigned.
        r = self.c.post("/api/platform/actions", headers=self.north,
                        json={"title": "x", "owner": "sam", "org_unit_code": "north"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("no access", r.json()["detail"])

    def test_links_never_reveal_out_of_scope_records(self):
        a_north = self.action(self.admin, "north", "nora")
        a_south = self.action(self.admin, "south", "sam")
        # North reviewer cannot link to a South record ...
        r = self.c.post("/api/platform/links", headers=self.north,
                        json={"from_type": "action", "from_id": str(a_north["id"]), "to_type": "action",
                              "to_id": str(a_south["id"])})
        self.assertEqual(r.status_code, 404)
        # ... and an admin-made cross-region link is counted as hidden, not shown.
        self.ok(self.c.post("/api/platform/links", headers=self.admin,
                            json={"from_type": "action", "from_id": str(a_north["id"]), "to_type": "action",
                                  "to_id": str(a_south["id"]), "relation": "related"}), 201)
        seen = self.ok(self.c.get(f"/api/platform/links?type=action&id={a_north['id']}", headers=self.north))
        self.assertEqual((seen["links"], seen["hidden"]), ([], 1))
        full = self.ok(self.c.get(f"/api/platform/links?type=action&id={a_north['id']}", headers=self.admin))
        self.assertEqual(full["links"][0]["other"]["id"], str(a_south["id"]))
        # Unknown record types are refused rather than guessed.
        r = self.c.get("/api/platform/links?type=nonsense&id=1", headers=self.admin)
        self.assertEqual(r.status_code, 422)

    def test_read_only_account_cannot_write_even_with_a_high_grant(self):
        ro = add_user(self.database, self.auth, "vera", "viewer", {"north": "approver"})
        r = self.c.post("/api/platform/actions", headers=ro,
                        json={"title": "x", "owner": "nora", "org_unit_code": "north"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.get("/api/platform/actions", headers=ro).status_code, 200)

    def test_org_wide_grant_restores_dashboards(self):
        wide = add_user(self.database, self.auth, "olga", "viewer", {"org": "viewer"})
        self.assertEqual(self.c.get("/api/catalogue/zones", headers=wide).status_code, 200)
        self.assertTrue(self.ok(self.c.get("/api/platform/me", headers=wide))["org_wide"])


class RouteSweepTests(PlatformFixture):
    """Every /api route must be public by design, admin-only, org-wide, or scope-aware."""

    PUBLIC = {"/api/auth/login", "/api/auth/dev-preview-token", "/api/config/public", "/api/config/logo",
              "/api/ingest/{code}"}
    # Authenticated but about the caller only, or installation config (no unit data).
    SELF_ONLY = {"/api/auth/me", "/api/auth/change-password", "/api/config"}

    @staticmethod
    def _deps(dependant):
        stack, seen = [dependant], []
        while stack:
            d = stack.pop()
            if d.call is not None:
                seen.append(getattr(d.call, "__name__", ""))
            stack.extend(d.dependencies)
        return set(seen)

    def test_every_api_route_is_classified(self):
        from fastapi.routing import APIRoute
        unclassified = []
        for route in self.main.app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
                continue
            if route.path in self.PUBLIC or route.path in self.SELF_ONLY:
                continue
            deps = self._deps(route.dependant)
            if deps & {"require_admin", "require_org_wide", "get_scope"}:
                continue
            unclassified.append(f"{sorted(route.methods)} {route.path}")
        self.assertEqual(unclassified, [], "routes without an admin, org-wide or scope guard")

    def test_scoped_user_is_refused_on_every_org_wide_get(self):
        from fastapi.routing import APIRoute
        checked = 0
        for route in self.main.app.routes:
            if not isinstance(route, APIRoute) or "GET" not in route.methods or "{" in route.path:
                continue
            if "require_org_wide" not in self._deps(route.dependant):
                continue
            r = self.c.get(route.path, headers=self.north)
            self.assertEqual(r.status_code, 403, route.path)
            checked += 1
        self.assertGreater(checked, 40)


class ActionWorkflowTests(PlatformFixture):
    def test_full_lifecycle_with_segregation_and_reasons(self):
        a = self.action(self.north2, "north", "nick", due_date=(date.today() + timedelta(days=30)).isoformat())
        self.assertEqual(a["ref"], f"ACT-{a['id']:04d}")
        aid = a["id"]
        tr = lambda h, name, note=None: self.c.post(f"/api/platform/actions/{aid}/transition", headers=h,
                                                    json={"name": name, "note": note})
        self.assertEqual(tr(self.north2, "close").status_code, 409)          # illegal: not completed
        self.assertEqual(self.ok(tr(self.north2, "start"))["status"], "in_progress")
        r = tr(self.north2, "complete")
        self.assertEqual(r.status_code, 422)                                   # completion needs a note
        self.assertEqual(self.ok(tr(self.north2, "complete", "Valve replaced"))["status"], "completed")
        self.assertEqual(tr(self.north2, "close").status_code, 403)          # owner cannot verify own work
        self.assertEqual(tr(self.north, "reopen").status_code, 422)          # reopen needs a reason
        self.assertEqual(self.ok(tr(self.north, "close"))["status"], "closed")
        self.assertEqual(self.c.put(f"/api/platform/actions/{aid}", headers=self.north,
                                    json={"title": "rename"}).status_code, 422)   # closed: reopen first
        self.assertEqual(self.ok(tr(self.north, "reopen", "Leak recurred"))["status"], "in_progress")

        detail = self.ok(self.c.get(f"/api/platform/actions/{aid}", headers=self.north))
        actions = [e["action"] for e in detail["history"]]
        self.assertEqual(actions, ["action.create", "action.start", "action.complete", "action.close",
                                   "action.reopen"])
        reopen = detail["history"][-1]
        self.assertEqual((reopen["before"]["status"], reopen["after"]["status"], reopen["reason"]),
                         ("closed", "in_progress", "Leak recurred"))
        # The owner was told their action was reopened.
        notes = self.ok(self.c.get("/api/platform/notifications", headers=self.north2))
        self.assertTrue(any("in progress" in n["title"] for n in notes), notes)

    def test_due_date_change_needs_reason_and_owner_cannot_redate(self):
        due = date.today() + timedelta(days=10)
        a = self.action(self.north, "north", "nick", due_date=due.isoformat())
        url = f"/api/platform/actions/{a['id']}"
        later = (due + timedelta(days=20)).isoformat()
        self.assertEqual(self.c.put(url, headers=self.north2, json={"due_date": later, "reason": "x"}).status_code, 403)
        self.assertEqual(self.c.put(url, headers=self.north2, json={"progress_note": "halfway"}).status_code, 200)
        self.assertEqual(self.c.put(url, headers=self.north, json={"due_date": later}).status_code, 422)
        self.ok(self.c.put(url, headers=self.north, json={"due_date": later, "reason": "Pipe delivery delayed"}))
        hist = self.ok(self.c.get(f"/api/platform/history?type=action&id={a['id']}", headers=self.north))
        change = [e for e in hist if e["action"] == "action.update" and "due_date" in e["after"]][0]
        self.assertEqual((change["before"]["due_date"], change["after"]["due_date"], change["reason"]),
                         (due.isoformat(), later, "Pipe delivery delayed"))

    def test_cancel_requires_reviewer_and_reason(self):
        a = self.action(self.north2, "north", "nick")
        url = f"/api/platform/actions/{a['id']}/transition"
        self.assertEqual(self.c.post(url, headers=self.north2, json={"name": "cancel", "note": "no"}).status_code, 403)
        self.assertEqual(self.c.post(url, headers=self.north, json={"name": "cancel"}).status_code, 422)
        self.assertEqual(self.ok(self.c.post(url, headers=self.north, json={"name": "cancel", "note": "Duplicate"}))
                         ["status"], "cancelled")

    def test_my_work_and_reminders(self):
        overdue = self.action(self.north, "north", "nick", due_date=(date.today() - timedelta(days=2)).isoformat())
        self.action(self.north, "north", "nick", due_date=(date.today() + timedelta(days=3)).isoformat())
        work = self.ok(self.c.get("/api/platform/my-work", headers=self.north2))
        self.assertEqual((len(work["actions"]), work["overdue_actions"]), (2, 1))
        from app.platform.notifications import run_reminders
        db = self.database.SessionLocal()
        try:
            self.assertEqual(run_reminders(db), 2)
            self.assertEqual(run_reminders(db), 0)         # once per item per day
        finally:
            db.close()
        kinds = [n["kind"] for n in self.ok(self.c.get("/api/platform/notifications", headers=self.north2))]
        self.assertIn("action_overdue", kinds)
        self.assertIn("action_due_soon", kinds)
        n = self.ok(self.c.get("/api/platform/notifications?unread_only=true", headers=self.north2))
        self.ok(self.c.post(f"/api/platform/notifications/{n[0]['id']}/read", headers=self.north2))
        self.assertEqual(self.c.post(f"/api/platform/notifications/{n[0]['id']}/read",
                                     headers=self.north).status_code, 404)   # not theirs
        self.assertTrue(overdue["id"])


class PeriodTests(PlatformFixture):
    def test_lock_blocks_writes_and_reopen_needs_reason(self):
        from app.platform import periods
        from app.platform.errors import PeriodLocked

        rows = self.ok(self.c.post("/api/platform/periods/fiscal-year", headers=self.admin,
                                   json={"fiscal_year": 2027}), 201)
        self.assertEqual(sorted({p["period_type"] for p in rows}), ["month", "quarter", "year"])
        self.assertEqual(len(rows), 17)
        year = next(p for p in rows if p["period_type"] == "year")
        self.assertEqual((year["start_date"], year["end_date"], year["label"]), ("2026-07-01", "2027-06-30", "FY2026/27"))
        month = next(p for p in rows if p["period_type"] == "month" and p["start_date"] == "2026-09-01")
        self.assertEqual(self.c.post(f"/api/platform/periods/{year['id']}/lock", headers=self.north).status_code, 403)
        self.ok(self.c.post(f"/api/platform/periods/{year['id']}/lock", headers=self.admin, json={}))
        db = self.database.SessionLocal()
        try:
            with self.assertRaises(PeriodLocked):
                periods.assert_open(db, month["id"])        # a month inside a locked year
        finally:
            db.close()
        r = self.c.post(f"/api/platform/periods/{year['id']}/reopen", headers=self.admin, json={"reason": " "})
        self.assertEqual(r.status_code, 422)
        self.ok(self.c.post(f"/api/platform/periods/{year['id']}/reopen", headers=self.admin,
                            json={"reason": "Audit adjustment to Q1 production"}))
        trail = self.ok(self.c.get("/api/platform/audit?entity_type=period", headers=self.admin))
        self.assertEqual([e["action"] for e in trail][:2], ["period.reopen", "period.lock"])
        self.assertEqual(trail[0]["reason"], "Audit adjustment to Q1 production")
        self.assertEqual(self.c.get("/api/platform/audit", headers=self.north).status_code, 403)

    def test_startup_creates_current_fiscal_year(self):
        rows = self.ok(self.c.get("/api/platform/periods?period_type=year", headers=self.north))
        self.assertEqual(len(rows), 1)


class AuditImmutabilityTests(PlatformFixture):
    def test_audit_events_cannot_be_changed_or_deleted(self):
        self.action(self.admin, "north", "nora")
        with self.database.engine.connect() as conn:
            for sql in ("UPDATE audit_events SET actor = 'mallory'", "DELETE FROM audit_events"):
                with self.assertRaises(Exception) as ctx:
                    conn.execute(text(sql))
                self.assertIn("append-only", str(ctx.exception))
                conn.rollback()


class AccessAdminTests(PlatformFixture):
    def test_admin_sets_grants_and_duties_with_audit(self):
        users = self.ok(self.c.get("/api/platform/access/users", headers=self.admin))
        sam = next(u for u in users["users"] if u["username"] == "sam")
        url = f"/api/platform/access/users/{sam['id']}"
        self.assertEqual(self.c.put(url, headers=self.north, json={"grants": []}).status_code, 403)
        bad = self.c.put(url, headers=self.admin, json={"grants": [{"org_unit_code": "atlantis", "role": "viewer"}]})
        self.assertEqual(bad.status_code, 422)
        bad = self.c.put(url, headers=self.admin, json={"grants": [], "functions": ["wizard"]})
        self.assertEqual(bad.status_code, 422)
        out = self.ok(self.c.put(url, headers=self.admin, json={
            "grants": [{"org_unit_code": "south", "role": "approver"}, {"org_unit_code": "central", "role": "viewer"}],
            "functions": ["risk_manager"], "reason": "Acting regional manager"}))
        self.assertEqual([(g["org_unit_code"], g["role"]) for g in out["grants"]],
                         [("central", "viewer"), ("south", "approver")])
        me = self.ok(self.c.get("/api/platform/me", headers=self.south))
        self.assertEqual(me["units"], {"central": "viewer", "south": "approver"})
        self.assertEqual(me["functions"], ["risk_manager"])
        trail = self.ok(self.c.get("/api/platform/audit?entity_type=user", headers=self.admin))
        self.assertEqual(trail[0]["reason"], "Acting regional manager")
        self.assertEqual(trail[0]["before"]["grants"][0]["org_unit_code"], "south")

    def test_admin_holds_duties_except_private_hr(self):
        me = self.ok(self.c.get("/api/platform/me", headers=self.admin))
        self.assertIn("auditor", me["functions"])
        self.assertNotIn("hr_officer", me["functions"])


class MigrationGrantTests(unittest.TestCase):
    def test_upgrade_keeps_existing_users_access_explicitly(self):
        from alembic import command
        with TemporaryDirectory() as d:
            main, database, auth, _ = boot(d)
            import app.migrate as migrate
            with database.engine.begin() as conn:
                command.upgrade(migrate.alembic_config(conn), "0001")
                conn.execute(text("INSERT INTO users (username, password_hash, role, is_active, "
                                  "must_change_password) VALUES ('legacy', 'h', 'viewer', 1, 0), "
                                  "('root', 'h', 'admin', 1, 0)"))
            backup, rev = migrate.upgrade()
            self.assertEqual(rev, migrate.head_revision())
            self.assertTrue(backup.exists())
            with database.engine.connect() as conn:
                grants = conn.execute(text("SELECT u.username, g.org_unit_code, g.role FROM user_org_roles g "
                                           "JOIN users u ON u.id = g.user_id")).fetchall()
                events = conn.execute(text("SELECT actor, action FROM audit_events")).fetchall()
            self.assertEqual([tuple(g) for g in grants], [("legacy", "org", "viewer")])
            self.assertEqual([tuple(e) for e in events], [("migration:0002", "access.update")])
            with TestClient(main.app) as c:
                h = {"Authorization": f"Bearer {auth.create_access_token('legacy', 'viewer')}"}
                self.assertEqual(c.get("/api/catalogue/zones", headers=h).status_code, 200)


if __name__ == "__main__":
    unittest.main()
