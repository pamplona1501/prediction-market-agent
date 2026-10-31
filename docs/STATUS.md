# Project status

Updated: 2026-10-31

## Completed

- Milestone 0: audited the empty designated Git workspace and reviewed the starter source in `Documents\projects\prediction-market-agent`. Copied source while excluding `.env`, `.venv`, and generated caches.
- Added ignore rules for local credentials, Streamlit secrets, local databases, virtual environments, and backups.
- Milestone 1: added a Streamlit health dashboard, safe environment configuration check, SQLAlchemy schema, and initial Alembic migration.
- Documented Windows PowerShell setup and the required Neon credential rotation.
- Applied the initial migration to Neon and verified Alembic reports `0001_initial (head)`.
- Confirmed the dashboard starts successfully and the workspace `.env` is ignored by Git.
- Verified the direct Neon connection. The configured pooled URL failed, so the app health check now falls back to the direct URL without exposing connection details.
- Added a manual, read-only Jupiter Prediction API soccer feed. `tags=soccer` plus `filter=live` returned five live-tagged soccer events in the 2026-10-31 check; the score endpoint returned matching score rows. The score table loads without market data; market details are requested only for a selected match.
- Added selected-match market detail tables for moneyline, first team to score, and both teams to score. Market volume and binary buy prices are read from Jupiter; payout multiples and favorite/long-shot labels are explicitly derived.
- Added an alternative Streamlit **Engine View** page with a dark high-contrast layout, sourced match tracker, selected-match market table, and actual provider request log. It does not show simulated balances, RPC health, or fabricated strategy gate results.
- Added a read-only API-Football adapter for fixtures and stats. It remains inactive until `API_FOOTBALL_KEY` is configured.
- All automated tests pass.

## Not yet completed

- Jupiter events and API-Football fixtures are not mapped to one another; no cross-provider strategy input is allowed.
- Fetched provider observations are displayed but not yet persisted. Orderbook depth is not fetched, strategies and paper execution are not implemented, and no live execution is available.
- API-Football publishing rights have not been confirmed. Do not enable it for a public/hosted dashboard until applicable data permissions are secured.

## User setup needed

For Jupiter soccer scores, use **Refresh live soccer scores**; the configured `JUPITER_API_KEY` is used. Jupiter's documented score endpoint does not include shots, possession, or corners. To display those statistics, configure `API_FOOTBALL_KEY` in the ignored `.env` after obtaining a provider key and reviewing data-use rights. Restart Streamlit after changing `.env`.

The current shell's bare `python` command still points at an inaccessible Windows Store alias. Use `\.venv\Scripts\python.exe` or activate the workspace `.venv` in PowerShell.
