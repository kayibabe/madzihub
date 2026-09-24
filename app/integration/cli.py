"""
Command-line runner for scheduled pulls.

    python -m app.integration.cli sync --due          # run every source whose schedule has elapsed
    python -m app.integration.cli sync --source sap-finance
    python -m app.integration.cli sync --all
    python -m app.integration.cli bootstrap-legacy    # seed tree, metrics and legacy source from records
    python -m app.integration.cli status

Schedule ``sync --due`` every 15 minutes with cron or Windows Task Scheduler.
Pulls run here rather than inside the web server, so several web workers never
start the same pull twice and a slow SAP extract never blocks the dashboards.
Exit code is 1 if any run failed, so the scheduler can alert.
"""
from __future__ import annotations

import argparse
import json
import sys

from app.database import SessionLocal, create_tables
from app.integration import pipeline
from app.integration.models import DataSource
from app.integration.position import freshness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.integration.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="pull data from sources")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--source", help="source code")
    g.add_argument("--all", action="store_true", help="every enabled pull source")
    g.add_argument("--due", action="store_true", help="enabled sources whose schedule has elapsed")
    sub.add_parser("bootstrap-legacy", help="seed hierarchy, metrics and legacy source from records")
    sub.add_parser("status", help="source freshness as JSON")
    args = parser.parse_args(argv)

    create_tables()
    db = SessionLocal()
    try:
        if args.cmd == "bootstrap-legacy":
            print(json.dumps(pipeline.bootstrap_legacy(db)))
            return 0
        if args.cmd == "status":
            print(json.dumps(freshness(db), indent=2))
            return 0

        if args.source:
            src = db.query(DataSource).filter_by(code=args.source).first()
            if src is None:
                print(f"unknown source {args.source}", file=sys.stderr)
                return 2
            sources = [src]
        elif args.all:
            sources = db.query(DataSource).filter(DataSource.enabled.is_(True), DataSource.connector != "push").all()
        else:
            sources = pipeline.due_sources(db)

        failed = False
        for src in sources:
            try:
                run = pipeline.run_sync(db, src, triggered_by="cli")
            except pipeline.SyncBusy as exc:
                print(f"{src.code}: skipped ({exc})")
                continue
            print(f"{src.code}: {run.status} read={run.rows_read} loaded={run.values_loaded} "
                  f"rejected={run.rows_rejected}" + (f" error={run.error}" if run.error else ""))
            failed = failed or run.status == "failed"
        return 1 if failed else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
