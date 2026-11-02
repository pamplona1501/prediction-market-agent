"""Persistence for candidate intents explicitly blocked from execution."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import Event, ExecutionIntent, Market
from engine.execution.jupiter_broker import DISABLED_REASON, ExecutionTicket, validate_ticket


def record_execution_intents(
    session: Session,
    *,
    jupiter_event_id: str,
    tickets: list[ExecutionTicket],
) -> int:
    """Append one disabled intent per strategy/outcome/event, safely deduplicated."""
    event = session.scalar(
        select(Event).where(
            Event.provider == "jupiter",
            Event.provider_event_id == jupiter_event_id,
        )
    )
    if event is None:
        return 0

    written = 0
    for ticket in tickets:
        validate_ticket(ticket)
        if ticket.event_id != jupiter_event_id:
            raise ValueError("Intent event does not match its persistence event.")
        market = session.scalar(
            select(Market).where(
                Market.provider == "jupiter",
                Market.provider_market_id == ticket.market_id,
                Market.event_id == event.id,
            )
        )
        if market is None:
            continue
        dedupe_key = f"{jupiter_event_id}:{ticket.strategy_name}:{ticket.outcome}"
        if session.scalar(
            select(ExecutionIntent.id).where(ExecutionIntent.dedupe_key == dedupe_key)
        ):
            continue
        row = ExecutionIntent(
            id=str(uuid4()),
            event_id=event.id,
            market_id=market.id,
            strategy_name=ticket.strategy_name,
            outcome_key=ticket.outcome,
            contract_side=ticket.contract_side,
            ask_price=ticket.ask_price,
            size_usd=ticket.size_usd,
            max_slippage_bps=ticket.max_slippage_bps,
            observed_at=ticket.observed_at.astimezone(UTC),
            status="disabled",
            disabled_reason=DISABLED_REASON,
            dedupe_key=dedupe_key,
        )
        # Protect idempotency if overlapping monitor/stat refreshes race.
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            continue
        written += 1
    return written
