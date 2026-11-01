"""Mark market observations as pre-match baselines or in-play snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0004_snapshot_phase"
down_revision = "0003_strategy_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_snapshots") as batch:
        batch.add_column(
            sa.Column("snapshot_phase", sa.String(length=20), server_default="live", nullable=False)
        )
        batch.create_check_constraint(
            "ck_market_snapshot_phase",
            "snapshot_phase IN ('prematch', 'live')",
        )


def downgrade() -> None:
    with op.batch_alter_table("market_snapshots") as batch:
        batch.drop_constraint("ck_market_snapshot_phase", type_="check")
        batch.drop_column("snapshot_phase")
