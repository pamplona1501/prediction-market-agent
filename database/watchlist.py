"""Database operations for persistent upcoming-event pins."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database.connection import get_engine
from database.models import Event, EventProviderReference, WatchlistItem


def add_event(provider_event_id: str) -> bool:
    """Pin a known Jupiter event. Return False when it was already pinned."""
    try:
        with Session(get_engine()) as session, session.begin():
            event = session.scalar(
                select(Event).where(
                    Event.provider == "jupiter",
                    Event.provider_event_id == provider_event_id,
                )
            )
            if event is None:
                raise ValueError("Refresh the upcoming Jupiter list before pinning this match.")
            existing = session.get(WatchlistItem, event.id)
            if existing:
                return False
            session.add(WatchlistItem(event_id=event.id, pinned_at=datetime.now(UTC)))
        return True
    except ValueError:
        raise
    except IntegrityError:
        # A concurrent pin of the same known event is still a successful idempotent outcome.
        return False
    except (SQLAlchemyError, RuntimeError):
        raise RuntimeError("Watchlist storage is unavailable. Check the database connection and migrations.") from None


def remove_event(provider_event_id: str) -> bool:
    """Unpin a Jupiter event; return False if it was not pinned."""
    try:
        with Session(get_engine()) as session, session.begin():
            event = session.scalar(
                select(Event).where(
                    Event.provider == "jupiter",
                    Event.provider_event_id == provider_event_id,
                )
            )
            if event is None:
                return False
            item = session.get(WatchlistItem, event.id)
            if item is None:
                return False
            session.delete(item)
        return True
    except (SQLAlchemyError, RuntimeError):
        raise RuntimeError("Watchlist storage is unavailable. Check the database connection and migrations.") from None


def read_watchlist() -> list[dict[str, str | None]]:
    """Read pinned event IDs and their last stored title/kickoff metadata."""
    try:
        with Session(get_engine()) as session:
            rows = session.execute(
                select(
                    Event.provider_event_id,
                    EventProviderReference.provider_event_name,
                    EventProviderReference.scheduled_start_at,
                    WatchlistItem.pinned_at,
                )
                .join(WatchlistItem, WatchlistItem.event_id == Event.id)
                .outerjoin(
                    EventProviderReference,
                    (EventProviderReference.event_id == Event.id)
                    & (EventProviderReference.provider == "jupiter"),
                )
                .where(Event.provider == "jupiter")
                .order_by(WatchlistItem.pinned_at.desc())
            ).all()
        def iso_utc(value: datetime | None) -> str | None:
            if value is None:
                return None
            normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            return normalized.isoformat()

        return [
            {
                "event_id": event_id,
                "title": title or event_id,
                "scheduled_start_at": iso_utc(start),
                "pinned_at": iso_utc(pinned) or "",
            }
            for event_id, title, start, pinned in rows
        ]
    except (SQLAlchemyError, RuntimeError):
        raise RuntimeError("Watchlist storage is unavailable. Check the database connection and migrations.") from None
