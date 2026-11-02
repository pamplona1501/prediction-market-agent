# Project status

Updated: 2026-11-02

## Implemented

- Milestones 0–1 project baseline, Windows setup, local secret handling, SQLAlchemy models, Alembic migration history, and the existing Streamlit research dashboard.
- Read-only Jupiter soccer event discovery, live score polling, three-way moneyline orderbook retrieval, and binary YES/NO quote normalization.
- On-demand LiveScore MCP statistics integration: selecting a match triggers one initial fetch; later updates require a refresh action. Exact team/score matching, a 15-second request cooldown, SQLAlchemy match snapshots and provider references. The prior API-Football adapter is no longer connected to the live monitor.
- FastAPI live-monitor service and responsive browser UI. Jupiter and LiveScore MCP use lifecycle-managed async HTTP clients; synchronous SQLAlchemy operations run in worker threads. Browser updates stream over Server-Sent Events with bounded per-client queues.
- Upcoming tab with an independent low-priority five-minute Jupiter scan, US$100,000 minimum event-volume filter, capped 100-event pagination, stale last-good display, favorite and event-volume observations, volume deltas, and a persistent manual watchlist. Pins do not start live monitoring.
- Selected-market quote/depth snapshots, match score/stat snapshots, pre-match reference-price observations, strategy-evaluation audits, and deduplicated disabled execution-intent audits in SQLAlchemy. Migration `0005` adds extended match statistics; `0006` adds disabled intent records.
- Three candidate-only strategies from the project master specification, with shared fail-closed gates. Eligible candidates can create a disabled intent audit row. The service never creates orders, paper positions, signatures, or transactions.
- Tests for strategy rules, quote parsing, persistence, event mapping, and monitor normalization.

## Runtime behavior and limitations

- Jupiter is queried via REST polling; no supported upstream Prediction API push feed has been identified. Browser updates stream immediately after this app publishes state, but provider data remains near-live at the configured polling cadence.
- Only the selected in-play event receives detailed orderbook polling. Upcoming soccer events are independently scanned every five minutes; Jupiter requests prioritize the live feed and selected-event details ahead of radar requests. The radar lists future events meeting its volume filter from the capped scan, while pre-match reference quotes continue to be captured up to 48 hours before kickoff.
- The strategy rules need live shots/possession/corners; Jupiter's score API does not provide those fields. Statistics are fetched when a match is selected and become stale under the existing freshness gate. Missing mappings, usable statistics, baseline, freshness, orderbook depth, or another hard gate also block candidates.
- Candidate results and intent rows are diagnostics, not recommendations to execute. Real-money trading remains disabled; the broker module has no wallet, signing, RPC, or order-submission path.
- The browser service currently has no authentication. Keep it bound to loopback for local use; do not expose it to a network without adding authentication and deployment security.
- The LiveScore MCP hosted free service is described as personal/non-commercial and disallows bulk scraping and automated harvesting; this app only fetches one selected match when requested. Review current terms and data rights before hosting or redistribution.

## User setup

1. In the repository directory, create/activate `.venv`, install `requirements.txt`, and keep provider/database secrets in ignored `.env`.
2. Back up the configured database and apply migrations with `python -m alembic upgrade head`.
3. Start the UI/service with `python -m uvicorn live_app.main:app --host 127.0.0.1 --port 8502`, then open `http://127.0.0.1:8502`.
4. Apply current Alembic migrations, then select a match to fetch its initial stats. Use **Refresh stats** for later updates. The default LiveScore MCP endpoint needs no API key; review its use terms in `docs/integrations/livescore-mcp.md`.
5. To use the baseline-dependent favorite strategy, run the service before kickoff so pre-match prices can be recorded.

The legacy Streamlit pages remain available with `python -m streamlit run app.py`.

## Verification

`pytest -q` passed (61 tests; one Starlette TestClient deprecation warning). Python bytecode compilation, `node --check web/app.js`, and `git diff --check` passed. Migration `0007` passed upgrade, downgrade, and re-upgrade on temporary SQLite. No production/Neon migration or provider write was performed.
