"""Persist user-pinned Jupiter events for the upcoming-match radar."""

from alembic import op
import sqlalchemy as sa


revision = "0007_event_watchlist"
down_revision = "0006_execution_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    op.drop_table("watchlist_items")
