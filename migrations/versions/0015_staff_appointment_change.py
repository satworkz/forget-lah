"""Durable staff appointment changes, separate from patient confirmations."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "staff_appointment_change",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("client_key", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("principal.id"), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("receipt", sa.JSON()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "case_id", "run_id"],
            ["agent_run.clinic_id", "agent_run.case_id", "agent_run.id"],
        ),
        sa.UniqueConstraint("clinic_id", "client_key"),
    )


def downgrade():
    op.drop_table("staff_appointment_change")
