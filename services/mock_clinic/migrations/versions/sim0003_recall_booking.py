"""Preserve source-owned slot booking evidence on synthetic receipts."""

import sqlalchemy as sa
from alembic import op

revision = "sim0003"
down_revision = "sim0002"
branch_labels = depends_on = None


def upgrade():
    op.add_column("sim_confirmation", sa.Column("booking_slot_id", sa.String(36)))
    op.add_column("sim_confirmation", sa.Column("booking_slot_version", sa.Integer()))
    op.add_column("sim_confirmation", sa.Column("prior_episode_version", sa.Integer()))


def downgrade():
    raise RuntimeError("Forward-only: preserve source booking receipts.")
