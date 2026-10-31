# Jupiter Prediction API integration

Checked: 2026-10-31 against the official Jupiter developer documentation and `jup-ag/api-examples`.

## Scope implemented

The soccer dashboard uses documented read-only endpoints at `https://api.jup.ag/prediction/v1`: `GET /events?category=sports&tags=soccer&filter=live&includeMarkets=false` and `GET /events/scores?eventIds=...`. The first filters event discovery to live-tagged soccer; the second returns score/status/period/elapsed data for those IDs. Score data is cached for 20 seconds and requests are manually refreshed. When a user selects a match, the dashboard calls documented `GET /events/{eventId}` to load that event's market metadata, then displays only `moneyline`, `soccer_first_to_score`, and `both_teams_to_score` rows. It does not fetch detailed markets for every live event. The adapter also supports a bounded event-market page through `GET /events/{eventId}/markets?start=0&end=20`. No order-building, execution, wallet, signing, or transaction endpoint is called.

The API is in beta. Event and market IDs are preserved as provider IDs. Prices in `buyYesPriceUsd`, `sellYesPriceUsd`, `buyNoPriceUsd`, and `sellNoPriceUsd` are documented in micro-USD; the adapter converts them to dollars with `Decimal` division by 1,000,000. Per-market `pricing.volume` is displayed in USD. The `$1 pays` multiple is calculated as `$1 / buy price` before fees; it is not an executable-return guarantee. Favorite and long-shot labels are derived from relative moneyline YES prices, not supplied by Jupiter. The market response does not supply the screenshot's `REG TIME` label. Displayed prices are not a substitute for an order-book depth check. The app does not create strategy signals from them. Transient connection and 5xx failures get up to two retries using capped exponential backoff with jitter; a 429 is surfaced without retrying.

Jupiter markets are binary YES/NO markets. Its event/market structure is not automatically converted into the project's HOME/DRAW/AWAY mapping. The feed also does not provide the shots, possession, and corner statistics needed by the strategies.

## Read-only endpoints verified in official docs

- `GET /events` and `GET /events/search`: discover events, filters, pagination, and market summaries.
- `GET /events/scores`: live scores for specified event IDs. It does not provide shots, possession, or corners.
- `GET /events/{eventId}/markets`: fetch a paginated market list; the app caps each request at 20 markets.
- `GET /markets/{marketId}`: details and buy/sell prices.
- `GET /orderbook/{marketId}`: documented YES/NO bid levels and quantities. Not yet requested by the app, so displayed prices have no depth validation.
- `GET /events/{eventId}/score`: per-event score and status details; not currently used by the app.

The official quick start describes keyless access at 0.5 requests/second; publishable keys follow the same rate limits. The client rate-limits all calls to that conservative pace. The existing `JUPITER_API_KEY` is loaded from local `.env` and was verified with live soccer and score requests on 2026-10-31; never put it in the repository.

## Reference repository

The linked official [`jup-ag/api-examples`](https://github.com/jup-ag/api-examples) README describes its Prediction Markets app as a trading UI with orderbook, positions, and wallet integration, and its video demo as supporting bet placement. Those write paths are outside this integration. The app borrows no signing or transaction behavior from the examples.

## Limits and remaining work

- This API is beta and may change.
- The API's market volume fields are shown only when present; volume is not treated as executable liquidity.
- There is no confirmed shared event identifier between Jupiter and API-Football. Cross-provider matching is deliberately not automatic.
- Data is fetched on demand and is not persisted to the database yet.
- No official WebSocket interface was identified in the Prediction API documentation reviewed; this app does not invent one or poll continuously.

## Official sources

- [Prediction Market API](https://developers.jup.ag/docs/prediction)
- [Events & Markets](https://developers.jup.ag/docs/prediction/events-and-markets)
- [Get Events API reference](https://developers.jup.ag/docs/api-reference/prediction/get-events)
- [Get Market API reference](https://developers.jup.ag/docs/api-reference/prediction/get-market)
- [Jupiter `api-examples` README](https://github.com/jup-ag/api-examples/blob/main/README.md)
