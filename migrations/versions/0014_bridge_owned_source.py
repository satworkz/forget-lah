"""Forget-lah-owned episode state and scoped follow-up options for Bridge clinics."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = depends_on = None


def upgrade():
    episodes = op.create_table(
        "bridge_episode",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), sa.ForeignKey("clinic.id"), nullable=False),
        sa.Column("patient_id", sa.String(36), nullable=False),
        sa.Column("source_episode_ref", sa.String(100), nullable=False),
        sa.Column(
            "record_id", sa.String(36), sa.ForeignKey("bridge_intake_record.id"), nullable=False
        ),
        sa.Column("normalized", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("followup_status", sa.String(30), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("clinic_id", "source_episode_ref"),
        sa.UniqueConstraint("clinic_id", "id"),
    )
    op.create_table(
        "bridge_followup_slot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("episode_id", sa.String(36), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doctor", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("principal.id"), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "episode_id"], ["bridge_episode.clinic_id", "bridge_episode.id"]
        ),
        sa.UniqueConstraint("episode_id", "starts_at", "doctor"),
        sa.CheckConstraint("status IN ('available','booked','withdrawn')"),
    )
    # Preserve existing approved imports; newest approved evidence initializes each episode once.
    connection = op.get_bind()
    records = sa.Table("bridge_intake_record", sa.MetaData(), autoload_with=connection)
    cases = sa.Table("followup_case", sa.MetaData(), autoload_with=connection)
    runs = sa.Table("agent_run", sa.MetaData(), autoload_with=connection)
    seen = set()
    for row in connection.execute(
        sa.select(records)
        .where(records.c.status == "IMPORTED")
        .order_by(records.c.created_at.desc(), records.c.id.desc())
    ).mappings():
        key = (row["clinic_id"], row["source_episode_ref"])
        if key in seen or not row["patient_id"] or not row["source_episode_ref"]:
            continue
        seen.add(key)
        latest_status = connection.scalar(
            sa.select(runs.c.status)
            .join(
                cases, sa.and_(runs.c.case_id == cases.c.id, runs.c.clinic_id == cases.c.clinic_id)
            )
            .where(
                cases.c.clinic_id == row["clinic_id"],
                cases.c.source_episode_ref == row["source_episode_ref"],
            )
            .order_by(runs.c.created_at.desc(), runs.c.id.desc())
            .limit(1)
        )
        followup_status = {
            "running": "in_progress",
            "waiting": "awaiting_reply",
            "escalated": "needs_staff",
        }.get(latest_status, latest_status or "pending")
        connection.execute(
            episodes.insert().values(
                id=str(uuid4()),
                clinic_id=row["clinic_id"],
                patient_id=row["patient_id"],
                source_episode_ref=row["source_episode_ref"],
                record_id=row["id"],
                normalized=row["normalized"],
                version=1,
                followup_status=followup_status,
                updated_at=datetime.now(UTC),
            )
        )


def downgrade():
    raise RuntimeError("Forward-only: preserve managed Bridge appointment state")
