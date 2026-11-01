"""Initial event, market, outcome mapping and observation schema.

Keep this migration frozen. Later model changes belong in newer revisions.
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_event_id", sa.String(160), nullable=False),
        sa.Column("home_name", sa.String(160)),
        sa.Column("away_name", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_events_provider_event"),
    )
    op.create_table(
        "markets",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_market_id", sa.String(160), nullable=False),
        sa.Column("market_type", sa.String(40), nullable=False),
        sa.Column("source_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_market_id", name="uq_markets_provider_market"),
    )
    op.create_table(
        "market_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(120), sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("outcome_key", sa.String(20), nullable=False),
        sa.Column("provider_outcome_id", sa.String(160), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.CheckConstraint("outcome_key IN ('HOME', 'DRAW', 'AWAY')", name="ck_market_outcomes_key"),
        sa.UniqueConstraint("market_id", "outcome_key", name="uq_market_outcomes_market_key"),
    )
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.String(120), sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("outcome_key", sa.String(20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid", sa.Numeric(12, 8)),
        sa.Column("ask", sa.Numeric(12, 8)),
        sa.Column("executable_depth_usd", sa.Numeric(18, 4)),
        sa.Column("event_volume_usd", sa.Numeric(18, 4)),
        sa.Column("volume_source", sa.String(160)),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("payload_note", sa.Text()),
        sa.CheckConstraint("bid IS NULL OR (bid > 0 AND bid <= 1)", name="ck_market_snapshot_bid_probability"),
        sa.CheckConstraint("ask IS NULL OR (ask > 0 AND ask <= 1)", name="ck_market_snapshot_ask_probability"),
    )
    op.create_index("ix_market_snapshots_market_observed", "market_snapshots", ["market_id", "observed_at"])
    op.create_table(
        "match_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("minute", sa.Integer()),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
        sa.Column("home_shots", sa.Integer()),
        sa.Column("away_shots", sa.Integer()),
        sa.Column("home_possession", sa.Numeric(6, 3)),
        sa.Column("away_possession", sa.Numeric(6, 3)),
        sa.Column("home_corners", sa.Integer()),
        sa.Column("away_corners", sa.Integer()),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("provider_event_id", sa.String(160), nullable=False),
    )
    op.create_index("ix_match_snapshots_event_observed", "match_snapshots", ["event_id", "observed_at"])


def downgrade() -> None:
    op.drop_index("ix_match_snapshots_event_observed", table_name="match_snapshots")
    op.drop_table("match_snapshots")
    op.drop_index("ix_market_snapshots_market_observed", table_name="market_snapshots")
    op.drop_table("market_snapshots")
    op.drop_table("market_outcomes")
    op.drop_table("markets")
    op.drop_table("events")
