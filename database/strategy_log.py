"""Persistence for strategy candidate/rejection audit rows."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Event, StrategyEvaluation


def record_strategy_evaluations(
    session: Session,
    *,
    jupiter_event_id: str,
    evaluations: list[dict[str, object]],
    input_snapshot: dict[str, object],
) -> int:
    """Append triggered results, deduplicating candidates once per event/outcome.

    A candidate is emitted at most once per strategy/outcome/event. Re-arming
    is deliberately deferred until a later event ID so a live oscillating quote
    cannot generate repeated candidate notifications.
    """
    event = session.scalar(
        select(Event).where(Event.provider == "jupiter", Event.provider_event_id == jupiter_event_id)
    )
    if event is None:
        return 0
    written = 0
    for result in evaluations:
        if not result.get("triggered"):
            continue
        status = str(result["status"])
        if status not in {"candidate", "rejected"}:
            continue
        strategy = str(result["strategy_name"])
        outcome = str(result["outcome"])
        dedupe_key = (
            f"{jupiter_event_id}:{strategy}:{outcome}" if status == "candidate" else None
        )
        if dedupe_key and session.scalar(
            select(StrategyEvaluation.id).where(StrategyEvaluation.dedupe_key == dedupe_key)
        ):
            continue
        evaluated_at = datetime.fromisoformat(str(result["evaluated_at"])).astimezone(UTC)
        session.add(
            StrategyEvaluation(
                id=str(uuid4()),
                event_id=event.id,
                market_id=result.get("market_id"),
                strategy_name=strategy,
                strategy_version=str(result["strategy_version"]),
                outcome_key=outcome,
                status=status,
                evaluated_at=evaluated_at,
                gate_results=dict(result["gate_results"]),
                reasons=list(result["reasons"]),
                input_snapshot=input_snapshot,
                configuration_version=str(result["configuration_version"]),
                dedupe_key=dedupe_key,
            )
        )
        written += 1
    return written
