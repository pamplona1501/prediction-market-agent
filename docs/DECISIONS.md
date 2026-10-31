# Decisions

## 2026-10-31 — Milestones 0–1 baseline

- The separate starter folder had no `.git` directory, so its Git history, branches, and remotes could not be inspected. The designated workspace is a clean, empty Git repository on `master` with no remote configured. Existing starter source was copied into the workspace; its local `.env`, `.venv`, caches, and any secret-bearing files were excluded.
- SQLAlchemy 2.x models and Alembic provide the initial schema. The dashboard checks connectivity but does not run migrations or create tables on page load.
- Dashboard connection errors are generic. Raw driver exception text and connection URLs are never displayed.
- PostgreSQL URL schemes are normalized to `postgresql+psycopg`; SSL is required for PostgreSQL connections.
- Milestone 1 has reference/observation tables only. Strategy, execution, and trading history tables are deferred to their specified milestones.
- Real-money trading remains disabled and is outside the application surface.
