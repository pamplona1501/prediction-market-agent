"""Store the selected LiveScore MCP team-stat categories."""

from alembic import op
import sqlalchemy as sa


revision = "0005_match_statistics_categories"
down_revision = "0004_snapshot_phase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        ("home_shots_on_target", sa.Integer()),
        ("away_shots_on_target", sa.Integer()),
        ("home_passes", sa.Integer()),
        ("away_passes", sa.Integer()),
        ("home_pass_accuracy", sa.Numeric(6, 3)),
        ("away_pass_accuracy", sa.Numeric(6, 3)),
        ("home_fouls", sa.Integer()),
        ("away_fouls", sa.Integer()),
        ("home_yellow_cards", sa.Integer()),
        ("away_yellow_cards", sa.Integer()),
        ("home_red_cards", sa.Integer()),
        ("away_red_cards", sa.Integer()),
        ("home_offsides", sa.Integer()),
        ("away_offsides", sa.Integer()),
    )
    for name, column_type in columns:
        op.add_column("match_snapshots", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    columns = (
        "away_offsides", "home_offsides",
        "away_red_cards", "home_red_cards",
        "away_yellow_cards", "home_yellow_cards",
        "away_fouls", "home_fouls",
        "away_pass_accuracy", "home_pass_accuracy",
        "away_passes", "home_passes",
        "away_shots_on_target", "home_shots_on_target",
    )
    for name in columns:
        op.drop_column("match_snapshots", name)
