# Jupiter Prediction API integration

Checked: 2026-10-31 against the official Jupiter developer documentation and `jup-ag/api-examples`.

## Scope implemented

The live service uses documented read-only endpoints at `https://api.jup.ag/prediction/v1`: `GET /events?category=sports&tags=soccer&filter=live&includeMarkets=false`, `GET /events/scores?eventIds=...`, `GET /events/{eventId}`, and `GET /orderbook/{marketId}`. Event discovery and scores run on a bounded polling schedule. Detailed orderbooks are requested only for the currently selected event, and only its three-way moneyline is used by candidate evaluation. Upcoming event quotes are collected on a slower schedule for pre-match reference prices. The app's browser WebSocket is served by FastAPI; it does not imply an upstream Jupiter WebSocket. No order-building, execution, wallet, signing, or transaction endpoint is called.

The API is in beta. Event and market IDs are preserved as provider IDs. Prices in `buyYesPriceUsd`, `sellYesPriceUsd`, `buyNoPriceUsd`, and `sellNoPriceUsd` are documented in micro-USD; the adapter converts them to dollars with `Decimal` division by 1,000,000. The current event response's `volumeUsd` numeric value is also normalized from micro-USD to USD at ingestion; per-market `pricing.volume` is already displayed in USD. The UI uses whole-dollar currency formatting (for example, `US$1,345,651`). The `$1 pays` multiple is calculated as `$1 / buy price` before fees; it is not an executable-return guarantee. Favorite and long-shot labels are derived from relative moneyline YES prices, not supplied by Jupiter. The market response does not supply the screenshot's `REG TIME` label. Displayed prices are not a substitute for an order-book depth check. The app does not create strategy signals from them. Transient connection and 5xx failures get up to two retries using capped exponential backoff with jitter; a 429 is surfaced without retrying.

Jupiter markets are binary YES/NO markets. The monitor identifies HOME/DRAW/AWAY by matching the market outcomes to the event's exact home and away team names and draw outcome. Ambiguous or incomplete markets fail closed. Jupiter does not provide shots, possession, or corner statistics needed by strategies.

## Read-only endpoints verified in official docs

- `GET /events` and `GET /events/search`: discover events, filters, pagination, and market summaries.
- `GET /events/scores`: live scores for specified event IDs. It does not provide shots, possession, or corners.
- `GET /events/{eventId}/markets`: fetch a paginated market list; the app caps each request at 20 markets.
- `GET /markets/{marketId}`: details and buy/sell prices.
- `GET /orderbook/{marketId}`: documented YES/NO bid levels and quantities. The live monitor requests these for the selected event; complementary binary bids are used to derive each side's ask and depth.
- `GET /events/{eventId}/score`: per-event score and status details; not currently used by the app.

The official quick start describes keyless access at 0.5 requests/second; publishable keys follow the same rate limits. The client rate-limits all calls to that conservative pace. The existing `JUPITER_API_KEY` is loaded from local `.env` and was verified with live soccer and score requests on 2026-10-31; never put it in the repository.

## Reference repository

The linked official [`jup-ag/api-examples`](https://github.com/jup-ag/api-examples) README describes its Prediction Markets app as a trading UI with orderbook, positions, and wallet integration, and its video demo as supporting bet placement. Those write paths are outside this integration. The app borrows no signing or transaction behavior from the examples.

## Limits

- This API is beta and may change.
- The API's event volume field is used for the configured event-level liquidity gate; it is distinct from displayed orderbook depth, which is used for executable-size screening.
- There is no shared event identifier between Jupiter and API-Football. Cross-provider matching requires explicit user confirmation and exact team/kickoff verification.
- Polling is near-real-time, not tick-level. The current selected event is polled on a bounded interval to respect API limits.
- Missing or ambiguous data does not produce a strategy candidate. The service records diagnostics and remains read-only.

## Official sources

- [Prediction Market API](https://developers.jup.ag/docs/prediction)
- [Events & Markets](https://developers.jup.ag/docs/prediction/events-and-markets)
- [Get Events API reference](https://developers.jup.ag/docs/api-reference/prediction/get-events)
- [Get Market API reference](https://developers.jup.ag/docs/api-reference/prediction/get-market)
- [Jupiter `api-examples` README](https://github.com/jup-ag/api-examples/blob/main/README.md)
