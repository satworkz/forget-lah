"""Persist simulated outgoing messages without contacting a real channel."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "simulated_message",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("body", sa.String(2600), nullable=False),
        sa.Column("source_version", sa.String(40), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "case_id", "run_id"],
            ["agent_run.clinic_id", "agent_run.case_id", "agent_run.id"],
        ),
        sa.UniqueConstraint("run_id", "event_id", "kind"),
    )


def downgrade():
    raise RuntimeError("Forward-only migration: preserve simulated message history.")
