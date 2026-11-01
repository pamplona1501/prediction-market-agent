# LiveScore MCP integration

## Behavior

The FastAPI dashboard uses LiveScore MCP as an **on-demand**, read-only statistics source. It does not poll this service in the background. Selecting a Jupiter match triggers the initial statistics fetch; use **Refresh stats** for later updates. The app waits at least 15 seconds between requests; one refresh makes two MCP tool calls: `get_live_scores` to resolve the provider match, then `get_match` for that one match.

The adapter uses Streamable HTTP at `https://livescoremcp.com/mcp` by default. No API key is required. An alternate HTTPS endpoint can be set with `LIVESCORE_MCP_URL`. For both match discovery and selected match details, it requests the provider's compact structured/text response (`format: "text"`): raw JSON is capped at 60,000 characters and can truncate either the worldwide live feed or a detailed match. The adapter reads total shots, shots on target, possession, total passes, pass accuracy, fouls, yellow/red cards, offsides, and corners for both teams. Pass accuracy is calculated from completed passes divided by total passes when both values are valid.

## Match identity and fail-closed behavior

The matcher first looks for one unique live match with the same home/away teams and orientation. It normalizes common club suffixes, accents, and a short list of well-known aliases. An exact current score match wins when several candidates exist; otherwise multiple possible matches are rejected as ambiguous. If no candidate matches, the error includes close provider team-name suggestions when available. The detailed `get_match` response must still confirm the same teams. A different or unavailable provider score no longer hides the stats: they are displayed and recorded, but the strategy's score-consistency gate remains blocked until the score agrees with Jupiter. The live-score list is used transiently; only the selected match's stats are kept or persisted.

Verified observations append to `match_snapshots` with `source="livescore_mcp"`. The associated `event_provider_references` row stores the provider match ID and `unique_live_team_pair` mapping method. Alembic migration `0005_match_statistics_categories` adds the requested statistic columns; apply it before expecting those new values to persist. The app timestamp is a receipt time, not an upstream provider timestamp. Strategy freshness and score-consistency rules still expire or block old/mismatched observations.

## Usage and limits

The upstream repository describes the hosted service as free for personal, non-commercial use, limits usage to 30 tool calls per minute, and prohibits bulk scraping and automated data harvesting. This app makes no scheduled/background requests: each fetch is initiated by selecting or refreshing one match. Confirm the provider's current terms and any data rights for your intended use before hosting, redistribution, or commercial use. The provider says its football data comes from Football Mania.

References: [LiveScore MCP README](https://github.com/holoduke/livescore-mcp/blob/main/README.md), [tool definitions and match-stat fields](https://github.com/holoduke/livescore-mcp/blob/main/tools.go).
