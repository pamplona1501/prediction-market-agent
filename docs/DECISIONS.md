# Decisions

## 2026-10-31 — Milestones 0–1 baseline

- The separate starter folder had no `.git` directory, so its Git history, branches, and remotes could not be inspected. The designated workspace is a clean, empty Git repository on `master` with no remote configured. Existing starter source was copied into the workspace; its local `.env`, `.venv`, caches, and any secret-bearing files were excluded.
- SQLAlchemy 2.x models and Alembic provide the initial schema. The dashboard checks connectivity but does not run migrations or create tables on page load.
- Dashboard connection errors are generic. Raw driver exception text and connection URLs are never displayed.
- PostgreSQL URL schemes are normalized to `postgresql+psycopg`; SSL is required for PostgreSQL connections.
- App health checks prefer `DATABASE_URL_POOLED` and fall back to `DATABASE_URL` if the pooled endpoint is unavailable. Status text does not expose connection details.
- Milestone 1 has reference/observation tables only. Strategy, execution, and trading history tables are deferred to their specified milestones.
- Real-money trading remains disabled and is outside the application surface.

## 2026-10-31 — Read-only provider adapters

- Jupiter's official Prediction API is beta and provides event/market discovery, binary YES/NO prices, and read-only event scores. The soccer dashboard uses the documented `tags=soccer` and `filter=live` filters plus `/events/scores`, without displaying market prices. The adapter retains a bounded event-market page method. Calls are manually refreshed, cached, and rate-limited at the publishable/keyless 0.5 RPS pace; no wallet or transaction methods are implemented.
- API-Football was selected as the initial match-statistics adapter because its documented API supplies live fixture status/minute and per-team shots, possession, and corners. Its free-plan allowance and provider licensing/coverage limits are documented; its key is optional and was not present/configured during implementation.
- Jupiter IDs and API-Football fixture IDs are not joined by team-name similarity. A validated manual mapping is required before the app can combine observations.
- The Jupiter and API-Football adapters are read-only, suppress response bodies and credentials, retry transient failures with bounded exponential backoff and jitter, and do not submit transactions.
- The official Jupiter example README points to a wallet-enabled trading UI. Its signing and order flows were not used.
