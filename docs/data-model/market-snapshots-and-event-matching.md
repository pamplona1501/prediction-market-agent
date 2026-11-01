# Market snapshots and future event matching

## Snapshot capture

The Live Soccer and Engine View pages capture data only for the event a user selects. A selection change makes a fresh Jupiter event-detail request; the explicit **Refresh markets & record snapshot** button repeats the same operation for the current selection. Listing/refreshing the event feed does not write rows, and there is no background poller.

For each market in the selected event-detail response, the persistence helper appends two rows to `market_snapshots`:

- `outcome_key=YES`: Jupiter sell-YES price is the observed bid; buy-YES is the ask.
- `outcome_key=NO`: Jupiter sell-NO price is the observed bid; buy-NO is the ask.
- `event_volume_usd` stores the event aggregate (`events.volumeUsd`); `market_volume_usd` stores the individual market's `pricing.volume`.
- `observed_at` is the local UTC time at which the detail response was received. `source` records `jupiter_prediction_api`.
- Missing, zero, or out-of-range prices become NULL. Jupiter does not provide executable depth in this response, so depth remains NULL.

Event and market identity rows are reused by their provider IDs; each capture appends new observations. The UI still displays fetched market data if persistence fails, and reports that failure without exposing database driver messages or credentials. The caller owns the SQLAlchemy transaction. No raw upstream response, API key, wallet, trade, or inferred value is persisted.

`MarketOutcome` currently represents the soccer `HOME`, `DRAW`, and `AWAY` mapping used by the initial schema. It is intentionally not used for Jupiter binary contract YES/NO observations; the snapshot table has no outcome foreign key or check constraint, allowing both vocabularies while market identity remains the provider contract ID.

## Provider event matching

`events` remains the canonical event record for compatibility with the initial schema. `event_provider_references` holds one identity per provider event and links it to that canonical event:

| Column | Purpose |
| --- | --- |
| `event_id` | Canonical event foreign key |
| `provider`, `provider_event_id` | Exact external identity; unique as a pair |
| `provider_event_name` | Provider supplied display name, for review |
| `scheduled_start_at` | Provider kickoff in UTC when supplied |
| `mapping_status` | `unverified`, `verified`, or `rejected` |
| `mapping_method`, `verified_at` | Audit of how/when a human or later controlled matcher confirmed the link |

Jupiter primary event references are recorded as verified using their provider ID. The current LiveScore MCP matcher creates a provider reference for one unique live home/away team pair, allowing known naming aliases. If multiple candidates exist, an exact score match may disambiguate them; otherwise the mapping fails closed. The detail response must confirm the same home/away pair. Stats may still be displayed when the provider score lags, but score consistency remains a separate hard strategy gate. A unique `(provider, provider_event_id)` prevents linking one provider match to multiple canonical events.

LiveScore MCP references use `mapping_method="unique_live_team_pair"` and match statistics are appended to `match_snapshots` with `source="livescore_mcp"`. Migration `0005_match_statistics_categories` adds shots on target, passes, pass accuracy, fouls, cards, and offsides columns. The provider supplies no timestamp used by this integration, so `observed_at` is the local response receipt time. The older API-Football mapper remains legacy code and is not called by the live monitor.

## Migration

Alembic revision `0002_snapshot_refs` adds `market_volume_usd` and `event_provider_references`. It is additive and does not delete or rewrite existing rows. It has been prepared locally but not applied to any configured database. After reviewing the change and confirming a backup, apply it from the repository with:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```
