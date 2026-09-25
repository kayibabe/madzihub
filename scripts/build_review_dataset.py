"""
scripts/build_review_dataset.py
===============================
Build an isolated demo database holding a populated fiscal year, for review journeys
(docs/GUI_UX_REVIEW_2026-09-25.md, "Before Slice 2: close coverage gaps").

It creates, in a new folder of its own:
  review.db       demo tenant schema, demo people and grants (app.demo_seed), fiscal years
                  and budget (tenants/demo/budget.yaml), the FY2025/26 returns from
                  tests/fixtures/populated_year.py (also published to the measure catalogue
                  through the legacy-returns bridge), and three integration sources whose
                  freshness is current, overdue (stale) and failed
  files/, secret  the file store and signing secret this database uses
  manifest.json   what the dataset contains and which case each scheme represents
  accounts.txt    demo sign-in names and one-time random passwords (fictional people)

Usage
-----
    python scripts/build_review_dataset.py --out <new folder>
    python scripts/build_review_dataset.py --out <folder> --replace   # rebuild a folder this script made

It never opens the working database: the folder must be new (or one this script built,
with --replace) and must not be inside the project's data/ folder. Source freshness is
relative to the build time: rebuild before a journey so "current" is still current.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = ".madzi-review-dataset"
DB_NAME = "review.db"

# code, name, schedule (minutes), last success (hours ago), last run status, error
SOURCES = [
    ("billing-export", "Billing system export (synthetic)", 7 * 24 * 60, 6, "success", None),
    ("scada-daily", "SCADA production totals (synthetic)", 24 * 60, 9 * 24, "success", None),
    ("lims-results", "Laboratory results feed (synthetic)", 24 * 60, 3 * 24, "failed",
     "Connection refused by the laboratory server (synthetic failure)"),
]


def _utcnow() -> datetime:
    """Naive UTC, as the app's DateTime columns store it."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _remove_tree(path: Path) -> None:
    """Delete a folder this script built; the file store keeps evidence files read-only."""
    def clear_and_retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear_and_retry)
    else:
        shutil.rmtree(path, onerror=clear_and_retry)


def _prepare(out: Path, replace: bool) -> None:
    data_dir = (ROOT / "data").resolve()
    if out == data_dir or data_dir in out.parents:
        raise SystemExit(f"Refusing to build inside {data_dir}: the working database lives there.")
    if out.exists() and any(out.iterdir()):
        if not replace:
            raise SystemExit(f"{out} is not empty. Use a new folder, or --replace for one this script built.")
        if not (out / MARKER).exists():
            raise SystemExit(f"{out} was not built by this script ({MARKER} missing); not replacing it.")
        _remove_tree(out)
    (out / "files").mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("Built by scripts/build_review_dataset.py. Safe to delete.\n", encoding="utf-8")


def _configure(out: Path) -> None:
    """Point the app at the new folder before any app module is imported."""
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{(out / DB_NAME).as_posix()}",
        "MADZI_FILE_STORE": str(out / "files"),
        "MADZI_SECRET_FILE": str(out / "secret"),
        "MADZI_TENANT": "demo",
        "MADZI_ENV": "development",
        "MADZI_LOG_LEVEL": "WARNING",
    })
    sys.path.insert(0, str(ROOT))


def _sources(db) -> None:
    from app.integration.models import DataSource, SyncRun

    now = _utcnow()
    for code, name, minutes, hours_ago, status, error in SOURCES:
        success = now - timedelta(hours=hours_ago)
        last_run = now - timedelta(hours=5) if status == "failed" else success
        src = DataSource(code=code, name=name, system_type="other", connector="csv", config={}, mapping={},
                         enabled=True, owner="planner", schedule_minutes=minutes,
                         last_run_at=last_run, last_success_at=success)
        db.add(src)
        db.flush()
        db.add(SyncRun(source_id=src.id, started_at=success, finished_at=success, status="success",
                       triggered_by="review-dataset", rows_read=120, values_loaded=120))
        if status == "failed":
            db.add(SyncRun(source_id=src.id, started_at=last_run, finished_at=last_run, status="failed",
                           triggered_by="review-dataset", error=error))


def build(out: Path) -> dict:
    from app import database, demo_seed
    from app.auth import ensure_default_admin
    from app.core.tenant import tenant
    from app.integration import pipeline
    from app.integration.models import DataSource
    from app.platform.bootstrap import at_startup
    from scripts.seed_fiscal_years import seed as seed_fiscal_years
    from tests.fixtures import populated_year

    if tenant.key != "demo":
        raise SystemExit(f"Refusing to build: tenant is '{tenant.key}', not 'demo'.")
    assert Path(database.engine.url.database).resolve() == (out / DB_NAME).resolve(), database.engine.url

    database.create_tables()
    with database.SessionLocal() as db:
        ensure_default_admin(db)
        at_startup(db)
        passwords = demo_seed.run(db)
    seed_fiscal_years()
    with database.SessionLocal() as db:
        populated_year.load(db, database.Record)
        _sources(db)
        db.commit()
        count = db.query(database.Record).count()
        # Publish the returns to the measure catalogue (Strategic Position) the way an
        # administrator does: Data Sources -> bootstrap from existing returns, then sync.
        pipeline.bootstrap_legacy(db)
        legacy = db.query(DataSource).filter_by(code="legacy-returns").one()
        run = pipeline.run_sync(db, legacy, triggered_by="review-dataset")
        if run.status != "success":
            raise SystemExit(f"Legacy returns sync ended '{run.status}': {run.error}")

    manifest = {**populated_year.manifest(), "built_at": _utcnow().isoformat(timespec="seconds") + "Z",
                "database": str(out / DB_NAME), "records_loaded": count,
                "sources": [{"code": c, "expected_freshness": "failed" if s == "failed" else
                             "overdue" if h * 60 > m * 2 else "current"} for c, _, m, h, s, _ in SOURCES],
                "accounts": [{"username": u, "grants": g, "duties": list(d)} for u, _, _, g, d in demo_seed.DEMO_USERS]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "accounts.txt").write_text(
        "Fictional demo accounts for this review database only (one-time random passwords).\n"
        + "".join(f"{u:<12} {pw}\n" for u, pw in passwords.items()), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated review database with a populated fiscal year")
    parser.add_argument("--out", required=True, help="new folder to build in (never the project's data/ folder)")
    parser.add_argument("--replace", action="store_true", help="rebuild a folder this script built before")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    _prepare(out, args.replace)
    _configure(out)
    manifest = build(out)
    print(f"[OK] {manifest['records_loaded']} returns loaded into {manifest['database']}")
    print(f"     cases: {json.dumps(manifest['cases'])}")
    print(f"     manifest: {out / 'manifest.json'}   accounts: {out / 'accounts.txt'}")
    print("     Serve it with DATABASE_URL, MADZI_FILE_STORE and MADZI_SECRET_FILE pointing at this folder,")
    print("     MADZI_TENANT=demo, MADZI_ENV=development and MADZI_DEV_PREVIEW=true (see .claude/launch.json).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
