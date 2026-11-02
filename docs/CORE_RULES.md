# Core Rules

This monitor reports strategy candidates and rejected checks. It does not create orders, simulate fills, manage a wallet, or execute trades. Eligible candidates may create a deduplicated disabled intent audit record; it is diagnostic only. A candidate is a rule match for review, not a recommendation or a promise of profit.

## Data and safety rules

- **Jupiter is authoritative** for event identity, market IDs, prices, depth, scores, and event volume. LiveScore MCP supplies supplemental soccer statistics only.
- Matches whose Jupiter score status or period is `SUSPENDED` are hidden from the live list and removed from monitoring.
- Selecting a match triggers one initial LiveScore statistics fetch; later updates are user-triggered. Accept a provider match only when one unique home/away team pair matches in that order and its detail confirms the teams. Never infer a match from score alone.
- Missing or ambiguous mapping, inconsistent scores, invalid quotes, or stale/missing observations block candidates. Stats may be shown when the provider score lags, but score inconsistency still blocks eligibility. Never fill gaps with sample or invented live data.
- The current freshness limit is **90 seconds** for in-play inputs. Jupiter is polled about every **30 seconds**; this is near-real-time monitoring, not a push feed. Browser state updates stream immediately after the monitor publishes a change, but SSE does not make provider data arrive sooner. LiveScore stats do not refresh automatically.
- The Upcoming radar is a separate **five-minute** Jupiter REST scan, capped at 100 events per refresh. It displays future events with reported event volume of at least **US$100,000** and captures pre-match baseline prices for eligible events within 48 hours. Its favorite and volume badges are observations only: a 75¢ team favorite means Strategy 1's 26¢ ceiling may apply only after kickoff and only if all live rules and gates pass; US$1M event volume does not mean liquidity or a live candidate. Pins persist until removed and never start monitoring.

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
| **Underdog Scouter** | HOME or AWAY is trailing; that side's ask is at most **$0.25**. When the sourced pre-match favorite baseline is at least **$0.75**, the underdog ask ceiling increases to **$0.26**. The trailing side also needs pressure evidence: at least **4 shots**, or **50% possession**, or **3 corners**. |
| **Draw Compression** | Score is **0–0** between minutes **25–40**; combined shots are at most **3**; DRAW ask is at most **$0.15**. A DRAW ask of **$0.30 or more** in that score/time window always creates a hard no-trade warning. |
| **Heavy Favorite Rebound** | A sourced pre-match HOME/AWAY favorite had at least **80%** probability; it is now trailing by minute **20**; its ask is **$0.50–$0.68**; and it has at least **68% possession** or **3 corners**. The pre-match observation must be no older than **48 hours**. |

The **3-corner trigger is provisional** and configurable. Thresholds are implementation rules, not evidence that a strategy is profitable. See [`strategies/live.py`](../strategies/live.py) for the current executable definitions.

## Persistence and operations

Verified observations and candidate/rejection gate results are logged for review. Database or provider failures must be reported without exposing credentials and must never turn into fabricated observations. Local dashboard access is unauthenticated; keep the service bound to `127.0.0.1` and do not expose it publicly.
