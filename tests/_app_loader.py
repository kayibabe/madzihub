"""Fresh-import the whole app package so module-level settings pick up test env vars.

Reloading individual modules leaves routers bound to stale ORM classes; purging
every ``app.*`` module avoids that.
"""
from __future__ import annotations

import gc
import importlib
import sys
import tempfile


def release_databases():
    """Close every SQLAlchemy connection pool the tests have opened.

    Each ``fresh_app()`` builds a new engine whose pool keeps its SQLite file
    open. Windows cannot delete an open file, so do this before removing a
    temp directory holding one. Engines from earlier fresh imports are no
    longer reachable through ``sys.modules``, hence the gc sweep.
    """
    from sqlalchemy.engine import Engine

    gc.collect()
    for obj in gc.get_objects():
        if isinstance(obj, Engine):
            obj.dispose()
    gc.collect()  # finalise any sessions/raw sqlite3 connections left behind


class TemporaryDirectory(tempfile.TemporaryDirectory):
    """``tempfile.TemporaryDirectory`` that releases app databases before cleanup."""

    def cleanup(self):
        release_databases()
        super().cleanup()


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
