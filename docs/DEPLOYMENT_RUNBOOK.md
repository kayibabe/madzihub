# Deployment Runbook

## Purpose
This document defines the minimum safe deployment process for the SRWB Operations Dashboard.

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
- `SRWB_ALLOWED_ORIGINS`
- `UPLOAD_LIMIT_MB`
- optional AI provider keys only if AI features are enabled

## Release procedure
1. Build a clean bundle using `scripts/build_release_bundle.py`.
2. Move the bundle to the target host.
3. Extract into a clean deployment directory.
4. Create environment variables or a protected `.env` file on the host.
5. Install dependencies in a fresh virtual environment.
6. Run migrations if needed.
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

## Backup and restore
### SQLite mode
Back up:
- `data/srwb.db`
- deployment package version
- current environment configuration

### Restore
1. Stop the service.
2. Restore the database file.
3. Restore matching application version.
4. Start the service.
5. Run smoke tests.
