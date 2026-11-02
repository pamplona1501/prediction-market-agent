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

## 2026-11-01 — Live monitoring foundation

- Keep the existing Streamlit app available, while using FastAPI and a browser UI for the live monitor. Browser state is delivered using server-sent events.
- Jupiter ingestion is bounded REST polling. The browser SSE stream is an app-level update channel, not a Jupiter feed subscription.
- Orderbook candidates are built only for the selected event's supported three-way moneyline. Binary YES/NO orderbook sides are normalized to HOME/DRAW/AWAY using exact event outcome names.
- Upcoming event discovery stores pre-match prices, enabling same-market baseline checks. Missing baselines fail closed.
- API-Football fixture matching is user-selected and explicitly verified by team names and kickoff time before statistics can be used.
- Add persistent market/match snapshots and strategy evaluation audit rows. Strategy results remain candidate/rejection diagnostics only; no paper or real orders are produced.
- Use bounded monitor subscriptions and log retention to prevent slow browser clients or long-running sessions from accumulating unbounded memory.
- Keep the service local-only by default (`127.0.0.1`); authentication is not implemented, so network exposure is unsupported.
- Normalize Jupiter event `volumeUsd` from the micro-USD integer scale to actual USD at ingestion, and format displayed amounts as whole-dollar currency for scanability.
- Remove the API-Football setup prompt and fixture-mapping controls from the browser UI while evaluating replacement statistics sources. Do not imply Jupiter includes shots/possession/corners; candidate strategies requiring those inputs stay blocked.
- Show 🔥 for event volume strictly above US$1M. Show ⭐ only when a monitored event has at least one strategy evaluation in `candidate` status, which means that strategy's trigger and all hard eligibility gates passed.
- Label the feed near-live/auto-refreshing: Jupiter is polled over REST on a target interval and its upstream score freshness may lag. The browser's SSE stream only transports the app's latest state.

## 2026-11-01 — LiveScore MCP statistics

- Use LiveScore MCP as the initial additional source for in-game shots, shots on target, possession, and corners. It is called only after an explicit user action for the selected match; do not add scheduled polling because the hosted service prohibits automated harvesting.
- Resolve one provider match by unique home/away team pair, with conservative name normalization and an exact score preferred when available. Recheck team orientation in the detail response; reject missing or ambiguous results. A score mismatch is shown but blocks strategy eligibility.
- Store the accepted match reference and observation in the provider-reference and match-snapshot tables. Migration `0005_match_statistics_categories` adds fields for the requested team stats. Enforce a 15-second manual request cooldown.
- Review personal/non-commercial usage terms and any applicable data rights before hosting or commercial use. See `docs/integrations/livescore-mcp.md`.
