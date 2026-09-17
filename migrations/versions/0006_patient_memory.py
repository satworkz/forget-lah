"""Evidence-backed scoped patient needs and preferences."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "patient_memory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("patient_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("quote", sa.String(240), nullable=False),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("step_id", sa.String(36), nullable=False),
        sa.Column("supersedes", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"], ["patient_ref.clinic_id", "patient_ref.id"]
        ),
        sa.UniqueConstraint("step_id", "key"),
    )
    op.create_index("ix_patient_memory_clinic_id", "patient_memory", ["clinic_id"])
    op.create_index("ix_patient_memory_patient_id", "patient_memory", ["patient_id"])


def downgrade():
    raise RuntimeError("Forward-only: preserve patient memory history")
