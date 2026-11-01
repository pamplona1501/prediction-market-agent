# Core Rules

This monitor reports strategy candidates and rejected checks. It is **read-only**: it does not create orders, simulate fills, manage a wallet, or execute trades. A candidate is a rule match for review, not a recommendation or a promise of profit.

## Data and safety rules

- **Jupiter is authoritative** for event identity, market IDs, prices, depth, scores, and event volume. LiveScore MCP supplies supplemental soccer statistics only.
- Match statistics are fetched manually for the selected event. Accept a provider match only when one unique home/away team pair matches in that order and its detail confirms the teams. Never infer a match from score alone.
- Missing or ambiguous mapping, inconsistent scores, invalid quotes, or stale/missing observations block candidates. Stats may be shown when the provider score lags, but score inconsistency still blocks eligibility. Never fill gaps with sample or invented live data.
- The current freshness limit is **90 seconds** for in-play inputs. Jupiter is polled about every **30 seconds**; this is near-real-time monitoring, not a push feed. LiveScore stats do not refresh automatically.

## Shared eligibility gates

Before a strategy can produce a candidate, the event must have:

- distinct HOME, DRAW, and AWAY moneyline markets;
- verified Jupiter event volume of at least **$1,000,000**;
- a confirmed first-half clock at **45 minutes or earlier**;
- freshly fetched, verified match statistics and a score consistent with Jupiter;
- fresh event, score, stats, and quote observations; and
- valid bid/ask quotes for all three outcomes, with ask-side depth and estimated slippage sufficient for the configured **$5 minimum order value** and **50 bps maximum slippage**.

These checks are fail-closed: a missing value is not treated as a pass.

## Strategy triggers

All prices below are probabilities expressed from `$0.00` to `$1.00` (for example, `$0.25` = 25¢). A trigger is only a candidate when every shared gate above passes.

| Strategy | Trigger conditions |
| --- | --- |
| **Underdog Scouter** | HOME or AWAY is trailing; that side's ask is at most **$0.25**; and it has pressure evidence: at least **4 shots**, or **50% possession**, or **3 corners**. |
| **Draw Compression** | Score is **0–0** between minutes **25–40**; combined shots are at most **3**; DRAW ask is at most **$0.15**. |
| **Heavy Favorite Rebound** | A sourced pre-match HOME/AWAY favorite had at least **80%** probability; it is now trailing by minute **20**; its ask is **$0.50–$0.68**; and it has at least **68% possession** or **3 corners**. The pre-match observation must be no older than **48 hours**. |

The **3-corner trigger is provisional** and configurable. Thresholds are implementation rules, not evidence that a strategy is profitable. See [`strategies/live.py`](../strategies/live.py) for the current executable definitions.

## Persistence and operations

Verified observations and candidate/rejection gate results are logged for review. Database or provider failures must be reported without exposing credentials and must never turn into fabricated observations. Local dashboard access is unauthenticated; keep the service bound to `127.0.0.1` and do not expose it publicly.
