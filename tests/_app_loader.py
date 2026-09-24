"""Fresh-import the whole app package so module-level settings pick up test env vars.

Reloading individual modules leaves routers bound to stale ORM classes; purging
every ``app.*`` module avoids that.
"""
from __future__ import annotations

import importlib
import sys


def fresh_app():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    main = importlib.import_module("app.main")
    return (
        main,
        importlib.import_module("app.database"),
        importlib.import_module("app.auth"),
        importlib.import_module("app.core.config"),
    )
