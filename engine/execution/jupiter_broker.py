"""Disabled Jupiter execution boundary for auditable candidate intents.

This module deliberately has no wallet, RPC, HTTP, signing, or submission code.
It validates a candidate ticket and reports that execution is disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


MINIMUM_ORDER_USD = Decimal("5.00")
MAXIMUM_SLIPPAGE_BPS = Decimal("50")
LIVE_EXECUTION_ENABLED = False
DISABLED_REASON = "Live execution is disabled by project policy."


@dataclass(frozen=True)
class ExecutionTicket:
    event_id: str
    market_id: str
    strategy_name: str
    outcome: str
    contract_side: str
    ask_price: Decimal
    size_usd: Decimal
    max_slippage_bps: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class BrokerResult:
    status: str
    reason: str


def validate_ticket(ticket: ExecutionTicket) -> None:
    """Validate fields recorded for an intent; this does not authorize execution."""
    if not ticket.event_id.strip() or not ticket.market_id.strip():
        raise ValueError("A verified Jupiter event and market ID are required.")
    if ticket.outcome not in {"HOME", "DRAW", "AWAY"}:
        raise ValueError("Unsupported moneyline outcome.")
    # Each mapped team/draw market represents that outcome on its YES side.
    if ticket.contract_side != "YES":
        raise ValueError("The mapped three-way moneyline outcome must use its YES contract.")
    if not (Decimal("0") < ticket.ask_price <= Decimal("1")):
        raise ValueError("The candidate ask must be between $0 and $1.")
    if ticket.size_usd < MINIMUM_ORDER_USD:
        raise ValueError("Intent size is below the $5 minimum boundary.")
    if not (Decimal("0") < ticket.max_slippage_bps <= MAXIMUM_SLIPPAGE_BPS):
        raise ValueError("Intent slippage must be within the configured 50 bps boundary.")
    if ticket.observed_at.tzinfo is None:
        raise ValueError("Intent observation time must include a timezone.")


class JupiterBrokerEngine:
    """Safe stub that can validate and classify tickets but can never submit them."""

    async def process_candidate(self, ticket: ExecutionTicket) -> BrokerResult:
        validate_ticket(ticket)
        return BrokerResult(status="disabled", reason=DISABLED_REASON)
