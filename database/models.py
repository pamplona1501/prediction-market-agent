"""Initial persistent reference and observation schema (no execution tables)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
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

    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_events_provider_event"),)


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
    bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    executable_depth_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    event_volume_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    volume_source: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("bid IS NULL OR (bid > 0 AND bid <= 1)", name="ck_market_snapshot_bid_probability"),
        CheckConstraint("ask IS NULL OR (ask > 0 AND ask <= 1)", name="ck_market_snapshot_ask_probability"),
        Index("ix_market_snapshots_market_observed", "market_id", "observed_at"),
    )


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
    home_possession: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    away_possession: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    home_corners: Mapped[int | None] = mapped_column()
    away_corners: Mapped[int | None] = mapped_column()
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)

    __table_args__ = (Index("ix_match_snapshots_event_observed", "event_id", "observed_at"),)
