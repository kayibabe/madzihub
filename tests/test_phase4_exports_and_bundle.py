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
        result = kpi_summary(
            zones=None, schemes=None, months=None, quarters=None, year=None,
            db=DummyDB(),
        )
        self.assertEqual(result, {"total_records": 0})


class TestReleaseBundleValidator(unittest.TestCase):
    def test_validator_rejects_secret_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / 'bad.zip'
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr('madzihub/data/madzihub.secret', 'secret')
                zf.writestr('madzihub/app/main.py', 'print(1)')
                zf.writestr('madzihub/requirements.txt', 'fastapi')
                zf.writestr('madzihub/.env.example', 'KEY=VALUE')
            self.assertEqual(validate_bundle(zip_path), 1)

    @staticmethod
    def _write_minimal(zf, skip_vendor=None):
        zf.writestr('madzihub/app/main.py', 'print(1)')
        zf.writestr('madzihub/requirements.txt', 'fastapi')
        zf.writestr('madzihub/.env.example', 'KEY=VALUE')
        # Offline installs need the vendored front-end files, byte-identical to the manifest.
        vendor = Path(__file__).resolve().parents[1] / 'app' / 'static' / 'vendor'
        zf.write(vendor / 'manifest.json', 'madzihub/app/static/vendor/manifest.json')
        for path in vendor.rglob('*'):
            rel = path.relative_to(vendor).as_posix()
            if path.is_file() and rel != 'manifest.json' and rel != skip_vendor:
                zf.write(path, f'madzihub/app/static/vendor/{rel}')

    def test_validator_accepts_minimal_safe_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / 'good.zip'
            with zipfile.ZipFile(zip_path, 'w') as zf:
                self._write_minimal(zf)
            self.assertEqual(validate_bundle(zip_path), 0)

    def test_validator_rejects_bundle_missing_vendored_library(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / 'no-chart.zip'
            with zipfile.ZipFile(zip_path, 'w') as zf:
                self._write_minimal(zf, skip_vendor='chart.js/chart.umd.js')
            self.assertEqual(validate_bundle(zip_path), 1)
