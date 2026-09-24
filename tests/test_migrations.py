"""Alembic migrations: fresh builds, the startup gate, and adoption of pre-Alembic databases."""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sqlite3
import unittest
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from tests._app_loader import TemporaryDirectory, fresh_app
from tests.fixtures.synthetic_dataset import build_records


def _boot(tmpdir: str):
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmpdir) / 'm.db'}"
    os.environ["MADZI_ENV"] = "development"
    os.environ["MADZI_SECRET_KEY"] = "k"
    os.environ["MADZI_TENANT"] = "demo"
    main, database, _auth, _config = fresh_app()
    import app.migrate as migrate
    return main, database, migrate


def _model_drift(database) -> list:
    """What `alembic check` reports: differences between the models and the migrated schema."""
    with database.engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), database.Base.metadata)


def _make_legacy(database, *statements: str) -> None:
    """A database as pre-Alembic MadziHub left it: the baseline tables, then optional older-shape edits.

    Only tables in the baseline fingerprint are created: a pre-Alembic install cannot
    contain tables that later revisions introduced.
    """
    import app.migrate as migrate
    baseline = migrate.load_baseline()
    with database.engine.begin() as conn:
        for name in baseline["tables"]:
            migrate._baseline_table(name, baseline).create(conn)
    with database.engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))


# activity_log.username as INTEGER: a type difference adopt must refuse rather than "fix".
MISMATCHED_ACTIVITY_LOG = (
    "DROP TABLE activity_log",
    "CREATE TABLE activity_log (id INTEGER PRIMARY KEY, username INTEGER NOT NULL, "
    "action VARCHAR(60) NOT NULL, detail VARCHAR(500), ip_address VARCHAR(60), logged_at DATETIME)",
)


def _fingerprint(migrate, database) -> dict:
    with database.engine.connect() as conn:
        return migrate.schema_fingerprint(conn)


def _records_summary(database) -> tuple:
    """Row count and money/volume totals: must be identical before and after adoption."""
    with database.engine.connect() as conn:
        return tuple(conn.execute(text(
            "SELECT COUNT(*), ROUND(SUM(vol_produced), 3), ROUND(SUM(total_sales), 2), "
            "ROUND(SUM(cash_collected), 2) FROM records")).one())


def _tables(database) -> set[str]:
    return set(inspect(database.engine).get_table_names())


class FreshDatabaseTests(unittest.TestCase):
    def test_fresh_database_is_built_at_head_and_matches_models(self):
        with TemporaryDirectory() as d:
            main, database, migrate = _boot(d)
            with TestClient(main.app):
                pass
            state = migrate.database_state()
            self.assertEqual(state.kind, "current")
            self.assertEqual(state.current, migrate.head_revision())
            self.assertEqual(_model_drift(database), [])

    def test_committed_baseline_fingerprint_matches_revision_0001(self):
        with TemporaryDirectory() as d:
            _main, _database, migrate = _boot(d)
            self.assertEqual(migrate.baseline_revision_fingerprint(), migrate.load_baseline())

    def test_sqlite_enforces_foreign_keys_and_uses_wal(self):
        with TemporaryDirectory() as d:
            main, database, _migrate = _boot(d)
            with TestClient(main.app):
                pass
            with database.engine.connect() as conn:
                self.assertEqual(conn.execute(text("PRAGMA foreign_keys")).scalar(), 1)
                self.assertEqual(conn.execute(text("PRAGMA journal_mode")).scalar(), "wal")

    def test_upgrade_of_current_database_changes_nothing(self):
        with TemporaryDirectory() as d:
            main, _database, migrate = _boot(d)
            with TestClient(main.app):
                pass
            self.assertEqual(migrate.upgrade(), (None, migrate.head_revision()))
            self.assertFalse((Path(d) / "backups").exists())

    def test_baseline_cannot_be_downgraded(self):
        with TemporaryDirectory() as d:
            main, database, migrate = _boot(d)
            with TestClient(main.app):
                pass
            with self.assertRaises(RuntimeError):
                command.downgrade(migrate.alembic_config(), "base")
            self.assertIn("records", _tables(database))
            self.assertEqual(migrate.database_state().kind, "current")


class StartupGateTests(unittest.TestCase):
    def test_legacy_database_blocks_startup_without_being_changed(self):
        with TemporaryDirectory() as d:
            main, database, migrate = _boot(d)
            _make_legacy(database)
            before = _fingerprint(migrate, database)
            with self.assertRaises(migrate.SchemaNotReady) as ctx:
                with TestClient(main.app):
                    pass
            self.assertIn("python -m app.migrate adopt", str(ctx.exception))
            self.assertNotIn("alembic_version", _tables(database))
            self.assertEqual(_fingerprint(migrate, database), before)
            database.engine.dispose()

    def test_status_and_refused_adopt_leave_the_file_byte_identical(self):
        with TemporaryDirectory() as d:
            _main, database, migrate = _boot(d)
            _make_legacy(database, *MISMATCHED_ACTIVITY_LOG)
            database.engine.dispose()
            path = Path(d) / "m.db"
            con = sqlite3.connect(path)          # pre-Alembic installs use the default rollback journal
            con.execute("PRAGMA journal_mode=DELETE")
            con.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                self.assertEqual(migrate.main(["status"]), 2)
                self.assertEqual(migrate.main(["adopt"]), 1)
            database.engine.dispose()
            self.assertIn("NOT adoptable", out.getvalue())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertFalse((Path(d) / "m.db-wal").exists())

    def test_unknown_revision_blocks_startup_and_upgrade(self):
        with TemporaryDirectory() as d:
            main, database, migrate = _boot(d)
            with TestClient(main.app):
                pass
            with database.engine.begin() as conn:
                conn.execute(text("UPDATE alembic_version SET version_num = 'zz99'"))
            self.assertEqual(migrate.database_state().kind, "unknown")
            with self.assertRaises(migrate.SchemaNotReady) as ctx:
                migrate.ensure_schema()
            self.assertIn("does not know", str(ctx.exception))
            with self.assertRaises(migrate.MigrationError):
                migrate.upgrade()


class AdoptTests(unittest.TestCase):
    OLDER_SHAPE = (
        "ALTER TABLE users DROP COLUMN must_change_password",   # added after the first release
        "DROP TABLE metric_values",                             # integration tables came later
        "DROP INDEX ix_record_year_month",                      # added by a later data-integrity fix
        "INSERT INTO users (username, password_hash, role, is_active) VALUES ('ops', 'h', 'admin', 1)",
    )

    def test_adopt_backs_up_tops_up_verifies_and_stamps(self):
        with TemporaryDirectory() as d:
            main, database, migrate = _boot(d)
            _make_legacy(database, *self.OLDER_SHAPE)
            db = database.SessionLocal()
            db.add_all(build_records(database.Record))
            db.commit()
            db.close()
            before = _records_summary(database)
            self.assertGreater(before[0], 0)
            self.assertEqual(migrate.database_state().kind, "legacy")
            diff = migrate.check_legacy()
            self.assertTrue(diff.fixable)
            self.assertEqual(diff.missing_tables, ["metric_values"])

            result = migrate.adopt()

            self.assertIn("created table metric_values", result.actions)
            self.assertIn("added column users.must_change_password", result.actions)
            self.assertIn("created index ix_record_year_month", result.actions)
            self.assertEqual(migrate.database_state().kind, "current")
            self.assertEqual(_model_drift(database), [])
            with database.engine.connect() as conn:
                row = conn.execute(text("SELECT username, must_change_password FROM users")).one()
            self.assertEqual(tuple(row), ("ops", 0))   # data kept; new NOT NULL column defaulted
            self.assertEqual(_records_summary(database), before)
            with database.engine.connect() as conn:
                self.assertEqual(conn.execute(text("PRAGMA journal_mode")).scalar(), "wal")

            # The backup is the database exactly as it was before adoption.
            self.assertTrue(result.backup.exists())
            con = sqlite3.connect(result.backup)
            try:
                names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                users = con.execute("SELECT username FROM users").fetchall()
            finally:
                con.close()
            self.assertNotIn("alembic_version", names)
            self.assertNotIn("metric_values", names)
            self.assertEqual(users, [("ops",)])

            with TestClient(main.app) as c:              # startup now passes the gate
                self.assertEqual(c.get("/health").status_code, 200)

    def test_missing_baseline_table_is_created_as_baseline_then_upgraded(self):
        """A table later revisions extend (metric_targets gains plan_id in 0003) must be created
        in its baseline shape, or the later revision's ALTER would fail on adoption."""
        with TemporaryDirectory() as d:
            _main, database, migrate = _boot(d)
            _make_legacy(database, "DROP TABLE metric_targets")
            result = migrate.adopt()
            self.assertIn("created table metric_targets", result.actions)
            self.assertEqual(migrate.database_state().kind, "current")
            self.assertEqual(_model_drift(database), [])
            cols = {c["name"] for c in inspect(database.engine).get_columns("metric_targets")}
            self.assertIn("plan_id", cols)

    def test_mismatched_database_is_refused_and_left_untouched(self):
        with TemporaryDirectory() as d:
            _main, database, migrate = _boot(d)
            _make_legacy(database, *MISMATCHED_ACTIVITY_LOG)
            before = _fingerprint(migrate, database)
            with self.assertRaises(migrate.MigrationError) as ctx:
                migrate.adopt()
            self.assertIn("activity_log.username is integer, expected string(60)", str(ctx.exception))
            self.assertEqual(_fingerprint(migrate, database), before)
            self.assertEqual(migrate.database_state().kind, "legacy")
            self.assertFalse((Path(d) / "backups").exists())
            database.engine.dispose()

    def test_sqlite_float_money_columns_are_accepted_with_a_note(self):
        with TemporaryDirectory() as d:
            _main, database, migrate = _boot(d)
            _make_legacy(database,
                         "DROP TABLE budget_lines",
                         "CREATE TABLE budget_lines (id INTEGER NOT NULL PRIMARY KEY, year INTEGER NOT NULL "
                         "REFERENCES fiscal_years (year), category VARCHAR(60) NOT NULL, value FLOAT NOT NULL, "
                         "unit VARCHAR(20), notes VARCHAR(300), created_at DATETIME, updated_at DATETIME, "
                         "CONSTRAINT uq_budget_year_category UNIQUE (year, category))",
                         "CREATE INDEX ix_budget_lines_year ON budget_lines (year)")
            diff = migrate.check_legacy()
            self.assertTrue(diff.fixable, diff.blocking)
            self.assertTrue(any("budget_lines: 1 column(s) declared FLOAT" in w for w in diff.warnings))
            migrate.adopt()
            self.assertEqual(migrate.database_state().kind, "current")

    def test_adopt_refuses_a_database_that_is_not_legacy(self):
        with TemporaryDirectory() as d:
            main, _database, migrate = _boot(d)
            with TestClient(main.app):
                pass
            with self.assertRaises(migrate.MigrationError):
                migrate.adopt()

    def test_non_file_database_needs_confirmed_external_backup(self):
        with TemporaryDirectory() as d:
            _main, _database, migrate = _boot(d)
            memory = create_engine("sqlite://")
            with self.assertRaises(migrate.MigrationError) as ctx:
                migrate.backup_database("adopt", memory)
            self.assertIn("--confirm-backup", str(ctx.exception))
            self.assertIsNone(migrate.backup_database("adopt", memory, confirm_backup=True))


class CliAndTypeTests(unittest.TestCase):
    def _run(self, migrate, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = migrate.main(list(argv))
        return code, out.getvalue()

    def test_status_exit_codes_and_messages(self):
        with TemporaryDirectory() as d:
            main, database, migrate = _boot(d)
            _make_legacy(database, "DROP TABLE metric_values")
            code, out = self._run(migrate, "status")
            self.assertEqual(code, 2)
            self.assertIn("must be adopted", out)
            self.assertIn("will create table metric_values", out)
            self.assertIn("Adoptable.", out)
            code, out = self._run(migrate, "adopt")
            self.assertEqual(code, 0, out)
            self.assertIn("Backup:", out)
            code, out = self._run(migrate, "status")
            self.assertEqual(code, 0)
            self.assertIn("up to date", out)
            code, out = self._run(migrate, "adopt")
            self.assertEqual(code, 1)
            self.assertIn("Nothing to adopt", out)

    def test_type_keys_match_across_sqlite_and_postgresql(self):
        with TemporaryDirectory() as d:
            _main, _database, migrate = _boot(d)
        from sqlalchemy import JSON, Boolean, DateTime, Float, Numeric, String, Text
        from sqlalchemy.dialects import postgresql as pg
        pairs = [
            (String(60), pg.VARCHAR(60)), (Text(), pg.TEXT()), (Float(), pg.DOUBLE_PRECISION()),
            (Numeric(15, 2), pg.NUMERIC(15, 2)), (Boolean(), pg.BOOLEAN()),
            (DateTime(), pg.TIMESTAMP()), (JSON(), pg.JSONB()),
        ]
        for declared, reflected in pairs:
            self.assertEqual(migrate._type_key(declared), migrate._type_key(reflected), (declared, reflected))
        self.assertNotEqual(migrate._type_key(Float()), migrate._type_key(Numeric(15, 2)))


if __name__ == "__main__":
    unittest.main()
