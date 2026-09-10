"""foundation schema"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinic",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "principal",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "auth_session",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principal.id"],
        ),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_table(
        "clinic_membership",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("clinic_id", sa.String(length=36), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinic.id"],
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principal.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("principal_id", "clinic_id"),
    )
    op.create_table(
        "patient_ref",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clinic_id", sa.String(length=36), nullable=False),
        sa.Column("display_alias", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinic.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "id"),
    )
    op.create_table(
        "followup_case",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clinic_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("source_episode_ref", sa.String(length=100), nullable=False),
        sa.Column("specialty", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("specialty IN ('dental','myopia','antenatal')"),
        sa.CheckConstraint("state = 'NEW'"),
        sa.CheckConstraint("trigger IN ('UPCOMING','MISSED','RECALL_OVERDUE')"),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient_ref.clinic_id", "patient_ref.id"],
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"],
            ["clinic.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clinic_id", "id"),
        sa.UniqueConstraint("clinic_id", "source_episode_ref"),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clinic_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("decision_origin", sa.String(length=20), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "case_id"],
            ["followup_case.clinic_id", "followup_case.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "event_type"),
    )
    op.create_table(
        "job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("clinic_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('queued','running','done')"),
        sa.ForeignKeyConstraint(
            ["clinic_id", "case_id"],
            ["followup_case.clinic_id", "followup_case.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "kind"),
    )


def downgrade():
    op.drop_table("job")
    op.drop_table("audit_event")
    op.drop_table("followup_case")
    op.drop_table("patient_ref")
    op.drop_table("clinic_membership")
    op.drop_table("auth_session")
    op.drop_table("principal")
    op.drop_table("clinic")
