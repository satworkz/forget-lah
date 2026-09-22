"""Forget-lah-owned confirmation receipts for imported follow-up appointments."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "bridge_confirmation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column(
            "record_id", sa.String(36), sa.ForeignKey("bridge_intake_record.id"), nullable=False
        ),
        sa.Column("source_version", sa.String(40), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "case_id", "run_id"],
            ["agent_run.clinic_id", "agent_run.case_id", "agent_run.id"],
        ),
    )


def downgrade():
    raise RuntimeError("Forward-only: preserve Bridge confirmation evidence")
