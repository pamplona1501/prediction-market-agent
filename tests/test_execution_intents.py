from datetime import UTC, datetime
from decimal import Decimal

import asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from database.execution_intents import record_execution_intents
from database.models import Base, ExecutionIntent
from database.snapshots import record_jupiter_market_snapshots
from engine.execution.jupiter_broker import (
    DISABLED_REASON,
    ExecutionTicket,
    JupiterBrokerEngine,
    validate_ticket,
)
from integrations.market_data.jupiter import JupiterEvent, JupiterMarket
from monitoring.service import LiveMonitor


def _ticket(**changes):
    values = {
        "event_id": "event-1",
        "market_id": "market-1",
        "strategy_name": "UNDERDOG_SCOUTER",
        "outcome": "AWAY",
        "contract_side": "YES",
        "ask_price": Decimal("0.25"),
        "size_usd": Decimal("5.00"),
        "max_slippage_bps": Decimal("50"),
        "observed_at": datetime(2026, 11, 2, 18, 0, tzinfo=UTC),
    }
    values.update(changes)
    return ExecutionTicket(**values)


def _event():
    market = JupiterMarket(
        market_id="market-1", title="Away wins", status="open", provider="jupiter",
        buy_yes_usd=Decimal("0.25"), sell_yes_usd=Decimal("0.24"),
        buy_no_usd=Decimal("0.76"), sell_no_usd=Decimal("0.75"),
        volume_usd=Decimal("200000"), sports_market_type="moneyline", period_type="regular",
        sports_line=None, team_name="Away", team_abbreviation="AWY", team_color=None,
        team_image_url=None, market_options=("Yes", "No"),
    )
    return JupiterEvent(
        event_id="event-1", title="Home vs Away", category="sports", subcategory="soccer",
        scheduled_start_at=datetime(2026, 11, 2, 18, 0, tzinfo=UTC), is_live=True,
        reported_volume_usd=Decimal("1500000"), markets=(market,),
    )


def test_broker_validates_ticket_and_always_reports_disabled():
    validate_ticket(_ticket())
    result = asyncio.run(JupiterBrokerEngine().process_candidate(_ticket()))
    assert result.status == "disabled"
    assert result.reason == DISABLED_REASON
    assert not hasattr(JupiterBrokerEngine, "submit_order")
    assert not hasattr(JupiterBrokerEngine, "sign_transaction")


def test_broker_rejects_below_minimum_and_non_yes_market_mapping():
    for ticket in (
        _ticket(size_usd=Decimal("4.99")),
        _ticket(contract_side="NO"),
        _ticket(ask_price=Decimal("1.01")),
    ):
        try:
            validate_ticket(ticket)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid execution intent was accepted")


def test_execution_intent_audit_is_persisted_once_and_never_as_an_order():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    event = _event()
    with Session(engine) as session, session.begin():
        record_jupiter_market_snapshots(
            session, event, observed_at=datetime(2026, 11, 2, 18, 0, tzinfo=UTC),
        )
    with Session(engine) as session, session.begin():
        assert record_execution_intents(session, jupiter_event_id="event-1", tickets=[_ticket()]) == 1
    with Session(engine) as session, session.begin():
        assert record_execution_intents(session, jupiter_event_id="event-1", tickets=[_ticket()]) == 0
    with Session(engine) as session:
        rows = session.scalars(select(ExecutionIntent)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome_key == "AWAY"
    assert row.contract_side == "YES"
    assert row.status == "disabled"
    assert row.disabled_reason == DISABLED_REASON
    assert row.size_usd == Decimal("5.0000")


def test_monitor_only_creates_ticket_for_exact_candidate_market_mapping(monkeypatch):
    tickets = []

    class FakeBroker:
        async def process_candidate(self, ticket):
            tickets.append(ticket)
            from engine.execution.jupiter_broker import BrokerResult
            return BrokerResult(status="disabled", reason=DISABLED_REASON)

    monkeypatch.setattr("monitoring.service.persist_execution_intents", lambda *args: (True, 1))
    monitor = LiveMonitor(broker=FakeBroker())
    selected = {"moneyline": [{
        "outcome": "AWAY", "market_id": "market-1",
        "orderbook": {"yes_ask": "0.25", "fetched_at": "2026-11-02T18:00:00+00:00"},
    }]}
    evaluations = [{
        "status": "candidate", "outcome": "AWAY", "market_id": "market-1",
        "strategy_name": "UNDERDOG_SCOUTER", "ask": "0.25",
    }]
    asyncio.run(monitor._process_candidate_intents("event-1", selected, evaluations))
    assert len(tickets) == 1
    assert tickets[0].outcome == "AWAY" and tickets[0].contract_side == "YES"
    assert evaluations[0]["execution_intent"]["status"] == "disabled"
    assert evaluations[0]["execution_intent"]["audit_status"] == "saved"

    selected["moneyline"] = []
    rejected = [{
        "status": "candidate", "outcome": "AWAY", "market_id": "market-1",
        "strategy_name": "UNDERDOG_SCOUTER", "ask": "0.25",
    }]
    asyncio.run(monitor._process_candidate_intents("event-1", selected, rejected))
    assert len(tickets) == 1
    assert rejected[0]["execution_intent"]["status"] == "rejected"
