from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Base, Event, EventProviderReference, WatchlistItem
from database import watchlist


def test_watchlist_pin_is_persistent_idempotent_and_removable(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'watchlist.sqlite'}")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(Event(
            id="jupiter:event-1", provider="jupiter", provider_event_id="event-1",
            home_name="Home", away_name="Away", created_at=now,
        ))
        session.add(EventProviderReference(
            event_id="jupiter:event-1", provider="jupiter", provider_event_id="event-1",
            provider_event_name="Home vs Away", scheduled_start_at=now + timedelta(hours=2),
            mapping_status="unverified", created_at=now,
        ))
    monkeypatch.setattr(watchlist, "get_engine", lambda: engine)

    assert watchlist.add_event("event-1") is True
    first = watchlist.read_watchlist()
    assert first[0]["event_id"] == "event-1"
    assert first[0]["title"] == "Home vs Away"
    assert watchlist.add_event("event-1") is False
    assert len(watchlist.read_watchlist()) == 1
    assert watchlist.remove_event("event-1") is True
    assert watchlist.remove_event("event-1") is False
    assert watchlist.read_watchlist() == []
    engine.dispose()
