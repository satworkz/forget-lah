"""Clinic roles and deterministic security/audit evidence; preserve existing access."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "clinic_membership",
        sa.Column("role", sa.String(20), nullable=False, server_default="staff"),
    )
    op.create_table(
        "security_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36)),
        sa.Column("actor_id", sa.String(36)),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_security_event_clinic_id", "security_event", ["clinic_id"])
    op.create_index("ix_security_event_resource_id", "security_event", ["resource_id"])


def downgrade():
    op.drop_table("security_event")
    op.drop_column("clinic_membership", "role")
