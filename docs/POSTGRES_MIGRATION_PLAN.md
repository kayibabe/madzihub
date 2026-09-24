# PostgreSQL Migration Plan

## Objective
Migrate the SRWB Operations Dashboard from SQLite to PostgreSQL without disrupting monthly reporting workflows.

## Why migrate
SQLite is acceptable for a small internal deployment, but PostgreSQL improves:
- concurrent access
- backup and recovery options
- indexing and query tuning
- operational visibility
- long-term maintainability

## Guiding principle
Do not rewrite the application first. Prepare the app to be database-portable, then cut over in stages.

## Stage 1 — portability readiness
- keep SQLAlchemy as the access layer
- ensure all DB configuration comes from `DATABASE_URL`
- remove SQLite-only assumptions where possible
- test all key queries against PostgreSQL in a staging environment

## Stage 2 — schema validation
- generate a PostgreSQL schema from the ORM models
- compare table types, indexes, defaults, and uniqueness rules
- verify month/year uniqueness and key report filters

## Stage 3 — migration rehearsal
- export a representative SQLite dataset
- import into PostgreSQL staging
- run reconciliation checks across:
  - record counts
  - KPI totals
  - zone/scheme summaries
  - auth/user data

## Stage 4 — application cutover
- switch `DATABASE_URL` in staging first
- run smoke tests
- validate uploads, reports, and admin flows
- cut over production during a controlled change window

## Stage 5 — stabilization
- monitor latency and failed queries
- verify backups
- tune indexes for frequent report filters
- retire SQLite as the primary production store

## Risks to watch
- type mismatches on numeric columns
- date and ordering behavior differences
- upload conflict-resolution behavior
- SQL that relies on SQLite-specific semantics

## Success criteria
The migration is successful when:
- all core user flows work unchanged
- KPI totals reconcile between SQLite and PostgreSQL
- report latency is equal or better
- backup and restore procedures are documented and tested
