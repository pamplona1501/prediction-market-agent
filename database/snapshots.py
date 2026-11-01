"""Persistence helpers for sourced market observations."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import re
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Event, EventProviderReference, Market, MarketSnapshot, MatchSnapshot
from integrations.market_data.jupiter import JupiterEvent, JupiterLiveScore


JUPITER_PROVIDER = "jupiter"


def _stable_id(namespace: str, provider: str, external_id: str) -> str:
    digest = sha256(f"{provider}:{external_id}".encode("utf-8")).hexdigest()
    return f"{namespace}_{digest}"


def _probability(value):
    """Keep provider omissions/invalid sentinel values out of constrained price columns."""
    if value is None or value <= 0 or value > 1:
        return None
    return value


def record_jupiter_market_snapshots(
    session: Session,
    event: JupiterEvent,
    *,
    observed_at: datetime,
    score: JupiterLiveScore | None = None,
    orderbooks: Mapping[str, Mapping[str, object]] | None = None,
    snapshot_phase: str = "live",
) -> int:
    """Insert a sourced YES/NO snapshot for every market in one selected Jupiter event.

    The caller owns the transaction. Event and market references are upserted by
    their provider IDs; observations are append-only. No upstream raw payloads,
    credentials, or derived payouts are stored.
    """
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    if snapshot_phase not in {"prematch", "live"}:
        raise ValueError("snapshot_phase must be prematch or live")
    if not event.event_id or len(event.event_id) > 160:
        raise ValueError("event has an invalid Jupiter provider ID")

    canonical_event = session.scalar(
        select(Event).where(
            Event.provider == JUPITER_PROVIDER,
            Event.provider_event_id == event.event_id,
        )
    )
    if canonical_event is None:
        canonical_event = Event(
            id=_stable_id("evt", JUPITER_PROVIDER, event.event_id),
            provider=JUPITER_PROVIDER,
            provider_event_id=event.event_id,
            home_name=score.home_team if score else None,
            away_name=score.away_team if score else None,
            created_at=observed_at.astimezone(UTC),
        )
        session.add(canonical_event)
        session.flush()
    elif score:
        canonical_event.home_name = score.home_team
        canonical_event.away_name = score.away_team

    if score:
        score_match = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", score.score or "")
        minute_match = re.search(r"\d+", score.elapsed or "")
        session.add(
            MatchSnapshot(
                event_id=canonical_event.id,
                observed_at=observed_at.astimezone(UTC),
                status=(score.status or score.period or "UNKNOWN")[:30],
                minute=int(minute_match.group()) if minute_match else None,
                home_score=int(score_match.group(1)) if score_match else None,
                away_score=int(score_match.group(2)) if score_match else None,
                source="jupiter_prediction_api",
                provider_event_id=event.event_id,
            )
        )

    provider_reference = session.scalar(
        select(EventProviderReference).where(
            EventProviderReference.provider == JUPITER_PROVIDER,
            EventProviderReference.provider_event_id == event.event_id,
        )
    )
    if provider_reference is None:
        session.add(
            EventProviderReference(
                event_id=canonical_event.id,
                provider=JUPITER_PROVIDER,
                provider_event_id=event.event_id,
                provider_event_name=event.title,
                scheduled_start_at=event.scheduled_start_at,
                mapping_status="verified",
                mapping_method="primary_provider_id",
                verified_at=observed_at.astimezone(UTC),
                created_at=observed_at.astimezone(UTC),
            )
        )
    else:
        provider_reference.provider_event_name = event.title
        provider_reference.scheduled_start_at = event.scheduled_start_at

    snapshots_written = 0
    for provider_market in event.markets:
        if not provider_market.market_id or len(provider_market.market_id) > 160:
            continue
        market = session.scalar(
            select(Market).where(
                Market.provider == JUPITER_PROVIDER,
                Market.provider_market_id == provider_market.market_id,
            )
        )
        if market is None:
            market = Market(
                id=_stable_id("mkt", JUPITER_PROVIDER, provider_market.market_id),
                event_id=canonical_event.id,
                provider=JUPITER_PROVIDER,
                provider_market_id=provider_market.market_id,
                market_type=provider_market.sports_market_type or "unknown",
                source_verified=False,
                created_at=observed_at.astimezone(UTC),
            )
            session.add(market)
            session.flush()
        else:
            market.event_id = canonical_event.id
            market.market_type = provider_market.sports_market_type or "unknown"

        book = (orderbooks or {}).get(provider_market.market_id)
        if book:
            prices = (
                ("YES", _probability(book.get("yes_bid")), _probability(book.get("yes_ask")),
                 book.get("yes_ask_depth_usd")),
                ("NO", _probability(book.get("no_bid")), _probability(book.get("no_ask")),
                 book.get("no_ask_depth_usd")),
            )
        else:
            prices = (
                ("YES", _probability(provider_market.sell_yes_usd), _probability(provider_market.buy_yes_usd), None),
                ("NO", _probability(provider_market.sell_no_usd), _probability(provider_market.buy_no_usd), None),
            )
        for outcome_key, bid, ask, depth in prices:
            session.add(
                MarketSnapshot(
                    market_id=market.id,
                    outcome_key=outcome_key,
                    observed_at=observed_at.astimezone(UTC),
                    snapshot_phase=snapshot_phase,
                    bid=bid,
                    ask=ask,
                    executable_depth_usd=depth,
                    event_volume_usd=event.reported_volume_usd,
                    market_volume_usd=provider_market.volume_usd,
                    volume_source="Jupiter events.volumeUsd; market pricing.volume",
                    source="jupiter_prediction_api",
                )
            )
            snapshots_written += 1

    return snapshots_written


def read_prematch_yes_prices(
    session: Session,
    *,
    event_provider_id: str,
    market_provider_ids: list[str],
    scheduled_start_at: datetime | None,
) -> dict[str, tuple[Decimal, datetime]]:
    """Load the last recorded pre-kickoff YES ask for each exact Jupiter market ID."""
    if not market_provider_ids or scheduled_start_at is None:
        return {}
    cutoff = scheduled_start_at if scheduled_start_at.tzinfo else scheduled_start_at.replace(tzinfo=UTC)
    rows = session.execute(
        select(Market.provider_market_id, MarketSnapshot.ask, MarketSnapshot.observed_at)
        .join(MarketSnapshot, MarketSnapshot.market_id == Market.id)
        .join(Event, Event.id == Market.event_id)
        .where(
            Event.provider == JUPITER_PROVIDER,
            Event.provider_event_id == event_provider_id,
            Market.provider == JUPITER_PROVIDER,
            Market.provider_market_id.in_(market_provider_ids),
            MarketSnapshot.snapshot_phase == "prematch",
            MarketSnapshot.outcome_key == "YES",
            MarketSnapshot.ask.is_not(None),
        )
        .order_by(MarketSnapshot.observed_at.desc())
    ).all()
    prices: dict[str, tuple[Decimal, datetime]] = {}
    for provider_market_id, price, observed_at in rows:
        if provider_market_id in prices or price is None:
            continue
        observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
        if observed < cutoff:
            prices[provider_market_id] = (price, observed)
    return prices
