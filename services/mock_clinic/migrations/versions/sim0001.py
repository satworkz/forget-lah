"""Isolated synthetic clinic source. No application case/history tables."""

import sqlalchemy as sa
from alembic import op

revision = "sim0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sim_patient",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_alias", sa.String(100), nullable=False),
    )
    op.create_table(
        "sim_episode",
        sa.Column("ref", sa.String(100), primary_key=True),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("sim_patient.id"), nullable=False),
        sa.Column("specialty", sa.String(20), nullable=False),
        sa.Column("record_type", sa.String(20), nullable=False),
        sa.Column("source_status", sa.String(20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("has_future_booking", sa.Boolean(), nullable=False),
        sa.Column("doctor_note", sa.String(400), nullable=False),
        sa.Column("note_approved", sa.Boolean(), nullable=False),
        sa.Column("prerequisite", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "sim_slot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("specialty", sa.String(20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doctor", sa.String(80), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("doctor", "starts_at"),
    )


def downgrade():
    op.drop_table("sim_slot")
    op.drop_table("sim_episode")
    op.drop_table("sim_patient")
