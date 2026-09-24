from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.auth import require_admin
from app.routers.upload import _validate_upload


class TestRequireAdmin(unittest.IsolatedAsyncioTestCase):
    async def test_admin_allowed(self):
        user = SimpleNamespace(role="admin")
        result = await require_admin(user)
        self.assertIs(result, user)

    async def test_non_admin_blocked(self):
        user = SimpleNamespace(role="viewer")
        with self.assertRaises(HTTPException) as ctx:
            await require_admin(user)
        self.assertEqual(ctx.exception.status_code, 403)


class TestUploadValidation(unittest.TestCase):
    def test_reject_bad_extension(self):
        file = SimpleNamespace(filename="data.csv", content_type="text/csv")
        with self.assertRaises(HTTPException) as ctx:
            _validate_upload(file, b"a,b,c")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reject_empty_upload(self):
        file = SimpleNamespace(filename="data.xlsx", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with self.assertRaises(HTTPException) as ctx:
            _validate_upload(file, b"")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_accept_valid_xlsx(self):
        file = SimpleNamespace(filename="data.xlsx", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIsNone(_validate_upload(file, b"non-empty"))
