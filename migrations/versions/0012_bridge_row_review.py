"""Staff review metadata for Bridge intake rows; forget-lah DB only."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = depends_on = None


def upgrade():
    op.add_column("bridge_intake_record", sa.Column("staff_overrides", sa.JSON()))
    op.add_column("bridge_intake_record", sa.Column("reviewed_by", sa.String(36)))
    op.add_column(
        "bridge_intake_record",
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    raise RuntimeError("Forward-only: preserve Bridge staff-review provenance")
