from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from strategies.live import AskLevel, CandidateConfig, MarketQuote, MatchInputs, evaluate_live_match


def _inputs(now):
    stamp = now
    return MatchInputs(
        event_id="jup-event-1",
        status="1H",
        minute=30,
        home_score=0,
        away_score=0,
        event_volume_usd=Decimal("1250000"),
        event_volume_verified=True,
        event_observed_at=stamp,
        score_observed_at=stamp,
        score_updated_at=stamp,
        stats_mapped_and_verified=True,
        stats_observed_at=stamp,
        home_shots=1,
        away_shots=1,
        home_possession=Decimal("48"),
        away_possession=Decimal("52"),
        home_corners=0,
        away_corners=1,
        score_consistent=True,
        markets={
            "HOME": MarketQuote("m-home", Decimal("0.39"), Decimal("0.40"), Decimal("10"), (AskLevel(Decimal("0.40"), Decimal("100")),), stamp),
            "DRAW": MarketQuote("m-draw", Decimal("0.13"), Decimal("0.14"), Decimal("10"), (AskLevel(Decimal("0.14"), Decimal("100")),), stamp),
            "AWAY": MarketQuote("m-away", Decimal("0.48"), Decimal("0.49"), Decimal("10"), (AskLevel(Decimal("0.49"), Decimal("100")),), stamp),
        },
    )


def test_draw_strategy_emits_only_candidate_telemetry_when_every_shared_gate_passes():
    now = datetime.now(UTC)
    result = evaluate_live_match(_inputs(now), now=now)
    draw = next(item for item in result if item["strategy_name"] == "DRAW_COMPRESSION")

    assert draw["status"] == "candidate"
    assert draw["outcome"] == "DRAW"
    assert draw["gate_results"]["three_way_moneyline"] is True
    assert draw["gate_results"]["slippage"] is True


def test_missing_verified_mapping_fails_closed_even_if_rule_trigger_is_true():
    now = datetime.now(UTC)
    result = evaluate_live_match(
        replace(_inputs(now), stats_mapped_and_verified=False),
        now=now,
    )
    draw = next(item for item in result if item["strategy_name"] == "DRAW_COMPRESSION")

    assert draw["status"] == "rejected"
    assert any("verified event mapping" in reason for reason in draw["reasons"])


def test_stale_quote_and_unknown_clock_prevent_candidate():
    now = datetime.now(UTC)
    data = _inputs(now)
    stale_draw = replace(data.markets["DRAW"], observed_at=now - timedelta(seconds=120))
    stale = replace(data, markets={**data.markets, "DRAW": stale_draw})
    stale_draw_result = next(
        item for item in evaluate_live_match(stale, now=now)
        if item["strategy_name"] == "DRAW_COMPRESSION"
    )
    assert stale_draw_result["status"] == "rejected"
    assert any("stale" in reason for reason in stale_draw_result["reasons"])

    unknown_clock = replace(data, status="UNKNOWN", minute=30)
    clock_result = next(
        item for item in evaluate_live_match(unknown_clock, now=now)
        if item["strategy_name"] == "DRAW_COMPRESSION"
    )
    assert clock_result["status"] == "no_trigger"
    assert clock_result["gate_results"]["first_half_clock"] is False


def test_underdog_strategy_uses_trailing_team_ask_and_attack_confirmation():
    now = datetime.now(UTC)
    data = _inputs(now)
    home_quote = replace(
        data.markets["HOME"],
        bid=Decimal("0.24"),
        ask=Decimal("0.25"),
        asks=(AskLevel(Decimal("0.25"), Decimal("100")),),
    )
    data = replace(
        data,
        home_score=0,
        away_score=1,
        home_shots=4,
        markets={**data.markets, "HOME": home_quote},
    )
    result = next(
        item for item in evaluate_live_match(data, now=now)
        if item["strategy_name"] == "UNDERDOG_SCOUTER" and item["outcome"] == "HOME"
    )
    assert result["status"] == "candidate"


def test_heavy_favorite_strategy_requires_fresh_independent_prematch_baseline():
    now = datetime.now(UTC)
    data = _inputs(now)
    favorite_quote = replace(
        data.markets["HOME"],
        bid=Decimal("0.59"),
        ask=Decimal("0.60"),
        asks=(AskLevel(Decimal("0.60"), Decimal("100")),),
    )
    data = replace(
        data,
        minute=15,
        home_score=0,
        away_score=1,
        home_possession=Decimal("70"),
        prematch_favorite="HOME",
        prematch_favorite_probability=Decimal("0.82"),
        prematch_source="jupiter_upcoming_event",
        prematch_observed_at=now,
        markets={**data.markets, "HOME": favorite_quote},
    )
    candidate = next(
        item for item in evaluate_live_match(data, now=now)
        if item["strategy_name"] == "HEAVY_FAVORITE_REBOUND"
    )
    assert candidate["status"] == "candidate"

    no_baseline = replace(data, prematch_favorite_probability=None, prematch_source=None)
    blocked = next(
        item for item in evaluate_live_match(no_baseline, now=now)
        if item["strategy_name"] == "HEAVY_FAVORITE_REBOUND"
    )
    assert blocked["status"] == "no_trigger"
