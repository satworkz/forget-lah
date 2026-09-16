"""Source-owned synthetic attendance confirmations; schedules remain unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "sim0002"
down_revision = "sim0001"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "sim_confirmation",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("episode_ref", sa.String(100), sa.ForeignKey("sim_episode.ref"), nullable=False),
        sa.Column("patient_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("episode_version", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError("Forward-only: preserve confirmation receipts.")
