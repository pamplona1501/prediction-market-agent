# Free in-game soccer statistics options

Researched: 2026-11-01. These were three free-plan candidates compared before selecting LiveScore MCP for an initial on-demand integration.

| Provider | Free access described by provider | Relevant live stats | Main constraint |
| --- | --- | --- | --- |
| [Sportmonks Football API](https://www.sportmonks.com/football-api/free-plan/) | Free plan with no expiry; Danish Superliga and Scottish Premiership | Live fixtures/scores, events, and statistics are listed for free plan coverage | Very narrow competition coverage; likely unsuitable if Jupiter events are from other leagues. |
| [APIfootball.com](https://apifootball.com/) | Free plan; 180 calls per hour per endpoint; England Championship and France Ligue 2 | Provider lists live events including goals, cards, lineups, and statistics | Only two competitions on free plan; confirm required stats and the coverage for a specific match before relying on it. |
| [Stats API](https://stats-api.com/) | New accounts receive 200 free requests once, with 30 requests/minute and no card | Documents team stats for corners, shots, possession, cards, passes, xG, plus a short-cache live-stats endpoint | 200 calls are a one-time trial balance, not a sustainable free quota. Its docs say ingestion is scheduled, not streamed, and provide no sub-minute freshness guarantee; coverage varies by league and match. |

## Practical assessment

Sportmonks is the clearest ongoing-free option if the matches are in its two free leagues. APIfootball.com has a larger request allowance but its free plan covers different, narrow leagues. Stats API appears easiest to test across its documented endpoints, but the one-time 200-call grant makes it a prototype option, not an always-on service plan. In every case, verify coverage for the leagues appearing in Jupiter and review attribution, storage, and display terms before using the data outside a local personal dashboard.

Jupiter's documented live score response provides teams, score, period/status, elapsed time, and update timestamp. It does not include the in-game shot, possession, or corner statistics used by the current candidate rules. LiveScore MCP was selected separately and is integrated as a manually requested source for one selected match. Its hosted free-service terms restrict use to personal, non-commercial activity and prohibit bulk scraping and automated harvesting; see [integration details](livescore-mcp.md). Candidates still remain blocked until fresh, verified stats and all other shared gates pass.

## Official references checked

- [Sportmonks free plan and free-league coverage](https://www.sportmonks.com/football-api/free-plan/)
- [Sportmonks live score API fields and statistics include](https://www.sportmonks.com/football-api/solutions/live-score-api/)
- [APIfootball.com plans and live statistics features](https://apifootball.com/)
- [Stats API plan limits](https://stats-api.com/)
- [Stats API match statistics and live-stats endpoints](https://stats-api.com/docs/endpoints/matches)
- [Stats API freshness and delivery FAQ](https://stats-api.com/faq)
- [Jupiter Prediction API event-score reference](https://developers.jup.ag/docs/api-reference/prediction/get-event-scores)
- [LiveScore MCP repository and usage policy](https://github.com/holoduke/livescore-mcp)
