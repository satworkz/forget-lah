"""Staff changes do not record patient attendance consent."""

import sqlalchemy as sa
from alembic import op

revision = "sim0004"
down_revision = "sim0003"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "sim_staff_change",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("episode_ref", sa.String(100), sa.ForeignKey("sim_episode.ref"), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("sim_staff_change")
