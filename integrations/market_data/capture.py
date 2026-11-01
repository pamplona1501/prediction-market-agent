"""Fetch and persist one user-selected Jupiter event (read-only provider access)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.connection import get_engine
from database.strategy_log import record_strategy_evaluations
from database.snapshots import record_jupiter_market_snapshots
from integrations.market_data.jupiter import JupiterEvent, JupiterLiveScore, JupiterPredictionClient


@dataclass(frozen=True)
class CaptureResult:
    event: JupiterEvent
    snapshots_written: int
    persisted: bool


def persist_event_snapshot(
    event: JupiterEvent,
    *,
    score: JupiterLiveScore | None = None,
    orderbooks: dict[str, dict[str, object]] | None = None,
    snapshot_phase: str = "live",
) -> CaptureResult:
    """Persist provider observations already fetched by the monitoring service."""
    from datetime import datetime

    observed_at = datetime.now(UTC)
    try:
        with Session(get_engine()) as session, session.begin():
            count = record_jupiter_market_snapshots(
                session,
                event,
                observed_at=observed_at,
                score=score,
                orderbooks=orderbooks,
                snapshot_phase=snapshot_phase,
            )
        return CaptureResult(event=event, snapshots_written=count, persisted=True)
    except (SQLAlchemyError, RuntimeError, ValueError):
        return CaptureResult(event=event, snapshots_written=0, persisted=False)


def persist_prematch_event(event: JupiterEvent) -> CaptureResult:
    """Capture only pre-match moneyline prices used as explicit strategy baselines."""
    moneyline = tuple(market for market in event.markets if market.sports_market_type == "moneyline")
    if not moneyline:
        return CaptureResult(event=event, snapshots_written=0, persisted=False)
    return persist_event_snapshot(
        replace(event, markets=moneyline),
        snapshot_phase="prematch",
    )


def persist_strategy_audit(
    event_id: str,
    evaluations: list[dict[str, object]],
    input_snapshot: dict[str, object],
) -> tuple[bool, int]:
    """Persist triggered candidate/rejection rows without exposing DB errors."""
    from sqlalchemy.exc import SQLAlchemyError

    try:
        with Session(get_engine()) as session, session.begin():
            count = record_strategy_evaluations(
                session,
                jupiter_event_id=event_id,
                evaluations=evaluations,
                input_snapshot=input_snapshot,
            )
        return True, count
    except (SQLAlchemyError, RuntimeError, ValueError):
        return False, 0


def capture_selected_event(
    event_id: str,
    *,
    score: JupiterLiveScore | None = None,
) -> CaptureResult:
    """Fetch fresh detail and append observations; DB errors leave read-only data usable."""
    event = JupiterPredictionClient.from_environment().get_sports_event_details(event_id)
    return persist_event_snapshot(event, score=score)
