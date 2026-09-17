"""Explicitly consented simulator preferences, scoped to the clinic patient."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "patient_preference",
        sa.Column("clinic_id", sa.String(36), primary_key=True),
        sa.Column("patient_id", sa.String(36), primary_key=True),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"], ["patient_ref.clinic_id", "patient_ref.id"]
        ),
    )


def downgrade():
    raise RuntimeError("Forward-only migration: preserve consent history.")
