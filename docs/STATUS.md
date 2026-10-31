# Project status

Updated: 2026-10-31

## Completed

- Milestone 0: audited the empty designated Git workspace and reviewed the starter source in `Documents\projects\prediction-market-agent`. Copied source while excluding `.env`, `.venv`, and generated caches.
- Added ignore rules for local credentials, Streamlit secrets, local databases, virtual environments, and backups.
- Milestone 1: added a Streamlit health dashboard, safe environment configuration check, SQLAlchemy schema, and initial Alembic migration.
- Documented Windows PowerShell setup and the required Neon credential rotation.

## Not yet completed

- Automated tests passed: 6 tests using Python 3.13.16 from the ignored workspace `.venv`.
- Alembic is installed and recognizes the `0001_initial` migration. The migration has not been applied to Neon because no database URL was configured.
- Database connectivity and migration have not been exercised against Neon; a newly rotated database credential must be configured locally first.
- No external data integration, strategies, paper execution, backups, or live execution are part of these milestones.

## User setup needed

1. Rotate/reset the exposed Neon role password in Neon.
2. Create `.env` from `.env.example` and add the new connection URL locally.
3. Run `alembic upgrade head`, then `streamlit run app.py`.

The current shell's bare `python` command still points at an inaccessible Windows Store alias. Use `\.venv\Scripts\python.exe` or activate the workspace `.venv` in PowerShell.
