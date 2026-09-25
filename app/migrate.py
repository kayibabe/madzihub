"""Schema migrations (Alembic) and adoption of pre-Alembic databases.

Operator commands (run from the install folder, with the same .env the app uses):

    python -m app.migrate status                   what state is the database in? (read-only)
    python -m app.migrate upgrade                  back up, then apply pending revisions
    python -m app.migrate adopt                    back up, check and stamp a pre-Alembic database
    python -m app.migrate fingerprint --write      developers: regenerate baseline_0001.json

SQLite databases are copied to <db folder>/backups/ before any change. Other
databases cannot be copied from here: take a dump first and pass --confirm-backup.

At startup the app only builds a brand-new (empty) database by itself. It never
stamps, adopts or upgrades an existing one; it stops with the command to run.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Alembic logs plugin set-up (on import) and each step at INFO; inside the app, and in this
# CLI, which prints its own summary, that is noise. The developer CLI uses alembic.ini.
logging.getLogger("alembic").setLevel(logging.WARNING)

from alembic import command  # noqa: E402
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Index, create_engine, inspect, text, types as sqltypes

from app.database import Base, _default_sql, engine
from app import model_registry as _models  # noqa: F401  (registers every table on Base)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001"
BASELINE_FILE = MIGRATIONS_DIR / f"baseline_{BASELINE_REVISION}.json"
VERSION_TABLE = "alembic_version"


# Database objects created by revisions that have no ORM model (SQLite FTS5 search
# tables and their shadow tables). Autogenerate and `alembic check` ignore them.
UNMANAGED_TABLE_PREFIXES = ("document_fts",)


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table" and name and name.startswith(UNMANAGED_TABLE_PREFIXES):
        return False
    return True


class MigrationError(RuntimeError):
    """The requested migration step is unsafe or impossible; nothing was changed unless stated."""


class SchemaNotReady(RuntimeError):
    """The database must be migrated by an operator before the app can start."""


# ── Alembic plumbing ────────────────────────────────────────────────────────

def alembic_config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _known_revisions() -> set[str]:
    return {rev.revision for rev in ScriptDirectory.from_config(alembic_config()).walk_revisions()}


@dataclass
class DbState:
    kind: str                 # fresh | current | behind | unknown | legacy
    current: str | None
    head: str
    url: str

    def describe(self) -> str:
        return {
            "fresh": "empty database; the app will build it at startup",
            "current": f"up to date at revision {self.current}",
            "behind": f"at revision {self.current}; revision {self.head} is available",
            "unknown": f"at revision {self.current}, which this version of MadziHub does not know "
                       "(the database is newer than the code, or was migrated by another branch)",
            "legacy": "created before migrations were introduced; it must be adopted",
        }[self.kind]


def database_state(eng=engine) -> DbState:
    head = head_revision()
    url = eng.url.render_as_string(hide_password=True)
    with eng.connect() as conn:
        tables = [t for t in inspect(conn).get_table_names() if not t.startswith("sqlite_")]
        current = MigrationContext.configure(conn).get_current_revision() if VERSION_TABLE in tables else None
    if current is None:
        app_tables = [t for t in tables if t != VERSION_TABLE]
        return DbState("legacy" if app_tables else "fresh", None, head, url)
    if current == head:
        return DbState("current", current, head, url)
    if current in _known_revisions():
        return DbState("behind", current, head, url)
    return DbState("unknown", current, head, url)


def enable_wal(eng=engine) -> None:
    """Use WAL journaling for file-based SQLite, so readers do not block the writer.

    The mode is stored in the database file, so this runs only once a schema has
    been accepted (at startup, or after a successful adopt/upgrade).
    """
    if _sqlite_path(eng) is None:
        return
    with eng.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))


def ensure_schema() -> None:
    """Startup check: build an empty database, otherwise require it to be at head."""
    state = database_state()
    if state.kind == "fresh":
        command.upgrade(alembic_config(), "head")
        enable_wal()
        return
    if state.kind == "current":
        enable_wal()
        return
    action = {
        "behind": "Stop the service and run:  python -m app.migrate upgrade  (it backs the database up first)",
        "legacy": "Stop the service and run:  python -m app.migrate adopt  (it backs the database up first)",
        "unknown": "Run the MadziHub version that created it, or restore a backup made for this version.",
    }[state.kind]
    raise SchemaNotReady(f"Database {state.url} is {state.describe()}. {action}")


# ── Backups ─────────────────────────────────────────────────────────────────

def _sqlite_path(eng=engine) -> Path | None:
    if eng.url.get_backend_name() != "sqlite":
        return None
    database = eng.url.database
    if not database or database == ":memory:":
        return None
    return Path(database).resolve()


def backup_database(label: str, eng=engine, confirm_backup: bool = False) -> Path | None:
    """Copy a SQLite database (consistently, even in WAL mode) before changing it.

    Returns the backup path, or None when the operator confirmed an external backup.
    """
    source = _sqlite_path(eng)
    if source is None:
        if confirm_backup:
            return None
        raise MigrationError(
            "This database cannot be copied automatically. Take a backup (e.g. pg_dump), "
            "then rerun with --confirm-backup.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_dir = source.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}-{stamp}-before-{label}{source.suffix}"
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return target


# ── Schema fingerprints (dialect-neutral) ───────────────────────────────────

def _type_key(t) -> str:
    """Normalise a reflected or declared column type so SQLite and PostgreSQL compare equal."""
    if isinstance(t, sqltypes.Boolean):
        return "boolean"
    if isinstance(t, sqltypes.JSON):
        return "json"
    if isinstance(t, sqltypes.DateTime):
        return "datetime"
    if isinstance(t, sqltypes.Date):
        return "date"
    if isinstance(t, sqltypes.Integer):
        return "integer"
    if isinstance(t, sqltypes.Float):          # before Numeric: Float subclasses Numeric
        return "float"
    if isinstance(t, sqltypes.Numeric):
        return f"numeric({t.precision},{t.scale})"
    if isinstance(t, sqltypes.Text):           # before String: Text subclasses String
        return "text"
    if isinstance(t, sqltypes.String):
        return f"string({t.length})" if t.length else "text"
    return type(t).__name__.lower()


def schema_fingerprint(conn) -> dict:
    insp = inspect(conn)
    tables = {}
    for name in sorted(insp.get_table_names()):
        if name.startswith("sqlite_") or name == VERSION_TABLE:
            continue
        columns = {c["name"]: {"type": _type_key(c["type"]), "nullable": bool(c["nullable"])}
                   for c in insp.get_columns(name)}
        indexes = {ix["name"]: {"columns": list(ix["column_names"]), "unique": bool(ix["unique"])}
                   for ix in insp.get_indexes(name)
                   if ix.get("name") and not ix.get("duplicates_constraint")}
        uniques = sorted(sorted(u["column_names"]) for u in insp.get_unique_constraints(name))
        fks = sorted([list(fk["constrained_columns"]), fk["referred_table"], list(fk["referred_columns"])]
                     for fk in insp.get_foreign_keys(name))
        tables[name] = {"columns": columns, "indexes": indexes, "uniques": uniques, "foreign_keys": fks}
    return {"revision": BASELINE_REVISION, "tables": tables}


def load_baseline() -> dict:
    return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


@dataclass
class SchemaDiff:
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: list[tuple[str, str]] = field(default_factory=list)
    missing_indexes: list[tuple[str, str]] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)   # cannot be fixed safely in place
    warnings: list[str] = field(default_factory=list)

    @property
    def fixable(self) -> bool:
        return not self.blocking

    @property
    def clean(self) -> bool:
        return not (self.missing_tables or self.missing_columns or self.missing_indexes or self.blocking)


def _sqlite_equivalent(got: str, want: str) -> bool:
    """FLOAT vs NUMERIC(p,s): older installs declared money columns as FLOAT. SQLite stores
    both as floating point (REAL/NUMERIC affinity), so the data and behaviour are identical."""
    return {got.split("(")[0], want.split("(")[0]} == {"float", "numeric"}


def compare_to_baseline(live: dict, baseline: dict, dialect: str = "sqlite") -> SchemaDiff:
    diff = SchemaDiff()
    float_money: dict[str, list[str]] = {}
    live_t, base_t = live["tables"], baseline["tables"]
    for extra in sorted(set(live_t) - set(base_t)):
        diff.warnings.append(f"extra table {extra} (left untouched)")
    for name, want in base_t.items():
        have = live_t.get(name)
        if have is None:
            diff.missing_tables.append(name)
            continue
        for col, spec in want["columns"].items():
            got = have["columns"].get(col)
            if got is None:
                diff.missing_columns.append((name, col))
            elif got["type"] != spec["type"]:
                if dialect == "sqlite" and _sqlite_equivalent(got["type"], spec["type"]):
                    float_money.setdefault(name, []).append(col)
                else:
                    diff.blocking.append(f"{name}.{col} is {got['type']}, expected {spec['type']}")
            elif got["nullable"] != spec["nullable"]:
                expected = "nullable" if spec["nullable"] else "NOT NULL"
                diff.blocking.append(f"{name}.{col} nullability differs (expected {expected})")
        for col in sorted(set(have["columns"]) - set(want["columns"])):
            diff.warnings.append(f"extra column {name}.{col} (left untouched)")
        for ix, spec in want["indexes"].items():
            got = have["indexes"].get(ix)
            if got is None:
                diff.missing_indexes.append((name, ix))
            elif got != spec:
                diff.blocking.append(f"index {ix} on {name} differs: {got} vs {spec}")
        for cols in want["uniques"]:
            if cols not in have["uniques"]:
                diff.blocking.append(f"{name} lacks the unique constraint on {', '.join(cols)}")
        for fk in want["foreign_keys"]:
            if fk not in have["foreign_keys"]:
                diff.warnings.append(f"{name} lacks the foreign key {fk[0]} -> {fk[1]}{fk[2]} "
                                     "(not enforced for this table)")
    for name, cols in float_money.items():
        diff.warnings.append(f"{name}: {len(cols)} column(s) declared FLOAT where the baseline says NUMERIC "
                             f"(e.g. {cols[0]}); SQLite stores both the same way, left as is")
    return diff


# ── Adoption of pre-Alembic databases ──────────────────────────────────────

def _baseline_column_matches(table: str, column: str, baseline: dict) -> bool:
    model_col = Base.metadata.tables[table].columns.get(column)
    return model_col is not None and _type_key(model_col.type) == baseline["tables"][table]["columns"][column]["type"]


def _baseline_table(name: str, baseline: dict):
    """The table exactly as revision 0001 defines it: only baseline columns, keys and indexes.

    Built from the current model's column types, restricted to the baseline fingerprint,
    so columns added by later revisions are left for those revisions to add.
    """
    from sqlalchemy import Column, ForeignKeyConstraint, MetaData, Table, UniqueConstraint

    model = Base.metadata.tables.get(name)
    if model is None:
        raise MigrationError(f"Table {name} is missing and no longer defined; adopt it with an older release.")
    spec = baseline["tables"][name]
    md = MetaData()
    columns = []
    for col, want in spec["columns"].items():
        c = model.columns.get(col)
        if c is None or _type_key(c.type) != want["type"]:
            raise MigrationError(f"Table {name} is missing and its column {col} has changed since the baseline; "
                                 "adopt with the release that introduced migrations.")
        columns.append(Column(c.name, c.type, primary_key=c.primary_key, nullable=want["nullable"],
                              autoincrement=c.autoincrement))
    named_uniques = {tuple(sorted(con.columns.keys())): con.name for con in model.constraints
                     if isinstance(con, UniqueConstraint)}
    extra = []
    for cols in spec["uniques"]:
        extra.append(UniqueConstraint(*cols, name=named_uniques.get(tuple(sorted(cols)))))
    for local, ref_table, ref_cols in spec["foreign_keys"]:
        if ref_table != name and ref_table not in md.tables:
            Table(ref_table, md, *[Column(rc, sqltypes.Integer) for rc in ref_cols])   # name-only stub for DDL
        extra.append(ForeignKeyConstraint(local, [f"{ref_table}.{rc}" for rc in ref_cols]))
    table = Table(name, md, *columns, *extra)
    for ix_name, ix in spec["indexes"].items():
        Index(ix_name, *[table.c[c] for c in ix["columns"]], unique=ix["unique"])
    return table


def _top_up(conn, diff: SchemaDiff, baseline: dict) -> list[str]:
    """Create the baseline tables, columns and indexes a legacy database is missing.

    Definitions come from the current models, but only where they still match the
    baseline fingerprint; the final verification rejects anything that drifted.
    """
    done = []
    for name in diff.missing_tables:
        _baseline_table(name, baseline).create(conn)
        done.append(f"created table {name}")
    for name, col in diff.missing_columns:
        if not _baseline_column_matches(name, col, baseline):
            raise MigrationError(f"Column {name}.{col} is missing and its definition has changed since the "
                                 "baseline; adopt with the release that introduced migrations.")
        column = Base.metadata.tables[name].columns[col]
        col_type = column.type.compile(dialect=conn.dialect)
        nullable = "" if column.nullable else " NOT NULL"
        conn.execute(text(f"ALTER TABLE {name} ADD COLUMN {col} {col_type}{nullable}{_default_sql(column)}"))
        done.append(f"added column {name}.{col}")
    for name, ix_name in diff.missing_indexes:
        spec = baseline["tables"][name]["indexes"][ix_name]
        table = Base.metadata.tables[name]
        Index(ix_name, *[table.c[c] for c in spec["columns"]], unique=spec["unique"]).create(conn)
        done.append(f"created index {ix_name}")
    return done


@dataclass
class AdoptResult:
    backup: Path | None
    actions: list[str]
    warnings: list[str]
    revision: str


def check_legacy(eng=engine) -> SchemaDiff:
    """Read-only comparison of a pre-Alembic database with the baseline."""
    with eng.connect() as conn:
        diff = compare_to_baseline(schema_fingerprint(conn), load_baseline(), conn.dialect.name)
        if conn.dialect.name == "sqlite":
            bad = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            if bad:
                diff.warnings.append(f"{len(bad)} existing row(s) break a foreign key; "
                                     "new writes will be checked, existing rows are left as they are")
    return diff


def adopt(eng=engine, confirm_backup: bool = False) -> AdoptResult:
    """Back up, top up, verify and stamp a pre-Alembic database, then upgrade it to head."""
    state = database_state(eng)
    if state.kind != "legacy":
        raise MigrationError(f"Nothing to adopt: the database is {state.describe()}.")
    baseline = load_baseline()
    diff = check_legacy(eng)
    if not diff.fixable:
        raise MigrationError("The database does not match the baseline schema and was not changed:\n  - "
                             + "\n  - ".join(diff.blocking))
    backup = backup_database("adopt", eng, confirm_backup)
    with eng.begin() as conn:
        actions = _top_up(conn, diff, baseline)
    with eng.connect() as conn:
        after = compare_to_baseline(schema_fingerprint(conn), baseline, conn.dialect.name)
    if not after.clean:
        problems = after.blocking + [f"missing {t}" for t in after.missing_tables] + \
                   [f"missing {t}.{c}" for t, c in after.missing_columns] + \
                   [f"missing index {i}" for _, i in after.missing_indexes]
        raise MigrationError("Verification failed after top-up; the database was NOT stamped. "
                             f"Restore {backup or 'your backup'} and report:\n  - " + "\n  - ".join(problems))
    with eng.begin() as conn:
        command.stamp(alembic_config(conn), BASELINE_REVISION)
    _upgrade_head(eng)
    return AdoptResult(backup, actions, diff.warnings, head_revision())


def _upgrade_head(eng) -> None:
    if eng is engine:
        command.upgrade(alembic_config(), "head")   # env.py manages SQLite FK pragmas
    else:
        with eng.begin() as conn:
            command.upgrade(alembic_config(conn), "head")
    enable_wal(eng)


def upgrade(eng=engine, confirm_backup: bool = False) -> tuple[Path | None, str]:
    state = database_state(eng)
    if state.kind == "legacy":
        raise MigrationError("This database predates migrations; run `python -m app.migrate adopt` instead.")
    if state.kind == "unknown":
        raise MigrationError(f"The database is {state.describe()}. Not changed.")
    if state.kind == "current":
        return None, state.current
    backup = backup_database("upgrade", eng, confirm_backup) if state.kind == "behind" else None
    _upgrade_head(eng)
    return backup, head_revision()


def baseline_revision_fingerprint() -> dict:
    """Fingerprint revision 0001 as built on a scratch SQLite database."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        scratch = create_engine(f"sqlite:///{Path(d) / 'baseline.db'}")
        try:
            with scratch.begin() as conn:
                command.upgrade(alembic_config(conn), BASELINE_REVISION)
            with scratch.connect() as conn:
                return schema_fingerprint(conn)
        finally:
            scratch.dispose()


def write_baseline_fingerprint() -> Path:
    """Developers: regenerate baseline_0001.json (only ever needed if revision 0001 is rebuilt)."""
    fp = baseline_revision_fingerprint()
    BASELINE_FILE.write_text(json.dumps(fp, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return BASELINE_FILE


# ── CLI ─────────────────────────────────────────────────────────────────────

def _print_diff(diff: SchemaDiff) -> None:
    for t in diff.missing_tables:
        print(f"  + will create table {t}")
    for t, c in diff.missing_columns:
        print(f"  + will add column {t}.{c}")
    for _, i in diff.missing_indexes:
        print(f"  + will create index {i}")
    for b in diff.blocking:
        print(f"  ! blocking: {b}")
    for w in diff.warnings:
        print(f"  ~ note: {w}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.migrate", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show the database state (read-only)")
    for name, help_text in (("upgrade", "back up, then apply pending revisions"),
                            ("adopt", "back up, check and stamp a pre-Alembic database")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--confirm-backup", action="store_true",
                       help="for non-SQLite databases: confirm you have taken a backup")
    fp = sub.add_parser("fingerprint", help="developers: regenerate the baseline fingerprint")
    fp.add_argument("--write", action="store_true", required=True)
    args = parser.parse_args(argv)

    try:
        if args.cmd == "status":
            state = database_state()
            print(f"Database: {state.url}\nState:    {state.describe()}\nHead:     {state.head}")
            if state.kind == "legacy":
                diff = check_legacy()
                print("Adoption check:" if not diff.clean or diff.warnings else "Adoption check: matches the baseline")
                _print_diff(diff)
                print("Adoptable." if diff.fixable else "NOT adoptable until the blocking items are resolved.")
            next_step = {
                "behind": "Next step: python -m app.migrate upgrade",
                "legacy": "Next step: python -m app.migrate adopt",
                "unknown": "Next step: run the MadziHub version that created this database, or restore a backup.",
            }.get(state.kind)
            if next_step:
                print(next_step)
            return 0 if state.kind in ("current", "fresh") else 2
        if args.cmd == "upgrade":
            backup, rev = upgrade(confirm_backup=args.confirm_backup)
            if backup:
                print(f"Backup: {backup}")
            print(f"Database is at revision {rev}.")
            return 0
        if args.cmd == "adopt":
            result = adopt(confirm_backup=args.confirm_backup)
            print(f"Backup: {result.backup or 'confirmed by operator'}")
            for a in result.actions:
                print(f"  + {a}")
            for w in result.warnings:
                print(f"  ~ note: {w}")
            print(f"Adopted. Database is at revision {result.revision}.")
            return 0
        if args.cmd == "fingerprint":
            print(f"Wrote {write_baseline_fingerprint()}")
            return 0
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
