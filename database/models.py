"""Persistent provider observations, candidate audits, and disabled intent audits."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    home_name: Mapped[str | None] = mapped_column(String(160))
    away_name: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    markets: Mapped[list["Market"]] = relationship(back_populates="event")
    provider_references: Mapped[list["EventProviderReference"]] = relationship(back_populates="event")

    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_events_provider_event"),)


class EventProviderReference(Base):
    """Provider-specific identity attached to one canonical event after source-specific checks."""

    __tablename__ = "event_provider_references"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_event_name: Mapped[str | None] = mapped_column(String(200))
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mapping_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unverified")
    mapping_method: Mapped[str | None] = mapped_column(String(40))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event: Mapped[Event] = relationship(back_populates="provider_references")

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_event_provider_reference"),
        CheckConstraint(
            "mapping_status IN ('unverified', 'verified', 'rejected')",
            name="ck_event_provider_reference_status",
        ),
        Index("ix_event_provider_references_event_provider", "event_id", "provider"),
    )


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_market_id: Mapped[str] = mapped_column(String(160), nullable=False)
    market_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event: Mapped[Event] = relationship(back_populates="markets")
    outcomes: Mapped[list["MarketOutcome"]] = relationship(back_populates="market")

    __table_args__ = (UniqueConstraint("provider", "provider_market_id", name="uq_markets_provider_market"),)


class MarketOutcome(Base):
    __tablename__ = "market_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False)
    outcome_key: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_outcome_id: Mapped[str] = mapped_column(String(160), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    market: Mapped[Market] = relationship(back_populates="outcomes")

    __table_args__ = (
        UniqueConstraint("market_id", "outcome_key", name="uq_market_outcomes_market_key"),
        CheckConstraint("outcome_key IN ('HOME', 'DRAW', 'AWAY')", name="ck_market_outcomes_key"),
    )


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False)
    outcome_key: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_phase: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    executable_depth_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    event_volume_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    market_volume_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    volume_source: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("bid IS NULL OR (bid > 0 AND bid <= 1)", name="ck_market_snapshot_bid_probability"),
        CheckConstraint("ask IS NULL OR (ask > 0 AND ask <= 1)", name="ck_market_snapshot_ask_probability"),
        Index("ix_market_snapshots_market_observed", "market_id", "observed_at"),
        CheckConstraint("snapshot_phase IN ('prematch', 'live')", name="ck_market_snapshot_phase"),
    )


class StrategyEvaluation(Base):
    """Append-only audit of triggered candidate and rejection evaluations."""

    __tablename__ = "strategy_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), nullable=False)
    market_id: Mapped[str | None] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"))
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome_key: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gate_results: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    configuration_version: Mapped[str] = mapped_column(String(40), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(300), unique=True)

    __table_args__ = (
        Index("ix_strategy_evaluations_event_time", "event_id", "evaluated_at"),
        CheckConstraint("status IN ('candidate', 'rejected')", name="ck_strategy_evaluations_status"),
        CheckConstraint("outcome_key IN ('HOME', 'DRAW', 'AWAY')", name="ck_strategy_evaluations_outcome"),
    )


class ExecutionIntent(Base):
    """Candidate ticket audit; all rows are explicitly disabled, never orders."""

    __tablename__ = "execution_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), nullable=False)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome_key: Mapped[str] = mapped_column(String(20), nullable=False)
    contract_side: Mapped[str] = mapped_column(String(8), nullable=False)
    ask_price: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    size_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    max_slippage_bps: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="disabled")
    disabled_reason: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)

    __table_args__ = (
        Index("ix_execution_intents_event_time", "event_id", "observed_at"),
        CheckConstraint("outcome_key IN ('HOME', 'DRAW', 'AWAY')", name="ck_execution_intents_outcome"),
        CheckConstraint("contract_side = 'YES'", name="ck_execution_intents_contract_side"),
        CheckConstraint("ask_price > 0 AND ask_price <= 1", name="ck_execution_intents_price"),
        CheckConstraint("size_usd >= 5", name="ck_execution_intents_minimum_size"),
        CheckConstraint("max_slippage_bps > 0 AND max_slippage_bps <= 50", name="ck_execution_intents_slippage"),
        CheckConstraint("status = 'disabled'", name="ck_execution_intents_disabled_only"),
    )


class WatchlistItem(Base):
    """Persistent pin for an upcoming Jupiter event; it does not start monitoring."""

    __tablename__ = "watchlist_items"

    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True,
    )
    pinned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MatchSnapshot(Base):
    __tablename__ = "match_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    minute: Mapped[int | None] = mapped_column()
    home_score: Mapped[int | None] = mapped_column()
    away_score: Mapped[int | None] = mapped_column()
    home_shots: Mapped[int | None] = mapped_column()
    away_shots: Mapped[int | None] = mapped_column()
    home_shots_on_target: Mapped[int | None] = mapped_column()
    away_shots_on_target: Mapped[int | None] = mapped_column()
    home_possession: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    away_possession: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    home_passes: Mapped[int | None] = mapped_column()
    away_passes: Mapped[int | None] = mapped_column()
    home_pass_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    away_pass_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    home_fouls: Mapped[int | None] = mapped_column()
    away_fouls: Mapped[int | None] = mapped_column()
    home_yellow_cards: Mapped[int | None] = mapped_column()
    away_yellow_cards: Mapped[int | None] = mapped_column()
    home_red_cards: Mapped[int | None] = mapped_column()
    away_red_cards: Mapped[int | None] = mapped_column()
    home_offsides: Mapped[int | None] = mapped_column()
    away_offsides: Mapped[int | None] = mapped_column()
    home_corners: Mapped[int | None] = mapped_column()
    away_corners: Mapped[int | None] = mapped_column()
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)

    __table_args__ = (Index("ix_match_snapshots_event_observed", "event_id", "observed_at"),)
