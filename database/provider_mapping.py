"""Explicit, auditable provider-event mapping operations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Event, EventProviderReference, MatchSnapshot
from integrations.market_data.jupiter import JupiterLiveScore
from integrations.sports_data.api_football import FixtureStatistics, LiveFixture
from integrations.sports_data.livescore_mcp import MatchStatistics, same_team_name


def _team_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def save_fixture_candidate(
    session: Session,
    *,
    jupiter_event_id: str,
    fixture: LiveFixture,
) -> EventProviderReference:
    event = session.scalar(
        select(Event).where(Event.provider == "jupiter", Event.provider_event_id == jupiter_event_id)
    )
    if event is None:
        raise ValueError("Monitor the Jupiter event first so it has a canonical database record.")
    external_id = str(fixture.fixture_id)
    reference = session.scalar(
        select(EventProviderReference).where(
            EventProviderReference.provider == "api_football",
            EventProviderReference.provider_event_id == external_id,
        )
    )
    now = datetime.now(UTC)
    if reference is None:
        reference = EventProviderReference(
            event_id=event.id,
            provider="api_football",
            provider_event_id=external_id,
            provider_event_name=f"{fixture.home_team} vs {fixture.away_team}",
            scheduled_start_at=fixture.scheduled_start_at,
            mapping_status="unverified",
            mapping_method=None,
            verified_at=None,
            created_at=now,
        )
        session.add(reference)
    elif reference.mapping_status == "verified" and reference.event_id != event.id:
        raise ValueError("This API-Football fixture is already verified against another event.")
    else:
        reference.event_id = event.id
        reference.provider_event_name = f"{fixture.home_team} vs {fixture.away_team}"
        reference.scheduled_start_at = fixture.scheduled_start_at
        reference.mapping_status = "unverified"
        reference.mapping_method = None
        reference.verified_at = None
    session.flush()
    return reference


def verify_fixture_candidate(
    session: Session,
    *,
    jupiter_event_id: str,
    score: JupiterLiveScore,
    fixture: LiveFixture,
) -> EventProviderReference:
    event = session.scalar(
        select(Event).where(Event.provider == "jupiter", Event.provider_event_id == jupiter_event_id)
    )
    reference = session.scalar(
        select(EventProviderReference).where(
            EventProviderReference.provider == "api_football",
            EventProviderReference.provider_event_id == str(fixture.fixture_id),
        )
    )
    if event is None or reference is None or reference.event_id != event.id:
        raise ValueError("Save this fixture as an unverified candidate before verifying it.")
    if reference.mapping_status == "rejected":
        raise ValueError("This fixture candidate was rejected; save it again before review.")
    if _team_key(score.home_team) != _team_key(fixture.home_team):
        raise ValueError("Home team names differ. The mapping remains unverified for manual review.")
    if _team_key(score.away_team) != _team_key(fixture.away_team):
        raise ValueError("Away team names differ. The mapping remains unverified for manual review.")
    kickoff = event.provider_references
    jupiter_ref = next(
        (item for item in kickoff if item.provider == "jupiter" and item.provider_event_id == jupiter_event_id),
        None,
    )
    jupiter_start = jupiter_ref.scheduled_start_at if jupiter_ref else None
    if jupiter_start is None or fixture.scheduled_start_at is None:
        raise ValueError("Both providers must supply a kickoff timestamp before the mapping can be verified.")
    left = jupiter_start if jupiter_start.tzinfo else jupiter_start.replace(tzinfo=UTC)
    right = fixture.scheduled_start_at if fixture.scheduled_start_at.tzinfo else fixture.scheduled_start_at.replace(tzinfo=UTC)
    if abs((left - right).total_seconds()) > 30 * 60:
        raise ValueError("Provider kickoff times differ by more than 30 minutes; the mapping remains unverified.")
    reference.mapping_status = "verified"
    reference.mapping_method = "operator_exact_teams_kickoff"
    reference.verified_at = datetime.now(UTC)
    session.flush()
    return reference


def fixture_mapping_status(session: Session, jupiter_event_id: str) -> dict[str, object]:
    event = session.scalar(
        select(Event).where(Event.provider == "jupiter", Event.provider_event_id == jupiter_event_id)
    )
    if event is None:
        return {"status": "unmapped", "fixture_id": None, "name": None, "verified_at": None}
    references = session.scalars(
        select(EventProviderReference).where(
            EventProviderReference.event_id == event.id,
            EventProviderReference.provider == "api_football",
        )
    ).all()
    reference = next((item for item in references if item.mapping_status == "verified"), None)
    reference = reference or (references[0] if references else None)
    if reference is None:
        return {"status": "unmapped", "fixture_id": None, "name": None, "verified_at": None}
    return {
        "status": reference.mapping_status,
        "fixture_id": reference.provider_event_id,
        "name": reference.provider_event_name,
        "verified_at": reference.verified_at.isoformat() if reference.verified_at else None,
    }


def record_api_football_statistics(
    session: Session,
    *,
    jupiter_event_id: str,
    fixture: LiveFixture,
    statistics: FixtureStatistics,
) -> bool:
    event = session.scalar(
        select(Event).where(Event.provider == "jupiter", Event.provider_event_id == jupiter_event_id)
    )
    reference = session.scalar(
        select(EventProviderReference).where(
            EventProviderReference.provider == "api_football",
            EventProviderReference.provider_event_id == str(fixture.fixture_id),
        )
    )
    if event is None or reference is None or reference.event_id != event.id or reference.mapping_status != "verified":
        return False
    by_team = {_team_key(team.team_name): team for team in statistics.teams}
    home = by_team.get(_team_key(fixture.home_team))
    away = by_team.get(_team_key(fixture.away_team))
    if home is None or away is None:
        return False
    session.add(
        MatchSnapshot(
            event_id=event.id,
            observed_at=statistics.received_at,
            status=fixture.status,
            minute=fixture.elapsed_minute,
            home_score=fixture.home_score,
            away_score=fixture.away_score,
            home_shots=home.shots_total,
            away_shots=away.shots_total,
            home_possession=Decimal(str(home.possession_percent)) if home.possession_percent is not None else None,
            away_possession=Decimal(str(away.possession_percent)) if away.possession_percent is not None else None,
            home_corners=home.corners,
            away_corners=away.corners,
            source="api_football",
            provider_event_id=str(fixture.fixture_id),
        )
    )
    return True


def record_livescore_mcp_statistics(
    session: Session,
    *,
    jupiter_event_id: str,
    score: JupiterLiveScore,
    statistics: MatchStatistics,
) -> bool:
    """Persist stats only after unique live team pairing has been confirmed by the adapter."""
    provider_score = _score_pair(statistics.score)
    if (
        not same_team_name(score.home_team, statistics.home_team)
        or not same_team_name(score.away_team, statistics.away_team)
        or not statistics.has_statistics
    ):
        return False
    event = session.scalar(
        select(Event).where(Event.provider == "jupiter", Event.provider_event_id == jupiter_event_id)
    )
    if event is None:
        return False
    provider_id = str(statistics.match_id)
    reference = session.scalar(
        select(EventProviderReference).where(
            EventProviderReference.provider == "livescore_mcp",
            EventProviderReference.provider_event_id == provider_id,
        )
    )
    if reference is not None and reference.event_id != event.id:
        return False
    now = datetime.now(UTC)
    if reference is None:
        reference = EventProviderReference(
            event_id=event.id,
            provider="livescore_mcp",
            provider_event_id=provider_id,
            provider_event_name=f"{statistics.home_team} vs {statistics.away_team}",
            scheduled_start_at=None,
            mapping_status="verified",
            mapping_method="unique_live_team_pair",
            verified_at=now,
            created_at=now,
        )
        session.add(reference)
    else:
        reference.mapping_status = "verified"
        reference.mapping_method = "unique_live_team_pair"
        reference.verified_at = now
        reference.provider_event_name = f"{statistics.home_team} vs {statistics.away_team}"
    session.add(
        MatchSnapshot(
            event_id=event.id,
            observed_at=statistics.received_at,
            status=(statistics.status or "LIVE")[:30],
            minute=statistics.minute,
            home_score=provider_score[0] if provider_score else None,
            away_score=provider_score[1] if provider_score else None,
            home_shots=statistics.home_shots,
            away_shots=statistics.away_shots,
            home_shots_on_target=statistics.home_shots_on_target,
            away_shots_on_target=statistics.away_shots_on_target,
            home_possession=(Decimal(str(statistics.home_possession))
                             if statistics.home_possession is not None else None),
            away_possession=(Decimal(str(statistics.away_possession))
                             if statistics.away_possession is not None else None),
            home_passes=statistics.home_passes,
            away_passes=statistics.away_passes,
            home_pass_accuracy=(Decimal(str(statistics.home_pass_accuracy))
                                if statistics.home_pass_accuracy is not None else None),
            away_pass_accuracy=(Decimal(str(statistics.away_pass_accuracy))
                                if statistics.away_pass_accuracy is not None else None),
            home_fouls=statistics.home_fouls,
            away_fouls=statistics.away_fouls,
            home_yellow_cards=statistics.home_yellow_cards,
            away_yellow_cards=statistics.away_yellow_cards,
            home_red_cards=statistics.home_red_cards,
            away_red_cards=statistics.away_red_cards,
            home_offsides=statistics.home_offsides,
            away_offsides=statistics.away_offsides,
            home_corners=statistics.home_corners,
            away_corners=statistics.away_corners,
            source="livescore_mcp",
            provider_event_id=provider_id,
        )
    )
    session.flush()
    return True


def livescore_mcp_mapping_status(session: Session, jupiter_event_id: str) -> dict[str, object]:
    event = session.scalar(
        select(Event).where(Event.provider == "jupiter", Event.provider_event_id == jupiter_event_id)
    )
    if event is None:
        return {"status": "unmapped", "fixture_id": None, "name": None, "verified_at": None}
    reference = session.scalar(
        select(EventProviderReference).where(
            EventProviderReference.event_id == event.id,
            EventProviderReference.provider == "livescore_mcp",
            EventProviderReference.mapping_status == "verified",
        )
    )
    if reference is None:
        return {"status": "unmapped", "fixture_id": None, "name": None, "verified_at": None}
    return {
        "status": reference.mapping_status,
        "fixture_id": reference.provider_event_id,
        "name": reference.provider_event_name,
        "verified_at": reference.verified_at.isoformat() if reference.verified_at else None,
    }


def _score_pair(value: str | None) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", value or "")
    return (int(match.group(1)), int(match.group(2))) if match else None
