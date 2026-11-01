"""Store triggered strategy candidates and rejection reasons."""

from alembic import op
import sqlalchemy as sa


revision = "0003_strategy_evaluations"
down_revision = "0002_snapshot_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("market_id", sa.String(length=120), nullable=True),
        sa.Column("strategy_name", sa.String(length=80), nullable=False),
        sa.Column("strategy_version", sa.String(length=30), nullable=False),
        sa.Column("outcome_key", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("configuration_version", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=True),
        sa.CheckConstraint("status IN ('candidate', 'rejected')", name="ck_strategy_evaluations_status"),
        sa.CheckConstraint("outcome_key IN ('HOME', 'DRAW', 'AWAY')", name="ck_strategy_evaluations_outcome"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        "ix_strategy_evaluations_event_time",
        "strategy_evaluations",
        ["event_id", "evaluated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_evaluations_event_time", table_name="strategy_evaluations")
    op.drop_table("strategy_evaluations")
