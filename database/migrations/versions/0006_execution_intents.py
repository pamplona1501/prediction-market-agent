"""Audit eligible strategy intents while execution remains disabled."""

from alembic import op
import sqlalchemy as sa


revision = "0006_execution_intents"
down_revision = "0005_match_statistics_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_intents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("market_id", sa.String(length=120), nullable=False),
        sa.Column("strategy_name", sa.String(length=80), nullable=False),
        sa.Column("outcome_key", sa.String(length=20), nullable=False),
        sa.Column("contract_side", sa.String(length=8), nullable=False),
        sa.Column("ask_price", sa.Numeric(12, 8), nullable=False),
        sa.Column("size_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("max_slippage_bps", sa.Numeric(8, 2), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="disabled"),
        sa.Column("disabled_reason", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.CheckConstraint("outcome_key IN ('HOME', 'DRAW', 'AWAY')", name="ck_execution_intents_outcome"),
        sa.CheckConstraint("contract_side = 'YES'", name="ck_execution_intents_contract_side"),
        sa.CheckConstraint("ask_price > 0 AND ask_price <= 1", name="ck_execution_intents_price"),
        sa.CheckConstraint("size_usd >= 5", name="ck_execution_intents_minimum_size"),
        sa.CheckConstraint("max_slippage_bps > 0 AND max_slippage_bps <= 50", name="ck_execution_intents_slippage"),
        sa.CheckConstraint("status = 'disabled'", name="ck_execution_intents_disabled_only"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_execution_intents_dedupe_key"),
    )
    op.create_index("ix_execution_intents_event_time", "execution_intents", ["event_id", "observed_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_intents_event_time", table_name="execution_intents")
    op.drop_table("execution_intents")
