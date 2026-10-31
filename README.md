# Prediction Market Agent

A Python and Streamlit research dashboard with an initial PostgreSQL schema. This is a prototype for **research and paper trading only**. It has no wallet support, signing, transaction submission, or live execution.

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

Apply the initial schema:

```powershell
alembic upgrade head
```

Start the dashboard:

```powershell
streamlit run app.py
```

Run automated tests:

```powershell
pytest
```

Without a configured database URL, the dashboard still starts and reports that database configuration is missing. No tables are created automatically by opening the dashboard.

## Initial schema

Alembic manages the initial tables for events, markets, outcome mappings, market snapshots, and match snapshots. Prices and volumes use fixed-precision numeric columns, timestamps are timezone-aware, and foreign keys/indexes protect relationships and observation queries. This first schema intentionally contains no orders, fills, positions, or strategy signals; those belong to later milestones.

## Current scope and limitations

- No live market or sports data adapters are connected; no fixture data is presented as live.
- No strategy execution or simulated positions are implemented in Milestones 0–1.
- The dashboard is a health and setup view, not an always-on worker.
- Neon is intended as authoritative storage. Do not rely on Render's ephemeral filesystem for persistent data or backups.

## Git safety

Before committing, run `git status` and confirm `.env` is absent. Commit `.env.example`, which contains blank placeholders only. Do not commit local database files, private keys, wallet files, or sensitive backups.
