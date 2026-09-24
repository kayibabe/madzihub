"""Business modules built on the shared governance foundation (app/platform).

Each module is a package with models.py (tables), service.py (rules), router.py (API).
``load_all`` imports them so their tables, record types, reminder producers and
"my work" sections are registered, whether the caller is the app, the CLI or a test.
"""
from __future__ import annotations

import importlib

MODULES = ("strategy",)


def load_all() -> None:
    for name in MODULES:
        importlib.import_module(f"app.modules.{name}.models")
        importlib.import_module(f"app.modules.{name}.service")
