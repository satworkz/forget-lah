"""Keep staff English translations separate from original patient evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = depends_on = None


def upgrade():
    op.add_column("agent_event", sa.Column("staff_translation", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("agent_event", "staff_translation")
