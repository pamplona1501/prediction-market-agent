"""Fail-closed live candidate rules from the project master specification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


OUTCOMES = ("HOME", "DRAW", "AWAY")


@dataclass(frozen=True)
class AskLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class MarketQuote:
    market_id: str
    bid: Decimal | None
    ask: Decimal | None
    ask_depth_usd: Decimal | None
    asks: tuple[AskLevel, ...]
    observed_at: datetime | None


@dataclass(frozen=True)
class CandidateConfig:
    max_data_age_seconds: int = 90
    prematch_max_age_seconds: int = 48 * 60 * 60
    max_slippage_bps: Decimal = Decimal("50")
    min_order_value_usd: Decimal = Decimal("5")
    corner_threshold: int = 3  # provisional; master specification leaves it unspecified
    underdog_favorite_boundary: Decimal = Decimal("0.75")
    underdog_max_ask: Decimal = Decimal("0.26")


@dataclass(frozen=True)
class MatchInputs:
    event_id: str
    status: str
    minute: int | None
    home_score: int | None
    away_score: int | None
    event_volume_usd: Decimal | None
    event_volume_verified: bool
    event_observed_at: datetime | None
    score_observed_at: datetime | None
    score_updated_at: datetime | None
    stats_mapped_and_verified: bool
    stats_observed_at: datetime | None
    home_shots: int | None
    away_shots: int | None
    home_possession: Decimal | None
    away_possession: Decimal | None
    home_corners: int | None
    away_corners: int | None
    score_consistent: bool | None
    markets: dict[str, MarketQuote]
    prematch_favorite: str | None = None
    prematch_favorite_probability: Decimal | None = None
    prematch_source: str | None = None
    prematch_observed_at: datetime | None = None


def _first_half(status: str) -> bool:
    return status.strip().upper() in {"1H", "FIRST_HALF", "FIRST HALF", "1ST HALF"}


def _age_ok(timestamp: datetime | None, now: datetime, max_age: int) -> bool:
    if timestamp is None or timestamp.tzinfo is None:
        return False
    age = (now.astimezone(UTC) - timestamp.astimezone(UTC)).total_seconds()
    return -5 <= age <= max_age


def _slippage_bps(quote: MarketQuote, notional: Decimal) -> Decimal | None:
    if quote.ask is None or quote.ask <= 0 or not quote.asks:
        return None
    remain, qty, spend = notional, Decimal("0"), Decimal("0")
    for level in sorted(quote.asks, key=lambda row: row.price):
        if not (Decimal("0") < level.price <= Decimal("1")) or level.quantity <= 0:
            continue
        used = min(remain, level.price * level.quantity)
        qty += used / level.price
        spend += used
        remain -= used
        if remain <= 0:
            break
    if remain > 0 or qty <= 0:
        return None
    return ((spend / qty) / quote.ask - 1) * Decimal("10000")


def evaluate_live_match(
    inputs: MatchInputs,
    *,
    now: datetime | None = None,
    config: CandidateConfig | None = None,
) -> list[dict[str, object]]:
    """Return candidate/rejection telemetry only; this function cannot place orders."""
    now, config = now or datetime.now(UTC), config or CandidateConfig()
    global_reasons: list[str] = []
    gates = {
        "three_way_moneyline": all(key in inputs.markets for key in OUTCOMES),
        "event_volume": inputs.event_volume_verified
        and inputs.event_volume_usd is not None
        and inputs.event_volume_usd >= Decimal("1000000"),
        "first_half_clock": _first_half(inputs.status) and inputs.minute is not None and inputs.minute <= 45,
        "verified_stats_mapping": inputs.stats_mapped_and_verified,
        "score_consistent": inputs.score_consistent is True,
    }
    if not gates["three_way_moneyline"]:
        global_reasons.append("A distinct HOME/DRAW/AWAY moneyline is incomplete.")
    if not gates["event_volume"]:
        global_reasons.append("Verified Jupiter event volume is missing or below $1,000,000.")
    if not gates["first_half_clock"]:
        global_reasons.append("Match is not confirmed in the first half at minute 45 or earlier.")
    if not gates["verified_stats_mapping"]:
        global_reasons.append("LiveScore MCP statistics lack a verified event mapping.")
    if not gates["score_consistent"]:
        global_reasons.append("Jupiter and LiveScore MCP scores are not both fresh and consistent.")

    fresh = _age_ok(inputs.event_observed_at, now, config.max_data_age_seconds)
    fresh &= _age_ok(inputs.score_observed_at, now, config.max_data_age_seconds)
    fresh &= _age_ok(inputs.score_updated_at, now, config.max_data_age_seconds)
    fresh &= _age_ok(inputs.stats_observed_at, now, config.max_data_age_seconds)
    valid_quotes = gates["three_way_moneyline"]
    if gates["three_way_moneyline"]:
        for outcome in OUTCOMES:
            quote = inputs.markets[outcome]
            fresh &= _age_ok(quote.observed_at, now, config.max_data_age_seconds)
            if quote.bid is None or quote.ask is None or not (Decimal("0") < quote.bid <= quote.ask <= Decimal("1")):
                valid_quotes = False
                global_reasons.append(outcome + " bid/ask is missing, malformed, or contradictory.")
    if not fresh:
        global_reasons.append("One or more provider observations are missing, stale, or future-dated.")
    gates["fresh_data"] = bool(fresh)
    gates["valid_quotes"] = bool(valid_quotes)
    if not valid_quotes and not any("bid/ask" in reason for reason in global_reasons):
        global_reasons.append("Valid executable quotes for all three outcomes are required.")

    score_known = inputs.home_score is not None and inputs.away_score is not None
    trailing: list[str] = []
    if score_known and inputs.home_score < inputs.away_score:
        trailing.append("HOME")
    if score_known and inputs.away_score < inputs.home_score:
        trailing.append("AWAY")
    evaluations: list[tuple[str, str, bool, list[str]]] = []
    for outcome in ("HOME", "AWAY"):
        shots = inputs.home_shots if outcome == "HOME" else inputs.away_shots
        possession = inputs.home_possession if outcome == "HOME" else inputs.away_possession
        corners = inputs.home_corners if outcome == "HOME" else inputs.away_corners
        quote = inputs.markets.get(outcome)
        attack = (
            (shots is not None and shots >= 4)
            or (possession is not None and possession >= Decimal("50"))
            or (corners is not None and corners >= config.corner_threshold)
        )
        underdog_limit = (
            config.underdog_max_ask
            if inputs.prematch_favorite_probability is not None
            and inputs.prematch_favorite_probability >= config.underdog_favorite_boundary
            else Decimal("0.25")
        )
        triggered = bool(
            outcome in trailing and quote and quote.ask is not None
            and quote.ask <= underdog_limit and attack
        )
        reason = [] if triggered else [
            f"Requires a trailing team, executable ask ≤ ${underdog_limit}, and shots/possession/corners confirmation."
        ]
        evaluations.append(("UNDERDOG_SCOUTER", outcome, triggered, reason))

    shots_total = (
        inputs.home_shots + inputs.away_shots
        if inputs.home_shots is not None and inputs.away_shots is not None
        else None
    )
    draw = inputs.markets.get("DRAW")
    draw_inflated = bool(
        inputs.home_score == 0 and inputs.away_score == 0
        and inputs.minute is not None and 25 <= inputs.minute <= 40
        and _first_half(inputs.status)
        and draw and draw.ask is not None and draw.ask >= Decimal("0.30")
    )
    draw_triggered = bool(
        draw and draw.ask is not None and draw.ask <= Decimal("0.15")
        and inputs.home_score == 0 and inputs.away_score == 0
        and inputs.minute is not None and 25 <= inputs.minute <= 40
        and _first_half(inputs.status) and shots_total is not None and shots_total <= 3
    )
    draw_reasons = (
        ["HARD WARNING: Draw contract is inflated at 30¢ or higher; no-trade boundary rejected."]
        if draw_inflated else
        [] if draw_triggered else ["Requires 0–0, minutes 25–40, ≤3 combined shots, and draw ask ≤ $0.15."]
    )
    evaluations.append((
        "DRAW_COMPRESSION", "DRAW", draw_triggered,
        draw_reasons,
    ))

    favorite = inputs.prematch_favorite if inputs.prematch_favorite in {"HOME", "AWAY"} else None
    favorite_quote = inputs.markets.get(favorite) if favorite else None
    favorite_trailing = favorite in trailing
    possession = inputs.home_possession if favorite == "HOME" else inputs.away_possession
    corners = inputs.home_corners if favorite == "HOME" else inputs.away_corners
    favorite_triggered = bool(
        favorite and favorite_quote and favorite_quote.ask is not None
        and inputs.prematch_favorite_probability is not None
        and inputs.prematch_favorite_probability >= Decimal("0.80")
        and inputs.prematch_source and _age_ok(inputs.prematch_observed_at, now, config.prematch_max_age_seconds)
        and favorite_trailing and _first_half(inputs.status) and inputs.minute is not None
        and inputs.minute <= 20 and Decimal("0.50") <= favorite_quote.ask <= Decimal("0.68")
        and ((possession is not None and possession >= Decimal("68"))
             or (corners is not None and corners >= config.corner_threshold))
    )
    evaluations.append((
        "HEAVY_FAVORITE_REBOUND", favorite or "HOME", favorite_triggered,
        [] if favorite_triggered else ["Requires a fresh sourced pre-match favorite ≥ $0.80, trailing before minute 20, current ask $0.50–$0.68, and attacking confirmation."],
    ))

    results: list[dict[str, object]] = []
    for strategy, outcome, triggered, reasons in evaluations:
        quote = inputs.markets.get(outcome)
        local_reasons = list(reasons)
        local_gates = dict(gates)
        if triggered and quote:
            if quote.ask_depth_usd is None or quote.ask_depth_usd < config.min_order_value_usd:
                local_gates["target_depth"] = False
                local_reasons.append("Executable ask depth is below the provisional $5 minimum.")
            else:
                local_gates["target_depth"] = True
            slippage = _slippage_bps(quote, config.min_order_value_usd)
            if slippage is None or slippage > config.max_slippage_bps:
                local_gates["slippage"] = False
                local_reasons.append("Slippage cannot be estimated for $5 or exceeds 50 bps.")
            else:
                local_gates["slippage"] = True
        if triggered:
            local_reasons.extend(global_reasons)
        candidate = triggered and not local_reasons
        results.append({
            "strategy_name": strategy,
            "strategy_version": "1.0",
            "outcome": outcome,
            "market_id": quote.market_id if quote else None,
            "status": "candidate" if candidate else "rejected" if triggered or (strategy == "DRAW_COMPRESSION" and draw_inflated) else "no_trigger",
            "triggered": triggered,
            "evaluated_at": now.astimezone(UTC).isoformat(),
            "ask": str(quote.ask) if quote and quote.ask is not None else None,
            "gate_results": local_gates,
            "reasons": list(dict.fromkeys(local_reasons)),
            "hard_warning": strategy == "DRAW_COMPRESSION" and draw_inflated,
            "configuration_version": "provisional-v2",
        })
    return results
