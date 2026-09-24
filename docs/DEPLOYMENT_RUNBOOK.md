# Deployment Runbook

## Purpose
This document defines the minimum safe deployment process for MadziHub.

## Pre-deployment checklist
- Confirm all required environment variables are present.
- Confirm `SECRET_KEY` is strong and not using a fallback.
- Confirm allowed CORS origins are explicitly configured.
- Confirm no live secrets, databases, or uploads are inside the release bundle.
- Confirm core tests pass.
- Confirm the intended `DATABASE_URL` is correct.

## Environment requirements
- Python 3.10+
- Installed dependencies from `requirements.txt`
- Writable `data/` and `uploads/` directories
- Network access only from approved origins and internal users where applicable

## Required configuration
Expected values include:
- `SECRET_KEY`
- `DATABASE_URL`
- `MADZI_ALLOWED_ORIGINS`
- `UPLOAD_LIMIT_MB`
- optional AI provider keys only if AI features are enabled

## Release procedure
1. Build a clean bundle using `scripts/build_release_bundle.py`.
2. Move the bundle to the target host.
3. Extract into a clean deployment directory.
4. Create environment variables or a protected `.env` file on the host.
5. Install dependencies in a fresh virtual environment.
6. Check the database: `python -m app.migrate status`. If it reports a next step, follow
   [Database migrations](#database-migrations) before starting.
7. Start the service.
8. Validate health, login, upload, and core dashboard screens.

## Post-deployment smoke tests
- login as admin
- login as viewer
- load dashboard landing page
- load one report page
- test one protected admin endpoint
- upload a valid workbook in a test environment
- confirm request logs and request IDs are visible

## Database migrations
The schema is managed by Alembic (`app/migrations/`). The app **never changes an existing
database at startup**: it builds a brand-new empty database, starts normally on one that
is up to date, and otherwise stops with the command to run. `start.bat` runs the same
read-only check before starting the server.

Run every command from the install folder with the same `.env` / environment the service
uses, so it targets the same `DATABASE_URL`.

| `status` says | Meaning | What to do |
|---|---|---|
| up to date | at the latest revision | nothing |
| empty database | new install | nothing; the app builds it at first start |
| at revision X; revision Y is available | a release added schema changes | stop the service, then `python -m app.migrate upgrade` |
| created before migrations were introduced | installed before Alembic | stop the service, then `python -m app.migrate adopt` (once per install) |
| a revision this version does not know | database is newer than the code, or from another branch | do not start; run the release that created it or restore a matching backup |

**Backups.** For SQLite, `upgrade` and `adopt` copy the database to
`data/backups/<name>-<UTC time>-before-<step>.db` before changing anything (the copy is
consistent even with WAL). For PostgreSQL take a `pg_dump` first and add `--confirm-backup`.

**Adopting a pre-Alembic database** (`adopt`):
1. Compares the live schema with the recorded baseline (`app/migrations/baseline_0001.json`):
   tables, columns, types, nullability, indexes, unique constraints and foreign keys.
2. If anything cannot be fixed safely in place (a different column type or nullability, a
   missing unique constraint), it stops **without changing or backing up** the database
   and lists the problems. `python -m app.migrate status` shows the same report read-only.
3. Otherwise it backs up, creates the missing baseline tables, columns and indexes, checks
   again, and only then stamps the database at `0001` and upgrades it to the latest revision.
4. Extra tables or columns (from older or other builds) and SQLite money columns declared
   `FLOAT` instead of `NUMERIC` are reported as notes and left untouched; in SQLite both
   store values identically.

**If a migration fails:** stop the service, copy the backup file over the database (for
example `copy data\backups\madzihub-...-before-upgrade.db data\madzihub.db`), delete any
`data\madzihub.db-wal` and `data\madzihub.db-shm` left beside it, reinstall the previous
release, start it and run the smoke tests. Report the command output. Never downgrade
below the baseline: revision `0001` refuses to be downgraded because it would drop all data.

**SQLite settings.** Every connection enables foreign keys and WAL journaling (readers do
not block the writer). WAL adds `-wal` and `-shm` files next to the database while it is
open; back up with the migrate command or with the service stopped, not by copying the
`.db` file of a running system.

**For developers:** change the model, run `python -m alembic revision --autogenerate -m "..."`,
review and edit the generated file under `app/migrations/versions/`, then run the tests.
`tests/test_migrations.py` fails if the models and the migrations disagree.

## Backup and restore
### SQLite mode
Back up (with the service stopped, or use the file `python -m app.migrate` creates):
- `data/madzihub.db`
- deployment package version
- current environment configuration

### Restore
1. Stop the service.
2. Restore the database file and delete any `-wal` / `-shm` files beside it.
3. Restore matching application version.
4. Check it: `python -m app.migrate status` must report "up to date".
5. Start the service.
6. Run smoke tests.
