from __future__ import annotations

import os
import unittest
from importlib import reload
from pathlib import Path

from fastapi.testclient import TestClient

from tests._app_loader import TemporaryDirectory, fresh_app


def _boot(tmpdir: str, **env):
    for k in ("MADZI_DEV_PREVIEW", "MADZI_ENV", "SRWB_ENV", "MADZI_SECRET_KEY", "SRWB_SECRET_KEY"):
        os.environ.pop(k, None)
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'sec.db'}"
    os.environ["MADZI_SECRET_FILE"] = str(Path(tmpdir) / "secret")
    os.environ.update({"MADZI_ENV": "development", "MADZI_SECRET_KEY": "k", **env})
    return fresh_app()


class DevPreviewTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("MADZI_DEV_PREVIEW", None)

    def test_disabled_by_default_even_in_development(self):
        with TemporaryDirectory() as d:
            main, *_ = _boot(d)
            with TestClient(main.app) as c:
                self.assertEqual(c.post("/api/auth/dev-preview-token").status_code, 404)

    def test_opt_in_still_requires_loopback(self):
        with TemporaryDirectory() as d:
            main, *_ = _boot(d, MADZI_DEV_PREVIEW="true")
            with TestClient(main.app) as c:  # TestClient host is "testclient", not loopback
                self.assertEqual(c.post("/api/auth/dev-preview-token").status_code, 403)

    def test_opt_in_ignored_outside_development(self):
        with TemporaryDirectory() as d:
            _, _, _, config = _boot(d, MADZI_DEV_PREVIEW="true", MADZI_ENV="staging")
            self.assertFalse(config.settings.dev_preview_allowed)


class LegacyEnvTests(unittest.TestCase):
    def test_srwb_prefixed_vars_still_work(self):
        with TemporaryDirectory() as d:
            _, _, _, config = _boot(d)
            os.environ.pop("MADZI_SECRET_KEY")
            os.environ["SRWB_SECRET_KEY"] = "legacy-key"
            reload(config)
            self.assertEqual(config.settings.secret_key, "legacy-key")
            os.environ.pop("SRWB_SECRET_KEY")


class TokenValidationTests(unittest.TestCase):
    """PyJWT-backed token checks: only valid, unexpired HS256 tokens signed with our key pass."""

    def test_token_validation(self):
        import base64
        import json
        from datetime import datetime, timedelta

        import jwt

        with TemporaryDirectory() as d:
            main, database, auth, _ = _boot(d)
            with TestClient(main.app) as c:
                db = database.SessionLocal()
                db.add(database.User(username="tok", password_hash=auth.hash_password("x"), role="viewer"))
                db.commit()
                db.close()
                url = "/api/catalogue/zones"

                def status_for(token):
                    return c.get(url, headers={"Authorization": f"Bearer {token}"}).status_code

                good = auth.create_access_token("tok", "viewer")
                self.assertEqual(status_for(good), 200)

                now = datetime.utcnow()
                expired = jwt.encode({"sub": "tok", "role": "viewer", "iat": now - timedelta(hours=9),
                                      "exp": now - timedelta(hours=1)}, auth.SECRET_KEY, algorithm="HS256")
                self.assertEqual(status_for(expired), 401)

                forged = jwt.encode({"sub": "tok", "exp": now + timedelta(hours=1)},
                                    "some-other-key-that-is-long-enough-32b", algorithm="HS256")
                self.assertEqual(status_for(forged), 401)

                def b64(obj):
                    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
                unsigned = f'{b64({"alg": "none", "typ": "JWT"})}.{b64({"sub": "tok"})}.'
                self.assertEqual(status_for(unsigned), 401)

                head, body, sig = good.split(".")
                tampered = f'{head}.{b64({"sub": "admin", "role": "admin"})}.{sig}'
                self.assertEqual(status_for(tampered), 401)
                self.assertEqual(status_for("not-a-jwt"), 401)


class MustChangePasswordTests(unittest.TestCase):
    def test_bootstrap_admin_must_change_password_before_using_api(self):
        with TemporaryDirectory() as d:
            main, database, auth, _ = _boot(d)
            with TestClient(main.app) as c:
                db = database.SessionLocal()
                admin = db.query(database.User).filter_by(username="admin").one()
                self.assertTrue(admin.must_change_password)
                admin.password_hash = auth.hash_password("temp-pass-1")
                db.commit()
                db.close()

                r = c.post("/api/auth/login", json={"username": "admin", "password": "temp-pass-1"})
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.json()["must_change_password"])
                h = {"Authorization": f"Bearer {r.json()['access_token']}"}

                blocked = c.get("/api/catalogue/zones", headers=h)
                self.assertEqual(blocked.status_code, 403)
                self.assertEqual(blocked.json()["detail"], "password_change_required")
                self.assertEqual(c.get("/api/auth/me", headers=h).status_code, 200)

                same = c.post("/api/auth/change-password", headers=h,
                              json={"current_password": "temp-pass-1", "new_password": "temp-pass-1"})
                self.assertEqual(same.status_code, 400)
                ok = c.post("/api/auth/change-password", headers=h,
                            json={"current_password": "temp-pass-1", "new_password": "a-new-pass-2"})
                self.assertEqual(ok.status_code, 204)
                self.assertEqual(c.get("/api/catalogue/zones", headers=h).status_code, 200)

    def test_reset_script_has_no_fixed_password(self):
        text = (Path(__file__).resolve().parents[1] / "scripts" / "reset_admin.py").read_text()
        self.assertNotIn("Admin123", text)
        self.assertFalse((Path(__file__).resolve().parents[1] / "reset_password.py").exists())


if __name__ == "__main__":
    unittest.main()
