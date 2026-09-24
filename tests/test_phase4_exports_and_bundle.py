from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.routers.analytics import kpi_summary
from scripts.validate_release_bundle import validate_bundle


class DummyQuery:
    def all(self):
        return []


class DummyDB:
    def query(self, *_args, **_kwargs):
        return DummyQuery()


class TestAnalyticsKpiEmpty(unittest.TestCase):
    def test_kpi_empty_rows_safe(self):
        result = kpi_summary(db=DummyDB())
        self.assertEqual(result, {"total_records": 0})


class TestReleaseBundleValidator(unittest.TestCase):
    def test_validator_rejects_secret_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / 'bad.zip'
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr('opswebmobile/data/srwb.secret', 'secret')
                zf.writestr('opswebmobile/app/main.py', 'print(1)')
                zf.writestr('opswebmobile/requirements.txt', 'fastapi')
                zf.writestr('opswebmobile/.env.example', 'KEY=VALUE')
            self.assertEqual(validate_bundle(zip_path), 1)

    def test_validator_accepts_minimal_safe_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / 'good.zip'
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr('opswebmobile/app/main.py', 'print(1)')
                zf.writestr('opswebmobile/requirements.txt', 'fastapi')
                zf.writestr('opswebmobile/.env.example', 'KEY=VALUE')
            self.assertEqual(validate_bundle(zip_path), 0)
