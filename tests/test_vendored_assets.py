"""Front-end libraries and fonts are vendored: no CDN at runtime, files match the manifest."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from tests._app_loader import fresh_app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VENDOR = STATIC / "vendor"
MANIFEST = json.loads((VENDOR / "manifest.json").read_text(encoding="utf-8"))
EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", re.I)


class VendoredFilesTests(unittest.TestCase):
    def test_files_match_manifest_and_nothing_is_unlisted(self):
        on_disk = {p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*") if p.is_file()} - {"manifest.json"}
        self.assertEqual(on_disk, set(MANIFEST))
        for rel, info in MANIFEST.items():
            with self.subTest(file=rel):
                self.assertEqual(hashlib.sha256((VENDOR / rel).read_bytes()).hexdigest(), info["sha256"])

    def test_every_library_ships_its_licence(self):
        packages = {info["package"] for info in MANIFEST.values() if info["package"] != "madzihub"}
        licensed = {info["package"] for rel, info in MANIFEST.items() if Path(rel).name.startswith("LICENSE")}
        self.assertEqual(packages, licensed)

    def test_fonts_css_points_only_at_vendored_files(self):
        css = (VENDOR / "fonts" / "fonts.css").read_text(encoding="utf-8")
        urls = set(re.findall(r"url\(([^)]+)\)", css))
        self.assertTrue(urls)
        for url in urls:
            self.assertIn(f"fonts/{url}", MANIFEST)
        self.assertIn("font-family:'Inter'", css)
        self.assertIn("font-family:'IBM Plex Mono'", css)

    def test_frontend_loads_nothing_from_other_origins(self):
        for path in [STATIC / "index.html", *STATIC.glob("assets/css/*.css")]:
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertIsNone(EXTERNAL.search(text), "external src/href found")
                self.assertNotRegex(text, r"@import\s+url\(\s*['\"]?https?:")
        refs = re.findall(r'(?:src|href)="/static/vendor/([^"?]+)', (STATIC / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(sorted(refs), sorted(["chart.js/chart.umd.js", "xlsx/xlsx.full.min.js",
                                               "dompurify/purify.min.js", "fonts/fonts.css"]))


class ServedTests(unittest.TestCase):
    def test_app_serves_vendored_assets_and_page_references_them(self):
        with TemporaryDirectory() as d:
            os.environ["DATABASE_URL"] = f"sqlite:///{Path(d) / 'v.db'}"
            os.environ["MADZI_SECRET_FILE"] = str(Path(d) / "secret")
            os.environ.update({"MADZI_ENV": "development", "MADZI_SECRET_KEY": "k"})
            main, *_ = fresh_app()
            with TestClient(main.app) as c:
                page = c.get("/").text
                self.assertIn("/static/vendor/chart.js/chart.umd.js", page)
                self.assertIsNone(EXTERNAL.search(page))
                for rel in ("chart.js/chart.umd.js", "dompurify/purify.min.js", "xlsx/xlsx.full.min.js",
                            "fonts/fonts.css", "fonts/inter/inter-latin-wght-normal.woff2"):
                    with self.subTest(file=rel):
                        r = c.get(f"/static/vendor/{rel}")
                        self.assertEqual(r.status_code, 200)
                        self.assertEqual(hashlib.sha256(r.content).hexdigest(), MANIFEST[rel]["sha256"])


if __name__ == "__main__":
    unittest.main()
