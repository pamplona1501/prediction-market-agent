import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from integrations.market_data.jupiter import JUPITER_PRIORITY_RADAR, JupiterEvent, JupiterEventPage, JupiterMarket
from monitoring.service import LiveMonitor


def _market(market_id, title, team, price):
    return JupiterMarket(
        market_id=market_id, title=title, status="open", provider="jupiter",
        buy_yes_usd=Decimal(price), sell_yes_usd=None, buy_no_usd=None,
        sell_no_usd=None, volume_usd=None, sports_market_type="moneyline",
        period_type="regular", sports_line=None, team_name=team,
        team_abbreviation=None, team_color=None, team_image_url=None,
        market_options=("Yes", "No"),
    )


def _event(event_id, start, volume="1200000", favorite="0.78"):
    return JupiterEvent(
        event_id=event_id, title=f"Home {event_id} vs Away", category="sports",
        subcategory="soccer", scheduled_start_at=start, is_live=False,
        reported_volume_usd=Decimal(volume), markets=(
            _market(f"h-{event_id}", "Home", "Home", favorite),
            _market(f"d-{event_id}", "Draw", None, "0.20"),
            _market(f"a-{event_id}", "Away", "Away", "0.22"),
        ),
    )


def test_upcoming_radar_filters_volume_and_keeps_48h_baseline(monkeypatch):
    now = datetime.now(UTC)
    matches = (
        _event("inside", now + timedelta(hours=2)),
        _event("threshold", now + timedelta(hours=4), volume="100000"),
        _event("below-volume", now + timedelta(hours=3), volume="99999"),
        _event("outside", now + timedelta(hours=30)),
        _event("too-late", now + timedelta(hours=49)),
    )
    calls = []

    class FakeJupiter:
        async def alist_sports_events(self, **kwargs):
            calls.append(kwargs)
            return JupiterEventPage(matches, now, "upcoming", kwargs["start"], kwargs["start"] + 50,
                                    total=3, has_next=False)

    persisted = []
    async def fake_to_thread(func, event):
        persisted.append(event.event_id)
        return type("Result", (), {"persisted": True, "snapshots_written": 3})()

    monkeypatch.setattr("monitoring.service.asyncio.to_thread", fake_to_thread)
    monitor = LiveMonitor(jupiter=FakeJupiter())
    asyncio.run(monitor._refresh_upcoming_radar_once())
    state = monitor.snapshot()

    assert [row["event_id"] for row in state["upcoming_matches"]] == [
        "inside", "threshold", "outside", "too-late",
    ]
    row = state["upcoming_matches"][0]
    assert row["strategy_1_may_apply"] is True
    assert row["volume_gate_met_at_observation"] is True
    assert row["favorite_team"] == "Home"
    assert row["draw_price"] == "0.20"
    assert row["volume_delta_usd"] is None
    assert set(persisted) == {"inside", "threshold", "below-volume", "outside"}
    assert state["upcoming_matches"][1]["volume_usd"] == "100000"
    assert state["upcoming_matches"][1]["volume_gate_met_at_observation"] is False
    assert calls[0]["priority"] == JUPITER_PRIORITY_RADAR
    assert calls[0]["sort_by"] == "volume" and calls[0]["sort_direction"] == "desc"
    assert calls[0]["start"] == 0


def test_upcoming_radar_delta_and_stale_last_good(monkeypatch):
    now = datetime.now(UTC)
    value = ["1200000"]

    class FakeJupiter:
        fail = False

        async def alist_sports_events(self, **kwargs):
            if self.fail:
                from integrations.market_data.jupiter import JupiterDataError
                raise JupiterDataError("temporary outage")
            return JupiterEventPage((_event("same", now + timedelta(hours=1), value[0]),), now,
                                    "upcoming", 0, 50, 1, False)

    async def fake_to_thread(func, event):
        return type("Result", (), {"persisted": True, "snapshots_written": 1})()

    monkeypatch.setattr("monitoring.service.asyncio.to_thread", fake_to_thread)
    jupiter = FakeJupiter()
    monitor = LiveMonitor(jupiter=jupiter)
    async def scenario():
        await monitor._refresh_upcoming_radar_once()
        value[0] = "1300000"
        await monitor._refresh_upcoming_radar_once()
        assert monitor.state["upcoming_matches"][0]["volume_delta_usd"] == "100000"
        previous = monitor.state["upcoming_matches"]
        jupiter.fail = True
        await monitor._refresh_upcoming_radar_once()
        assert monitor.state["upcoming_matches"] == previous
        assert monitor.state["upcoming_radar"]["status"] == "stale"
    asyncio.run(scenario())


def test_radar_scans_maximum_two_pages_of_fifty(monkeypatch):
    now = datetime.now(UTC)
    requested = []

    class FakeJupiter:
        async def alist_sports_events(self, **kwargs):
            requested.append(kwargs["start"])
            page_events = tuple(
                JupiterEvent(f"far-{kwargs['start']}-{n}", "Not in radar window", "sports", "soccer",
                             now + timedelta(days=10), False, Decimal("0"), ())
                for n in range(50)
            )
            return JupiterEventPage(page_events, now, "upcoming", kwargs["start"], kwargs["start"] + 50,
                                    total=500, has_next=True)

    monitor = LiveMonitor(jupiter=FakeJupiter())
    asyncio.run(monitor._refresh_upcoming_radar_once())
    assert requested == [0, 50]
    assert monitor.state["upcoming_radar"]["page_cap"] == 100


def test_radar_is_lifecycle_managed_and_runs_separately_from_live_loop(monkeypatch):
    calls = []
    now = datetime.now(UTC)

    class FakeJupiter:
        async def open(self): calls.append("open")
        async def close(self): calls.append("close")
        async def alist_sports_events(self, **kwargs):
            calls.append(kwargs["filter_name"])
            return JupiterEventPage((), now, kwargs["filter_name"], 0, 50, 0, False)
        async def aget_live_scores(self, event_ids): return ()

    class FakeStats:
        async def open(self): pass
        async def close(self): pass

    async def fake_thread(func, *args, **kwargs):
        if func.__name__ == "read_watchlist": return []
        return func(*args, **kwargs)

    monkeypatch.setattr("monitoring.service.asyncio.to_thread", fake_thread)
    monitor = LiveMonitor(jupiter=FakeJupiter(), livescore_mcp=FakeStats(),
                          poll_seconds=15, prematch_refresh_seconds=0.02)

    async def scenario():
        await monitor.start()
        await asyncio.sleep(0.05)
        await monitor.stop()

    asyncio.run(scenario())
    assert "live" in calls and "upcoming" in calls
    assert monitor._task is None and monitor._upcoming_task is None
    assert "open" in calls and "close" in calls


def test_watchlist_flags_propagate_to_upcoming_and_live_rows():
    monitor = LiveMonitor()
    monitor.state = {
        **monitor.state,
        "events": [{"event_id": "pin-me"}],
        "upcoming_matches": [{"event_id": "pin-me"}],
        "watchlist": [{"event_id": "pin-me"}],
    }
    monitor._apply_watchlist_flags()
    assert monitor.state["events"][0]["watched"] is True
    assert monitor.state["upcoming_matches"][0]["watched"] is True


def test_radar_is_lifecycle_managed_and_runs_separately_from_live_loop(monkeypatch):
    calls = []
    now = datetime.now(UTC)

    class FakeJupiter:
        async def open(self): calls.append("open")
        async def close(self): calls.append("close")
        async def alist_sports_events(self, **kwargs):
            calls.append(kwargs["filter_name"])
            return JupiterEventPage((), now, kwargs["filter_name"], 0, 50, 0, False)
        async def aget_live_scores(self, event_ids): return ()

    class FakeStats:
        async def open(self): pass
        async def close(self): pass

    async def fake_thread(func, *args, **kwargs):
        if func.__name__ == "read_watchlist": return []
        return func(*args, **kwargs)

    monkeypatch.setattr("monitoring.service.asyncio.to_thread", fake_thread)
    monitor = LiveMonitor(jupiter=FakeJupiter(), livescore_mcp=FakeStats(),
                          poll_seconds=15, prematch_refresh_seconds=0.02)

    async def scenario():
        await monitor.start()
        await asyncio.sleep(0.05)
        await monitor.stop()

    asyncio.run(scenario())
    assert "live" in calls and "upcoming" in calls
    assert monitor._task is None and monitor._upcoming_task is None
    assert "open" in calls and "close" in calls
