from datetime import UTC
from decimal import Decimal

import pytest

from integrations.market_data.jupiter import JupiterDataError, JupiterPredictionClient
from integrations.sports_data.api_football import (
    ApiFootballClient,
    SportsProviderNotConfigured,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 400

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.call = None

    def get(self, url, **kwargs):
        self.call = (url, kwargs)
        return self.response


def test_jupiter_list_is_read_only_and_converts_micro_usd():
    session = FakeSession(
        FakeResponse(
            {
                "data": [
                    {
                        "eventId": "event-1",
                        "category": "sports",
                        "volumeUsd": "1250000.50",
                        "metadata": {"title": "Home vs Away", "isLive": True},
                        "markets": [
                            {
                                "marketId": "market-1",
                                "title": "Home wins",
                                "status": "open",
                                "provider": "polymarket",
                                "sportsMarketType": "moneyline",
                                "team": {
                                    "name": "Home",
                                    "abbreviation": "hom",
                                    "color": "#123456",
                                    "imageUrl": "https://images.example/home.png",
                                },
                                "marketOptions": [{"label": "Yes", "buyYes": True}, {"label": "No", "buyYes": False}],
                                "pricing": {
                                    "buyYesPriceUsd": 650000,
                                    "sellYesPriceUsd": 620000,
                                    "buyNoPriceUsd": 380000,
                                    "sellNoPriceUsd": 350000,
                                    "volume": 282173,
                                },
                            }
                        ],
                    }
                ]
            }
        )
    )
    page = JupiterPredictionClient(session=session).list_sports_events(filter_name="live")

    assert page.events[0].title == "Home vs Away"
    assert page.events[0].reported_volume_usd == Decimal("1250000.50")
    assert page.events[0].markets[0].buy_yes_usd == Decimal("0.65")
    assert page.events[0].markets[0].sell_yes_usd == Decimal("0.62")
    assert page.events[0].markets[0].volume_usd == Decimal("282173")
    assert page.events[0].markets[0].sports_market_type == "moneyline"
    assert page.events[0].markets[0].team_abbreviation == "hom"
    assert page.events[0].markets[0].team_image_url == "https://images.example/home.png"
    assert page.events[0].markets[0].market_options == ("Yes", "No")
    assert page.fetched_at.tzinfo == UTC
    url, kwargs = session.call
    assert url.endswith("/events")
    assert kwargs["params"]["category"] == "sports"
    assert kwargs["params"]["includeMarkets"] == "false"
    assert kwargs["headers"] == {}
    assert kwargs["timeout"] > 0


def test_jupiter_soccer_tag_filter_and_live_scores():
    class MultiResponseSession:
        def __init__(self):
            self.calls = []
            self.responses = iter(
                [
                    FakeResponse(
                        {
                            "data": [
                                {
                                    "eventId": "soccer-1",
                                    "category": "sports",
                                    "metadata": {"title": "Home vs Away"},
                                }
                            ]
                        }
                    ),
                    FakeResponse(
                        {
                            "data": [
                                {
                                    "eventId": "soccer-1",
                                    "leagueAbbreviation": "EPL",
                                    "homeTeam": "Home",
                                    "awayTeam": "Away",
                                    "score": "2-1",
                                    "period": "2H",
                                    "elapsed": "67",
                                    "status": "InProgress",
                                    "updatedAt": "2026-10-31T17:00:00Z",
                                }
                            ]
                        }
                    ),
                ]
            )

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return next(self.responses)

    session = MultiResponseSession()
    client = JupiterPredictionClient(api_key="test-key", session=session)
    events = client.list_sports_events(tag="soccer", filter_name="live", limit=50)
    scores = client.get_live_scores([event.event_id for event in events.events])

    assert len(events.events) == 1
    assert scores[0].score == "2-1"
    assert scores[0].elapsed == "67"
    assert scores[0].league_abbreviation == "EPL"
    assert session.calls[0][1]["params"]["tags"] == "soccer"
    assert session.calls[1][1]["params"] == {"eventIds": "soccer-1"}
    assert all(call[1]["headers"] == {"x-api-key": "test-key"} for call in session.calls)


def test_jupiter_event_markets_are_bounded_and_paginated():
    session = FakeSession(
        FakeResponse(
            {
                "data": [
                    {
                        "marketId": "market-2",
                        "title": "Away wins",
                        "pricing": {"buyYesPriceUsd": 440000},
                    }
                ],
                "pagination": {"start": 20, "end": 40, "total": 615, "hasNext": True},
            }
        )
    )
    page = JupiterPredictionClient(api_key="test-key", session=session).get_sports_event_markets("event / 2", start=20)

    assert page.event_id == "event / 2"
    assert page.markets[0].market_id == "market-2"
    assert page.markets[0].buy_yes_usd == Decimal("0.44")
    assert page.total == 615
    assert page.has_next
    url, kwargs = session.call
    assert url.endswith("/events/event%20%2F%202/markets")
    assert kwargs["params"] == {"start": 20, "end": 40}
    assert kwargs["headers"] == {"x-api-key": "test-key"}


def test_jupiter_event_details_parse_screenshot_market_groups():
    session = FakeSession(
        FakeResponse(
            {
                "eventId": "match-1",
                "metadata": {"title": "Home vs Away"},
                "markets": [
                    {
                        "marketId": "ml-home",
                        "title": "Home",
                        "sportsMarketType": "moneyline",
                        "team": {"name": "Home", "abbreviation": "hom"},
                        "pricing": {"buyYesPriceUsd": 730000, "buyNoPriceUsd": 280000, "volume": 282173},
                    },
                    {
                        "marketId": "first-neither",
                        "title": "Neither",
                        "sportsMarketType": "soccer_first_to_score",
                        "pricing": {"buyYesPriceUsd": 799000},
                    },
                    {
                        "marketId": "btts",
                        "title": "Both Teams to Score",
                        "sportsMarketType": "both_teams_to_score",
                        "pricing": {"buyYesPriceUsd": 600000, "buyNoPriceUsd": 420000},
                    },
                ],
            }
        )
    )
    event = JupiterPredictionClient(api_key="test-key", session=session).get_sports_event_details("match-1")

    assert event.event_id == "match-1"
    assert [market.sports_market_type for market in event.markets] == [
        "moneyline",
        "soccer_first_to_score",
        "both_teams_to_score",
    ]
    assert event.markets[0].volume_usd == Decimal("282173")
    assert event.markets[1].buy_yes_usd == Decimal("0.799")
    assert event.markets[2].buy_no_usd == Decimal("0.42")
    assert session.call[0].endswith("/events/match-1")


def test_jupiter_errors_do_not_expose_response_body():
    session = FakeSession(FakeResponse({"message": "private response detail"}, status_code=401))
    with pytest.raises(JupiterDataError) as error:
        JupiterPredictionClient(api_key="synthetic-key", session=session).list_sports_events()
    assert "private response detail" not in str(error.value)
    assert "synthetic-key" not in str(error.value)


def test_api_football_requires_key_before_network_call():
    session = FakeSession(FakeResponse({"response": []}))
    with pytest.raises(SportsProviderNotConfigured):
        ApiFootballClient(session=session).get_live_fixtures()
    assert session.call is None


def test_api_football_parses_live_fixtures_and_nullable_statistics():
    live_session = FakeSession(
        FakeResponse(
            {
                "response": [
                    {
                        "fixture": {"id": 77, "status": {"short": "1H", "elapsed": 31}},
                        "league": {"name": "League"},
                        "teams": {"home": {"name": "Home"}, "away": {"name": "Away"}},
                        "goals": {"home": 0, "away": 1},
                    }
                ]
            }
        )
    )
    fixture_client = ApiFootballClient(api_key="test-key", session=live_session, minimum_request_interval_seconds=0)
    fixtures = fixture_client.get_live_fixtures()
    assert fixtures[0].fixture_id == 77
    assert fixtures[0].elapsed_minute == 31
    assert fixtures[0].home_score == 0

    stats_session = FakeSession(
        FakeResponse(
            {
                "response": [
                    {
                        "team": {"id": 1, "name": "Home"},
                        "statistics": [
                            {"type": "Total Shots", "value": 8},
                            {"type": "Ball Possession", "value": "55%"},
                            {"type": "Corner Kicks", "value": 3},
                        ],
                    },
                    {
                        "team": {"id": 2, "name": "Away"},
                        "statistics": [
                            {"type": "Total Shots", "value": None},
                            {"type": "Ball Possession", "value": None},
                            {"type": "Corner Kicks", "value": 1},
                        ],
                    },
                ]
            }
        )
    )
    stats = ApiFootballClient(
        api_key="test-key", session=stats_session, minimum_request_interval_seconds=0
    ).get_fixture_statistics(77)
    assert stats.teams[0].shots_total == 8
    assert stats.teams[0].possession_percent == 55.0
    assert stats.teams[0].corners == 3
    assert stats.teams[1].shots_total is None
    assert stats.teams[1].possession_percent is None


def test_read_only_provider_get_retries_transient_server_error(monkeypatch):
    from integrations.http import read_only_get

    class RetrySession:
        def __init__(self):
            self.statuses = iter([503, 200])
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            return FakeResponse({}, status_code=next(self.statuses))

    session = RetrySession()
    sleeps = []
    monkeypatch.setattr("integrations.http.time.sleep", sleeps.append)
    monkeypatch.setattr("integrations.http.random.uniform", lambda start, end: 0.25)
    response = read_only_get(
        session,
        "https://provider.invalid/read-only",
        headers={},
        params={},
        timeout_seconds=1,
        provider_name="Test provider",
    )

    assert response.status_code == 200
    assert session.calls == 2
    assert sleeps == [2.25]
