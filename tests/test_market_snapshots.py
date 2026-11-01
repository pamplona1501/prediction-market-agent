from datetime import UTC, datetime, timedelta
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database.models import Base, EventProviderReference, Market, MarketSnapshot, MatchSnapshot
from database.provider_mapping import (
    record_api_football_statistics, record_livescore_mcp_statistics, livescore_mcp_mapping_status,
    save_fixture_candidate, verify_fixture_candidate,
)
from database.snapshots import read_prematch_yes_prices, record_jupiter_market_snapshots
from integrations.market_data.jupiter import JupiterEvent, JupiterLiveScore, JupiterMarket
from integrations.sports_data.api_football import FixtureStatistics, LiveFixture, TeamStatistics
from integrations.sports_data.livescore_mcp import MatchStatistics


def _event():
    market = JupiterMarket(
        market_id="market-1",
        title="Home wins",
        status="open",
        provider="jupiter",
        buy_yes_usd=Decimal("0.65"),
        sell_yes_usd=Decimal("0.62"),
        buy_no_usd=Decimal("0.38"),
        sell_no_usd=Decimal("0.35"),
        volume_usd=Decimal("282173"),
        sports_market_type="moneyline",
        period_type="regular",
        sports_line=None,
        team_name="Home",
        team_abbreviation="HOM",
        team_color=None,
        team_image_url=None,
        market_options=("Yes", "No"),
    )
    return JupiterEvent(
        event_id="event-1",
        title="Home vs Away",
        category="sports",
        subcategory="soccer",
        scheduled_start_at=datetime(2026, 11, 1, 18, 30, tzinfo=UTC),
        is_live=True,
        reported_volume_usd=Decimal("1250000.50"),
        markets=(market,),
    )


def test_selected_jupiter_event_appends_two_sourced_snapshots_without_duplicate_entities():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    observed_at = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
    event = _event()

    with Session(engine) as session:
        with session.begin():
            assert record_jupiter_market_snapshots(session, event, observed_at=observed_at) == 2
        with session.begin():
            assert record_jupiter_market_snapshots(session, event, observed_at=observed_at) == 2

        snapshots = session.scalars(select(MarketSnapshot).order_by(MarketSnapshot.outcome_key)).all()
        markets = session.scalars(select(Market)).all()
        references = session.scalars(select(EventProviderReference)).all()

    assert len(snapshots) == 4
    assert len(markets) == 1
    assert len(references) == 1
    assert {snapshot.outcome_key for snapshot in snapshots} == {"YES", "NO"}
    yes = next(snapshot for snapshot in snapshots if snapshot.outcome_key == "YES")
    assert yes.bid == Decimal("0.62000000")
    assert yes.ask == Decimal("0.65000000")
    assert yes.event_volume_usd == Decimal("1250000.5000")
    assert yes.market_volume_usd == Decimal("282173.0000")
    assert yes.executable_depth_usd is None
    assert yes.source == "jupiter_prediction_api"
    assert yes.payload_note is None
    assert references[0].mapping_status == "verified"
    assert references[0].mapping_method == "primary_provider_id"


def test_fixture_mapping_requires_explicit_candidate_then_exact_teams_and_kickoff():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
    event = _event()
    fixture = LiveFixture(
        fixture_id=77,
        league="League",
        home_team="Home",
        away_team="Away",
        scheduled_start_at=event.scheduled_start_at,
        status="1H",
        elapsed_minute=30,
        home_score=0,
        away_score=0,
        received_at=now,
    )
    score = JupiterLiveScore(
        event_id=event.event_id,
        league_abbreviation="LGE",
        home_team="Home",
        away_team="Away",
        score="0-0",
        period="1H",
        elapsed="30",
        status="InProgress",
        updated_at=now.isoformat(),
    )
    stats = FixtureStatistics(
        fixture_id=77,
        teams=(
            TeamStatistics(1, "Home", 8, 55.0, 3),
            TeamStatistics(2, "Away", 2, 45.0, 1),
        ),
        received_at=now,
    )

    with Session(engine) as session, session.begin():
        record_jupiter_market_snapshots(session, event, observed_at=now)
        reference = save_fixture_candidate(session, jupiter_event_id=event.event_id, fixture=fixture)
        assert reference.mapping_status == "unverified"
    with Session(engine) as session, session.begin():
        reference = verify_fixture_candidate(
            session,
            jupiter_event_id=event.event_id,
            score=score,
            fixture=fixture,
        )
        assert reference.mapping_status == "verified"
        assert record_api_football_statistics(
            session,
            jupiter_event_id=event.event_id,
            fixture=fixture,
            statistics=stats,
        )
    with Session(engine) as session:
        snapshot = session.scalar(select(MatchSnapshot).where(MatchSnapshot.source == "api_football"))
    assert snapshot.home_shots == 8
    assert snapshot.away_corners == 1


def test_prematch_price_reader_returns_last_yes_ask_captured_before_kickoff():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    event = _event()
    observed_at = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        record_jupiter_market_snapshots(
            session,
            event,
            observed_at=observed_at,
            snapshot_phase="prematch",
        )
    with Session(engine) as session:
        baseline = read_prematch_yes_prices(
            session,
            event_provider_id=event.event_id,
            market_provider_ids=[event.markets[0].market_id],
            scheduled_start_at=event.scheduled_start_at,
        )
    assert baseline[event.markets[0].market_id][0] == Decimal("0.65000000")


def test_livescore_mcp_snapshots_save_team_mapping_and_keep_provider_score():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    observed_at = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)
    event = _event()
    score = JupiterLiveScore(
        event_id=event.event_id,
        league_abbreviation="LGE",
        home_team="Home",
        away_team="Away",
        score="1-0",
        period="1H",
        elapsed="30",
        status="InProgress",
        updated_at=observed_at.isoformat(),
    )
    stats = MatchStatistics(
        match_id="mcp-123",
        home_team="Home",
        away_team="Away",
        score="1-0",
        score_consistent=True,
        status="1H",
        minute=30,
        home_shots=8,
        away_shots=2,
        home_shots_on_target=3,
        away_shots_on_target=0,
        home_possession=55.0,
        away_possession=45.0,
        home_passes=400,
        away_passes=300,
        home_pass_accuracy=90.0,
        away_pass_accuracy=80.0,
        home_fouls=7,
        away_fouls=11,
        home_yellow_cards=1,
        away_yellow_cards=2,
        home_red_cards=0,
        away_red_cards=0,
        home_offsides=2,
        away_offsides=1,
        home_corners=3,
        away_corners=1,
        received_at=observed_at,
    )
    with Session(engine) as session, session.begin():
        record_jupiter_market_snapshots(session, event, observed_at=observed_at)
        assert record_livescore_mcp_statistics(
            session, jupiter_event_id=event.event_id, score=score, statistics=stats,
        )
    with Session(engine) as session:
        snapshot = session.scalar(select(MatchSnapshot).where(MatchSnapshot.source == "livescore_mcp"))
        mapping = livescore_mcp_mapping_status(session, event.event_id)
    assert snapshot.home_score == 1 and snapshot.away_score == 0
    assert snapshot.home_shots == 8 and snapshot.away_corners == 1
    assert snapshot.home_shots_on_target == 3
    assert snapshot.home_passes == 400 and snapshot.away_pass_accuracy == Decimal("80.000")
    assert snapshot.home_fouls == 7 and snapshot.away_offsides == 1
    assert snapshot.source == "livescore_mcp"
    assert mapping["status"] == "verified" and mapping["fixture_id"] == "mcp-123"

    mismatched = replace(stats, score="2-0", score_consistent=False, received_at=observed_at + timedelta(seconds=1))
    with Session(engine) as session, session.begin():
        assert record_livescore_mcp_statistics(
            session, jupiter_event_id=event.event_id, score=score, statistics=mismatched,
        )
    with Session(engine) as session:
        latest = session.scalar(
            select(MatchSnapshot).where(MatchSnapshot.source == "livescore_mcp").order_by(MatchSnapshot.observed_at.desc())
        )
    assert latest.home_score == 2 and latest.away_score == 0
