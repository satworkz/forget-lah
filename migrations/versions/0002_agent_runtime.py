"""Persist agent requests, delegation, events, handoffs and a shared call budget."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def run_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
    ]


def run_fk():
    return sa.ForeignKeyConstraint(
        ["clinic_id", "case_id", "run_id"],
        ["agent_run.clinic_id", "agent_run.case_id", "agent_run.id"],
    )


def upgrade():
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clinic_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("start_key", sa.String(64), nullable=False),
        sa.Column("start_case_version", sa.Integer(), nullable=False),
        sa.Column("started_by", sa.String(36), sa.ForeignKey("principal.id"), nullable=False),
        sa.Column("authorised_by", sa.String(36), sa.ForeignKey("principal.id"), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("active_role", sa.String(20), nullable=False),
        sa.Column("goal", sa.String(240), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["clinic_id", "case_id"], ["followup_case.clinic_id", "followup_case.id"]
        ),
        sa.UniqueConstraint("clinic_id", "case_id", "id"),
        sa.UniqueConstraint("clinic_id", "start_key"),
        sa.CheckConstraint("mode IN ('mock','organiser')"),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting','paused','escalated','completed')"
        ),
        sa.CheckConstraint("active_role IN ('coordinator','engagement','preparation')"),
    )
    op.create_index("ix_agent_run_case_id", "agent_run", ["case_id"])
    op.create_table(
        "agent_step",
        *run_columns(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
        sa.Column("decision", sa.JSON()),
        sa.Column("policy", sa.JSON()),
        sa.Column("tool_result", sa.JSON()),
        sa.Column("error_code", sa.String(60)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        run_fk(),
        sa.UniqueConstraint("run_id", "sequence"),
        sa.CheckConstraint("origin IN ('mock','model','rule')"),
        sa.CheckConstraint("status IN ('pending','tool_pending','completed','rejected','error')"),
    )
    op.create_index("ix_agent_step_run_id", "agent_step", ["run_id"])
    op.create_table(
        "agent_delegation",
        *run_columns(),
        sa.Column("target", sa.String(20), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("goal", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("start_sequence", sa.Integer(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("result_reason_code", sa.String(60)),
        run_fk(),
        sa.CheckConstraint("status IN ('active','returned','aborted')"),
    )
    op.create_index("ix_agent_delegation_run_id", "agent_delegation", ["run_id"])
    op.create_table(
        "agent_event",
        *run_columns(),
        sa.Column("client_key", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("principal.id"), nullable=False),
        sa.Column("expected_case_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("content", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        run_fk(),
        sa.UniqueConstraint("run_id", "client_key"),
    )
    op.create_index("ix_agent_event_run_id", "agent_event", ["run_id"])
    op.create_table(
        "staff_handoff",
        *run_columns(),
        sa.Column("reason_code", sa.String(60), nullable=False),
        sa.Column("risk", sa.String(10), nullable=False),
        sa.Column("accepted_by", sa.String(36), sa.ForeignKey("principal.id")),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        run_fk(),
        sa.UniqueConstraint("run_id"),
    )
    budget = op.create_table(
        "model_budget",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(budget, [{"id": "organiser", "day": "", "calls": 0}])


def downgrade():
    for table in (
        "model_budget",
        "staff_handoff",
        "agent_event",
        "agent_delegation",
        "agent_step",
        "agent_run",
    ):
        op.drop_table(table)
