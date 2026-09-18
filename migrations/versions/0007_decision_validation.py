"""Retain bounded structured proposal validation evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = depends_on = None


def upgrade():
    op.add_column("agent_step", sa.Column("validation_failures", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("Forward-only: preserve decision validation history")
