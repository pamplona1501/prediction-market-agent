# Prediction Market Agent

A read-only soccer market monitor with a FastAPI service, a browser dashboard, SQLAlchemy persistence, and an optional Streamlit research view. Jupiter supplies market events, scores, and orderbooks through its documented REST API. LiveScore MCP supplies selected-match stats through a manual, on-demand refresh; Jupiter's score feed does not include shots, possession, or corners. The service evaluates strategy candidates but **never places simulated or real orders**. Wallet support, signing, transaction submission, and real-money trading are disabled.

## Security first

A Neon connection credential was previously exposed in chat and must be treated as compromised. **Rotate/reset that Neon role password before connecting this app.** Put the newly rotated connection URL only in a local `.env` file or a hosting provider's secret settings. Never paste it into chat, commit it, or include it in backups. No seed phrase or private key is needed.

The repository ignores `.env`, `.env.*` (except `.env.example`), Streamlit secrets, local databases, virtual environments, and backup contents. The dashboard hides database driver error details so a connection string cannot leak through the UI.

## Windows 11 setup (PowerShell)

From the repository folder:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks environment activation, run this once in PowerShell, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Edit `.env` locally and set `DATABASE_URL` to the newly rotated Neon connection URL. You may set `DATABASE_URL_POOLED` for dashboard connections. The URL must not be shared or committed. Migrations prefer `DATABASE_URL`, and use `DATABASE_URL_POOLED` only when the direct URL is absent. PostgreSQL connections require SSL.

Apply database migrations (back up any existing database first):

```powershell
python -m alembic upgrade head
```

Start the live monitoring service and browser UI:

```powershell
python -m uvicorn live_app.main:app --host 127.0.0.1 --port 8502
```

Open `http://127.0.0.1:8502`. Keep the service bound to loopback; the UI currently has no user authentication. To use the older Streamlit research view instead, run `python -m streamlit run app.py` in a separate terminal.

Run automated tests:

```powershell
pytest
```

Without a configured database URL, the dashboard still starts and reports that database configuration is missing. No tables are created automatically by opening the dashboard.

## Live soccer monitoring

- The service uses `JUPITER_API_KEY` and Jupiter's documented `tags=soccer` plus `filter=live` filters, followed by `GET /events/scores`. It refreshes in-play data on a bounded REST polling loop (default 30 seconds), fetches the selected event's three-way moneyline orderbooks, and streams updates to the browser over the app's WebSocket. This WebSocket is between the local FastAPI service and browser; Jupiter's upstream API is polled over REST.
- Market prices and volumes use Jupiter's documented fields; displayed $1 payouts are derived from the current buy price before fees. Favorite/long-shot labels are price-derived. The example's `REG TIME` label is not included in Jupiter's market response.
- Jupiter's documented score response includes score/status/period/time but not the in-game statistics. Use **Fetch match stats** to retrieve the selected match's shots, shots on target, possession, passes, pass accuracy, fouls, cards, offsides, and corners from LiveScore MCP. Matching uses a unique home/away team pair; a lagging or different score is shown but blocks strategy eligibility. See the [LiveScore MCP integration details](docs/integrations/livescore-mcp.md).
- Selected-match market/orderbook observations, in-play score/stat snapshots, and upcoming pre-match moneyline baselines are persisted by SQLAlchemy. Candidate evaluations and gate results are audited in the database; no orders or trades are created. Migrations `0002` through `0005` extend the initial schema. See [market snapshot and event matching design](docs/data-model/market-snapshots-and-event-matching.md) and [live monitor architecture](docs/architecture/live-monitor.md).

The Streamlit sidebar also includes **Engine View**, an alternative read-only layout for sourced soccer scores and market groups. It remains separate from the always-on FastAPI live monitor.

## Initial schema

Alembic manages tables for events, external event references, markets, outcome mappings, market snapshots, and match snapshots. Prices and volumes use fixed-precision numeric columns, timestamps are timezone-aware, and foreign keys/indexes protect relationships and observation queries. The schema intentionally contains no orders, fills, positions, or strategy signals; those belong to later milestones.

## Current scope and limitations

- Jupiter live events/scores and market quotes refresh on a bounded interval. LiveScore MCP statistics are fetched manually for the selected match and are not background-polled.
- Strategy rules generate candidate/rejection diagnostics only. There is no paper order execution, simulated position accounting, wallet, or live execution.
- Live monitoring is near-real-time with bounded Jupiter polling, not an upstream Jupiter push feed. Missing/stale statistics, unverified match mappings, absent pre-match baseline, thin orderbook depth, or failed hard gates suppress candidates.
- To build the pre-match baseline required by the favorite-rebound strategy, run the service while the relevant event is still upcoming and allow its scheduled discovery cycle to capture observations.
- LiveScore MCP's README limits its hosted free service to personal, non-commercial use and prohibits bulk scraping and automated harvesting. The app requests stats only when you click for the selected event. Check current terms and data-use rights before hosting, redistributing, or commercial use.
- Neon is intended as authoritative storage. Do not rely on Render's ephemeral filesystem for persistent data or backups.

## Git safety

Before committing, run `git status` and confirm `.env` is absent. Commit `.env.example`, which contains blank placeholders only. Do not commit local database files, private keys, wallet files, or sensitive backups.
