# Live monitor architecture

## Runtime path

```text
Jupiter REST ───────┐
                    ├─> bounded monitor loop ─> normalized event state ─> strategy candidates
LiveScore MCP ──────┴─> on-demand selected-match refresh        │                    │
                                      ├─> SQLAlchemy snapshots/audit <─────────────┘
                                      └─> bounded subscriber queue ─> FastAPI SSE ─> browser UI
Jupiter REST ─> low-priority 5-minute radar task ─> 24-hour upcoming view
                                               └─> 48-hour baseline snapshots
```

`live_app.main` owns the HTTP/SSE surface. `monitoring.service` performs scheduled Jupiter ingestion and assembles a current view. Provider adapters own HTTP/MCP parsing; `integrations.market_data.capture` and the `database` modules handle normalization and persistence; `strategies.live` is a pure candidate evaluator. The legacy Streamlit pages are retained as a separate research UI. LiveScore MCP is called once when the user selects a match, then only on an explicit refresh action.

## Refresh and resource bounds

- The selected in-play event is refreshed at a configurable interval (default 30 seconds; accepted range 15–300 seconds).
- LiveScore MCP statistics are never polled in the monitor loop. Selecting a match triggers one initial fetch; later requests require the refresh button. Requests are rate-limited to one every 15 seconds and fetch details for only one exact selected match.
- Upcoming soccer discovery runs as an independent task every five minutes. Startup waits up to 20 seconds for its first scan so the default Upcoming view is populated before the page is served when Jupiter responds promptly. It uses Jupiter's [`GET /events` filters and pagination](https://developers.jup.ag/docs/api-reference/prediction/get-events.md): `filter=upcoming`, `tags=soccer`, `sortBy=volume` descending, and `start`/`end`, capped at 100 events per scan. The displayed future events also sort by event volume descending and require reported volume of at least US$100,000. Existing pre-match snapshots continue for eligible events within 48 hours. The shared asynchronous Jupiter limiter prioritizes live requests, then selected-event details, then radar requests.
- Radar view is built from the latest successful response in memory. Provider failures retain those rows and mark them stale. Volume delta is unavailable until the event appears in two successful scans. A 75¢ team favorite only indicates that Strategy 1's 26¢ threshold may apply if live conditions and all gates pass; a US$1M event-volume badge records that observation only.
- Watchlist membership is stored in `watchlist_items` and remains until manually removed. A pin does not start match monitoring or increase the Jupiter request cadence. Live rows show the pin when that event appears in the live feed.
- The Upcoming tab is the browser's default view. Selecting a listed match opens its cached Jupiter kickoff, event volume, and three-way pre-match quote details in a separate panel; it does not call the live monitor route, fetch match statistics, or create an execution intent. The selected detail refreshes when the independent radar feed succeeds.
- The monitor requests orderbooks only for the selected match's three moneyline markets. It does not download every event's complete market list on each cycle.
- Jupiter and LiveScore MCP use lifecycle-managed `httpx.AsyncClient` instances with bounded retries and secret-safe errors. Synchronous SQLAlchemy work runs with `asyncio.to_thread` so database calls do not block the event loop.
- Per-browser update queues have capacity one; a slow client receives the latest state instead of an unbounded backlog. The service log retains at most 100 entries.
- API failures are surfaced as stale/unavailable source state; they do not create prices or statistics from fixtures or examples.

## Identity and persistence

Jupiter's event ID is the canonical event ID. A LiveScore MCP match reference is verified only when one unique home/away team pair matches in the same orientation; common aliases are normalized and the detail response rechecks identity. Missing or ambiguous matches fail closed. Score consistency is checked separately, so lagging scores can display stats but still block strategy candidates.

Market snapshots retain event/market IDs, outcome side, quote and depth information, source observation time, and whether the row was collected pre-match or in-play. Pre-match baselines are read by Jupiter market ID so the evaluator does not silently compare unrelated contracts. `StrategyEvaluation` stores the candidate/rejection outcome and its input/gate audit fields. Database or migration errors disable persistence and are reported without exposing connection credentials.

Apply Alembic migrations through the current head before relying on persistence. Migration `0001` is the initial schema; `0002`–`0004` add provider mapping, snapshot/audit, and pre-match/live phase support; `0005` adds extended match-stat columns; `0006` adds disabled execution-intent audit records; `0007` adds persistent watchlist pins. Back up a database before applying migrations; no migration has been applied to the user's Neon database.

## Strategy boundary

The evaluator follows the project's master specification: UnderDog Scouter, Draw Compression, and Heavy Favorite Rebound. Shared hard gates require a supported three-way market, sufficient event volume, first-half timing, fresh and consistent source data, verified match statistics, usable ask-side depth, and acceptable estimated slippage. Strategies requiring statistics remain blocked until the user fetches fresh data for that match. Candidate/rejection diagnostics are persisted and shown in the UI. Eligible candidates also produce deduplicated disabled intent audit records using the exact mapped Jupiter market and its YES contract. The broker is a validation-only stub with no wallet, signing, RPC, or order submission. Real-money trading is disabled. See [Core Rules](../CORE_RULES.md) for the exact current thresholds, trigger conditions, and safety boundaries.

## Streaming and source cadence

The browser subscribes to `/api/events` using Server-Sent Events. Each connection receives the latest snapshot first, then the newest state after each publication. Queues hold one item, replacing stale queued state for slow clients; heartbeat comments keep idle connections alive. Browsers reconnect automatically.

Jupiter Prediction API is currently consumed through REST polling at a default 30-second interval (configured range 15–300 seconds). No supported Jupiter Prediction push feed has been identified. SSE is a browser delivery mechanism and does not make provider observations fresher. Provider requests retain conservative spacing to respect rate limits.

## Service and security boundary

Local start command:

```powershell
python -m uvicorn live_app.main:app --host 127.0.0.1 --port 8502
```

The UI's `/api/*` endpoints and SSE stream currently have no authentication or CSRF protection. Loopback binding is therefore the supported local mode. Do not bind to `0.0.0.0`, forward the port, or host this service publicly until authentication, origin controls, deployment secrets, and operational monitoring are added.

The UI is near-real-time and depends on API availability, rate limits, and the machine running the service.
