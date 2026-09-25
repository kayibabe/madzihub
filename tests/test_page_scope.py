"""Slice 1b (UX-02) page-scope contract: every page states which top-bar filters govern it.

Static checks over the shipped front end; they do not depend on the calendar or demo seed.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
CORE = (STATIC / "assets" / "js" / "app-core.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
KINDS = {"dashboard", "year_only", "latest", "queue", "strategy", "governed", "setup"}


def _page_scope() -> dict[str, str]:
    block = re.search(r"const PAGE_SCOPE=\{(.*?)\n\};", CORE, re.S).group(1)
    return {k: v for k, v in re.findall(r"'?([\w-]+)'?\s*:\s*'(\w+)'", block)}


def _module_pages() -> set[str]:
    return {m for f in (STATIC / "assets" / "js").glob("mod-*.js")
            for m in re.findall(r"MZ\.page\('([\w-]+)'", f.read_text(encoding="utf-8"))}


class PageScopeContractTest(unittest.TestCase):
    def test_every_page_is_classified_and_no_entry_is_stale(self):
        pages = set(re.findall(r'id="page-([a-z0-9-]+)"', INDEX))
        scope = _page_scope()
        self.assertEqual(sorted(pages - set(scope)), [], "pages without a scope classification")
        self.assertEqual(sorted(set(scope) - pages), [], "classified pages that no longer exist")
        self.assertEqual(set(scope.values()) - KINDS, set())

    def test_module_pages_are_never_presented_as_globally_filtered(self):
        # MZ.api does not send the global year, zone or period filters.
        scope = _page_scope()
        wrong = {p: scope.get(p) for p in _module_pages() if scope.get(p) in (None, "dashboard", "year_only")}
        self.assertEqual(wrong, {})

    def test_dashboards_load_through_the_filtered_api(self):
        loaders = re.search(r"const map=\{(.*?)\};", CORE, re.S).group(1)
        for page, kind in _page_scope().items():
            if kind == "dashboard":
                self.assertRegex(loaders, rf"'?{re.escape(page)}'?\s*:", page)

    def test_pages_that_ignore_filters_are_not_dashboards(self):
        scope = _page_scope()
        # Strategic Position reads /api/position with its own unit and period controls.
        self.assertEqual(scope["position"], "strategy")
        # Compliance endpoints take no year, zone or period parameters.
        self.assertEqual((scope["compliance"], scope["water-quality"]), ("latest", "latest"))
        # The strategic plan scorecard takes the year only.
        self.assertEqual(scope["strategic"], "year_only")
        # Work queues are cross-year and say so.
        for page in ("my-work", "updates"):
            self.assertEqual(scope[page], "queue")

    def test_top_bar_has_a_scope_note_and_labelled_year(self):
        self.assertIn('id="tb-scope-note"', INDEX)
        self.assertIn('id="fy-select" aria-label="Financial year"', INDEX)


if __name__ == "__main__":
    unittest.main()
