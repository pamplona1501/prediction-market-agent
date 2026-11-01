# Sports data provider research

Checked: 2026-10-31 against providers' official documentation, pricing, and terms pages.

> **Current status (2026-11-01):** [LiveScore MCP](livescore-mcp.md) is integrated for on-demand selected-match statistics. Selecting a match triggers its initial fetch; later updates are manual. The older API-Football adapter details below are retained as historical research; the live monitor does not call it. Earlier provider comparisons are available in [three free live-statistics options](free-live-statistics-options.md).

## Current dashboard feed: Jupiter soccer events and scores

The dashboard filters `GET /events` with `category=sports`, `tags=soccer`, and `filter=live`, then requests `GET /events/scores` for the returned event IDs. A live check on 2026-10-31 returned soccer events and matching score rows. Jupiter exposes teams, score, period, elapsed time, status, and update time in its documented score schema. It does **not** document shots, possession, or corners in that response, so those statistics are left blank/unavailable rather than inferred.

## Legacy provider research: API-Football adapter, not used by the live monitor

The adapter implements read-only calls to API-Football's documented `/fixtures?live=all` and `/fixtures/statistics?fixture={id}` endpoints. It reads fixture IDs, team names, status, elapsed minute, score, total shots, possession, and corners. Each statistics request is made only after an operator selects one fixture; the UI does not fetch statistics for every match.

Current published free plan: $0, 100 requests/day, with the provider listing livescore, fixtures, and statistics among available endpoints. The provider's rate-limit page lists 10 requests/minute on the free plan. Its docs indicate fixture/event data updates about every 15 seconds and statistics about every minute; these intervals are explicitly indicative and can vary by competition. Coverage data can vary by league/season, and a listed coverage flag is not a guarantee that every match statistic is present.

Activation requires `API_FOOTBALL_KEY` in the local ignored `.env`. The adapter fails closed when the key is missing, suppresses raw provider error bodies, and does not access odds endpoints. Requests are globally spaced by at least six seconds to stay within the published free-plan rate of 10/minute. Transient connection and 5xx failures get up to two retries using capped exponential backoff with jitter; 429 responses are surfaced without retrying.

**Data rights:** API-Football's terms say it does not grant a license to use or publish the supplied data and that users must obtain any necessary rights from the relevant competition owners. Do not use this feed in a public/hosted dashboard until the required data-use permissions have been confirmed. The dashboard labels source and retrieval time and does not present provider data as guaranteed.

## Comparison

| Provider | Live/stat coverage | Published limits/pricing checked 2026-10-31 | Mapping and rights notes |
|---|---|---|---|
| Jupiter Prediction API | Soccer-tagged events and score/status/period/minute endpoint. No shots, possession, or corners in the documented score response. | Publishable keys have keyless 0.5 requests/second limits; beta. A keyed soccer query and score request succeeded on 2026-10-31. | Jupiter event IDs are not API-Football fixture IDs. No automatic matching. Not a complete football stats source. |
| API-Football | Live fixtures, score/status/minute, plus per-fixture shots, possession, and corners where the selected competition supplies them. Fixture feed is about 15-second cadence; stats about 1 minute (indicative). | Free: 100 requests/day, 10/minute. Paid tiers are listed on provider pricing; no purchase made. | Requires key. Terms do not grant publication rights; obtain permissions before public display. IDs are provider-specific. |
| football-data.org | Fixtures/results and scores; its statistics add-on lists corners, possession, and shots. | Free: 12 competitions, delayed scores, 10 calls/minute. Live-score tier lists €12/month and 20 calls/minute; statistics add-on lists €15/month and requires a regular plan (VAT may apply). | Terms require visible attribution and restrict use to one application; league/team imagery rights must be cleared separately. Coverage and data fields vary by competition. |

## Event mapping policy

The current LiveScore MCP mapping policy is documented in [its integration note](livescore-mcp.md): one unique home/away team pair is required, and ambiguous candidates fail closed. Team identity can be accepted when the provider score lags Jupiter, but the strategy score-consistency gate remains blocked. The legacy API-Football mapper uses separate provider-specific IDs and is not called by the live monitor.

The dashboard records the LiveScore MCP response receipt time. The provider response does not expose an upstream timestamp used by this integration, so the display time is not proof that the upstream data changed at that exact moment.

## Official sources

- [API-Football v3 documentation](https://www.api-football.com/documentation_v3)
- [API-Football pricing](https://www.api-football.com/pricing)
- [API-Football rate limits](https://www.api-football.com/news/post/how-ratelimit-works)
- [API-Football terms](https://www.api-football.com/terms)
- [football-data.org pricing](https://www.football-data.org/pricing)
- [football-data.org API policies](https://docs.football-data.org/general/v4/policies.html)
- [football-data.org FAQ](https://www.football-data.org/documentation/faq)
- [football-data.org terms](https://www.football-data.org/about)
