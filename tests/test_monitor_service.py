from datetime import UTC, datetime
from decimal import Decimal

from integrations.market_data.jupiter import (
    JupiterEvent, JupiterLiveScore, JupiterMarket, JupiterOrderBook, OrderBookLevel,
)
from monitoring.service import LiveMonitor, _classify_moneyline, orderbook_view


def _market(market_id, title, team):
    return JupiterMarket(
        market_id=market_id, title=title, status="open", provider="polymarket",
        buy_yes_usd=Decimal("0.5"), sell_yes_usd=Decimal("0.49"),
        buy_no_usd=Decimal("0.5"), sell_no_usd=Decimal("0.49"),
        volume_usd=Decimal("10000"), sports_market_type="moneyline",
        period_type="regular", sports_line=None, team_name=team,
        team_abbreviation=None, team_color=None, team_image_url=None,
        market_options=("Yes", "No"),
    )


def _event(markets=None):
    return JupiterEvent(
        event_id="j-event", title="Home FC vs Away FC", category="sports",
        subcategory="soccer", scheduled_start_at=datetime.now(UTC),
        is_live=True, reported_volume_usd=Decimal("1200000"),
        markets=tuple(markets or (
            _market("home", "Home FC", "Home FC"),
            _market("draw", "Draw", None),
            _market("away", "Away FC", "Away FC"),
        )),
    )


def _score():
    return JupiterLiveScore(
        event_id="j-event", league_abbreviation="EPL", home_team="Home FC",
        away_team="Away FC", score="0-0", period="1H", elapsed="30",
        status="InProgress", updated_at=datetime.now(UTC).isoformat(),
    )


def test_orderbook_view_uses_complement_bids_and_sums_buy_depth():
    now = datetime.now(UTC)
    book = JupiterOrderBook(
        market_id="m-home",
        yes_bids=(OrderBookLevel(Decimal("0.60"), Decimal("4")),),
        no_bids=(
            OrderBookLevel(Decimal("0.20"), Decimal("5")),
            OrderBookLevel(Decimal("0.30"), Decimal("10")),
        ),
        fetched_at=now,
    )

    view = orderbook_view(book)

    assert view["yes_bid"] == "0.60"
    assert view["yes_ask"] == "0.70"
    assert view["yes_ask_depth_usd"] == "11.00"
    assert view["no_ask"] == "0.40"
    assert view["no_ask_depth_usd"] == "1.60"


def test_moneyline_classifier_requires_three_distinct_outcomes():
    event = _event()
    score = _score()

    assigned, reasons = _classify_moneyline(event, score)

    assert set(assigned) == {"HOME", "DRAW", "AWAY"}
    assert reasons == []

    incomplete = _event(markets=event.markets[:2])
    assigned, reasons = _classify_moneyline(incomplete, score)
    assert set(assigned) == {"HOME", "DRAW"}
    assert reasons == ["Missing moneyline outcome: AWAY."]


def test_monitor_log_is_a_fixed_size_ring_buffer(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "")
    monitor = LiveMonitor(poll_seconds=15)
    for index in range(125):
        monitor._log("info", f"message {index}")

    snapshot = monitor.snapshot()

    assert len(snapshot["logs"]) == 100
    assert snapshot["logs"][0]["message"] == "message 124"
    assert snapshot["execution"] == "disabled"


def test_live_score_provider_is_on_demand_and_not_polled_during_initialization():
    class FakeStatsClient:
        calls = 0

        def get_match_statistics(self, **kwargs):
            self.calls += 1
            raise AssertionError("LiveScore MCP must be called only by the explicit refresh action.")

    fake = FakeStatsClient()
    monitor = LiveMonitor(livescore_mcp=fake)
    assert monitor.snapshot()["livescore_mcp"]["status"] == "on_demand"
    assert fake.calls == 0
