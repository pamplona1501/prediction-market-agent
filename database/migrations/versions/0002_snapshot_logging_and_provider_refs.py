"""Add market-level volume and provider event references."""

from alembic import op
import sqlalchemy as sa


revision = "0002_snapshot_refs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_snapshots",
        sa.Column("market_volume_usd", sa.Numeric(18, 4), nullable=True),
    )
    op.create_table(
        "event_provider_references",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("provider_event_id", sa.String(length=160), nullable=False),
        sa.Column("provider_event_name", sa.String(length=200), nullable=True),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "mapping_status",
            sa.String(length=20),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column("mapping_method", sa.String(length=40), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mapping_status IN ('unverified', 'verified', 'rejected')",
            name="ck_event_provider_reference_status",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_event_provider_reference"),
    )
    op.create_index(
        "ix_event_provider_references_event_provider",
        "event_provider_references",
        ["event_id", "provider"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_provider_references_event_provider",
        table_name="event_provider_references",
    )
    op.drop_table("event_provider_references")
    op.drop_column("market_snapshots", "market_volume_usd")
