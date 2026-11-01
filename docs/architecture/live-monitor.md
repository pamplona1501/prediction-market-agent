# Live monitor architecture

## Runtime path

```text
Jupiter REST ───────┐
                    ├─> bounded monitor loop ─> normalized event state ─> strategy candidates
LiveScore MCP ──────┴─> on-demand selected-match refresh        │                    │
                                      ├─> SQLAlchemy snapshots/audit <─────────────┘
                                      └─> bounded subscriber queue ─> FastAPI WebSocket ─> browser UI
```

`live_app.main` owns the HTTP/WebSocket surface. `monitoring.service` performs scheduled Jupiter ingestion and assembles a current view. Provider adapters own HTTP/MCP parsing; `integrations.market_data.capture` and the `database` modules handle normalization and persistence; `strategies.live` is a pure candidate evaluator. The legacy Streamlit pages are retained as a separate research UI. LiveScore MCP is called once when the user selects a match, then only on an explicit refresh action.

## Refresh and resource bounds

- The selected in-play event is refreshed at a configurable interval (default 30 seconds; accepted range 15–300 seconds).
- LiveScore MCP statistics are never polled in the monitor loop. Selecting a match triggers one initial fetch; later requests require the refresh button. Requests are rate-limited to one every 15 seconds and fetch details for only one exact selected match. Upcoming Jupiter events are scanned at a slower interval to capture pre-match quotes.
- The monitor requests orderbooks only for the selected match's three moneyline markets. It does not download every event's complete market list on each cycle.
- Provider and SQLAlchemy operations run with `asyncio.to_thread` so blocking I/O does not block the event loop.
- Per-browser update queues have capacity one; a slow client receives the latest state instead of an unbounded backlog. The service log retains at most 100 entries.
- API failures are surfaced as stale/unavailable source state; they do not create prices or statistics from fixtures or examples.

## Identity and persistence

Jupiter's event ID is the canonical event ID. A LiveScore MCP match reference is verified only when one unique home/away team pair matches in the same orientation; common aliases are normalized and the detail response rechecks identity. Missing or ambiguous matches fail closed. Score consistency is checked separately, so lagging scores can display stats but still block strategy candidates.

Market snapshots retain event/market IDs, outcome side, quote and depth information, source observation time, and whether the row was collected pre-match or in-play. Pre-match baselines are read by Jupiter market ID so the evaluator does not silently compare unrelated contracts. `StrategyEvaluation` stores the candidate/rejection outcome and its input/gate audit fields. Database or migration errors disable persistence and are reported without exposing connection credentials.

Apply Alembic migrations through the current head before relying on persistence. Migration `0001` is the initial schema; `0002`–`0004` add provider mapping, snapshot/audit, and pre-match/live phase support; `0005` adds the extended match-stat columns. Back up a database before applying migrations; no migration has been applied to the user's Neon database.

## Strategy boundary

The evaluator follows the project's master specification: UnderDog Scouter, Draw Compression, and Heavy Favorite Rebound. Shared hard gates require a supported three-way market, sufficient event volume, first-half timing, fresh and consistent source data, verified match statistics, usable ask-side depth, and acceptable estimated slippage. Strategies requiring statistics remain blocked until the user fetches fresh data for that match. Candidate/rejection diagnostics are persisted and shown in the UI; the system has no order execution path. Real-money trading is disabled. See [Core Rules](../CORE_RULES.md) for the exact current thresholds, trigger conditions, and safety boundaries.

## Service and security boundary

Local start command:

```powershell
python -m uvicorn live_app.main:app --host 127.0.0.1 --port 8502
```

The UI's `/api/*` endpoints and WebSocket currently have no authentication or CSRF protection. Loopback binding is therefore the supported local mode. Do not bind to `0.0.0.0`, forward the port, or host this service publicly until authentication, origin controls, deployment secrets, and operational monitoring are added.

Jupiter is polled over REST; the app's WebSocket is only the server-to-browser update channel. The UI is near-real-time and depends on API availability, rate limits, and the machine running the service.
