# Project status

Updated: 2026-11-01

## Implemented

- Milestones 0–1 project baseline, Windows setup, local secret handling, SQLAlchemy models, Alembic migration history, and the existing Streamlit research dashboard.
- Read-only Jupiter soccer event discovery, live score polling, three-way moneyline orderbook retrieval, and binary YES/NO quote normalization.
- On-demand LiveScore MCP statistics integration for the selected match: exact team/score matching, a 15-second request cooldown, SQLAlchemy match snapshots and provider references. The prior API-Football adapter is no longer connected to the live monitor.
- FastAPI live-monitor service and responsive browser UI. The worker uses bounded asynchronous scheduling with synchronous provider/database calls moved to worker threads. The browser receives service updates over WebSocket.
- Selected-market quote/depth snapshots, match score/stat snapshots, pre-match reference-price observations, and strategy-evaluation audit records in SQLAlchemy. Migration `0005` adds the requested extended match-stat fields.
- Three candidate-only strategies from the project master specification, with shared fail-closed gates. The service never creates orders, paper positions, signatures, or transactions.
- Tests for strategy rules, quote parsing, persistence, event mapping, and monitor normalization.

## Runtime behavior and limitations

- Jupiter is queried via REST polling; no upstream Prediction API WebSocket has been identified. Browser updates are pushed from this app's FastAPI service over WebSocket.
- Only the selected in-play event receives detailed orderbook polling. Upcoming soccer events are scanned periodically to collect pre-match reference quotes.
- The strategy rules need live shots/possession/corners; Jupiter's score API does not provide those fields. Statistics must be fetched manually and become stale under the existing freshness gate. Missing mappings, usable statistics, baseline, freshness, orderbook depth, or another hard gate also block candidates.
- Candidate results are diagnostic records, not recommendations to execute. Real-money trading remains disabled.
- The browser service currently has no authentication. Keep it bound to loopback for local use; do not expose it to a network without adding authentication and deployment security.
- The LiveScore MCP hosted free service is described as personal/non-commercial and disallows bulk scraping and automated harvesting; this app only fetches one selected match when requested. Review current terms and data rights before hosting or redistribution.

## User setup

1. In the repository directory, create/activate `.venv`, install `requirements.txt`, and keep provider/database secrets in ignored `.env`.
2. Back up the configured database and apply migrations with `python -m alembic upgrade head`.
3. Start the UI/service with `python -m uvicorn live_app.main:app --host 127.0.0.1 --port 8502`, then open `http://127.0.0.1:8502`.
4. Apply current Alembic migrations, then select a match and use **Fetch match stats** when needed. The default Livescore MCP endpoint needs no API key; review its use terms in `docs/integrations/livescore-mcp.md`.
5. To use the baseline-dependent favorite strategy, run the service before kickoff so pre-match prices can be recorded.

The legacy Streamlit pages remain available with `python -m streamlit run app.py`.

## Verification

`pytest -q` passed (37 tests), including LiveScore MCP name aliases, score-feed lag, all requested stat fields, ambiguous matches, and persistence. Python bytecode compilation, `node --check web/app.js`, and `git diff --check` passed. Migration `0005` passed upgrade, downgrade, and re-upgrade on temporary SQLite. No production/Neon migration or provider write was performed.
