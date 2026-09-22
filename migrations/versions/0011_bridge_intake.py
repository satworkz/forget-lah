"""AI-native Bridge intake stored entirely in forget-lah."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = depends_on = None


def _expand_specialty_check():
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        table = sa.Table("followup_case", sa.MetaData(), autoload_with=connection)
        old = next(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint) and "specialty" in str(constraint.sqltext)
        )
        old.name = old.name or "ck_followup_case_specialty_old"
        with op.batch_alter_table("followup_case", copy_from=table) as batch:
            batch.drop_constraint(old.name, type_="check")
            batch.create_check_constraint(
                "ck_followup_case_specialty",
                "specialty IN ('dental','myopia','antenatal','general')",
            )
        return
    checks = sa.inspect(connection).get_check_constraints("followup_case")
    old = next(item for item in checks if "specialty" in item["sqltext"])
    op.drop_constraint(old["name"], "followup_case", type_="check")
    op.create_check_constraint(
        "ck_followup_case_specialty",
        "followup_case",
        "specialty IN ('dental','myopia','antenatal','general')",
    )


def upgrade():
    _expand_specialty_check()
    op.create_table(
        "bridge_intake_batch",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), sa.ForeignKey("clinic.id"), nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("principal.id"), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("staff_instruction", sa.String(600)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("clinic_id", "id"),
        sa.CheckConstraint("file_type IN ('csv','tsv','xlsx')"),
        sa.CheckConstraint("status IN ('ANALYSED','APPROVED','REJECTED')"),
        sa.CheckConstraint(
            "purpose IN ('UPCOMING_APPOINTMENTS','MISSED_APPOINTMENTS','RECALLS','MIXED','UNKNOWN')"
        ),
    )
    op.create_index("ix_bridge_intake_batch_clinic_id", "bridge_intake_batch", ["clinic_id"])
    op.create_table(
        "bridge_intake_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("normalized", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("patient_id", sa.String(36)),
        sa.Column("source_episode_ref", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "batch_id"],
            ["bridge_intake_batch.clinic_id", "bridge_intake_batch.id"],
        ),
        sa.UniqueConstraint("batch_id", "row_number"),
        sa.CheckConstraint("status IN ('READY','REVIEW','IMPORTED','SKIPPED')"),
    )
    op.create_index("ix_bridge_intake_record_clinic_id", "bridge_intake_record", ["clinic_id"])
    op.create_index("ix_bridge_intake_record_batch_id", "bridge_intake_record", ["batch_id"])
    op.create_index(
        "ix_bridge_intake_record_source_episode_ref",
        "bridge_intake_record",
        ["source_episode_ref"],
    )
    op.create_table(
        "bridge_import_profile",
        sa.Column("clinic_id", sa.String(36), sa.ForeignKey("clinic.id"), primary_key=True),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("last_batch_id", sa.String(36)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError("Forward-only: preserve Bridge import provenance and mappings")
