"""Patient-scoped channel routing; preserve all existing provider ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "channel_routing_state",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("clinic_id", sa.String(36), sa.ForeignKey("clinic.id"), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )


def downgrade():
    raise RuntimeError("Forward-only: preserve conversation routing evidence")
