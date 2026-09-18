from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from forget_lah.db import Base, uid, utcnow


class PatientPreference(Base):
    __tablename__ = "patient_preference"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"], ["patient_ref.clinic_id", "patient_ref.id"]
        ),
    )
    clinic_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentRun(Base):
    __tablename__ = "agent_run"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "case_id"], ["followup_case.clinic_id", "followup_case.id"]
        ),
        UniqueConstraint("clinic_id", "case_id", "id"),
        UniqueConstraint("clinic_id", "start_key"),
        CheckConstraint("mode IN ('mock','organiser','anthropic')", name="ck_agent_run_mode"),
        CheckConstraint(
            "status IN ('queued','running','waiting','paused','escalated','completed')"
        ),
        CheckConstraint("active_role IN ('coordinator','engagement','preparation')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    start_key: Mapped[str] = mapped_column(String(64))
    start_case_version: Mapped[int] = mapped_column(Integer)
    started_by: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    authorised_by: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    active_role: Mapped[str] = mapped_column(String(20), default="coordinator")
    goal: Mapped[str] = mapped_column(String(240))
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def run_fk():
    return ForeignKeyConstraint(
        ["clinic_id", "case_id", "run_id"],
        ["agent_run.clinic_id", "agent_run.case_id", "agent_run.id"],
    )


class AgentStep(Base):
    __tablename__ = "agent_step"
    __table_args__ = (
        run_fk(),
        UniqueConstraint("run_id", "sequence"),
        CheckConstraint("origin IN ('mock','model','rule')"),
        CheckConstraint("status IN ('pending','tool_pending','completed','rejected','error')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    case_version: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    observation: Mapped[dict] = mapped_column(JSON, default=dict)
    decision: Mapped[dict | None] = mapped_column(JSON)
    policy: Mapped[dict | None] = mapped_column(JSON)
    tool_result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(60))
    validation_failures: Mapped[list | None] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentDelegation(Base):
    __tablename__ = "agent_delegation"
    __table_args__ = (run_fk(), CheckConstraint("status IN ('active','returned','aborted')"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    target: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(36))
    goal: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active")
    start_sequence: Mapped[int] = mapped_column(Integer)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    result_reason_code: Mapped[str | None] = mapped_column(String(60))


class AgentEvent(Base):
    __tablename__ = "agent_event"
    __table_args__ = (run_fk(), UniqueConstraint("run_id", "client_key"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    client_key: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    expected_case_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StaffHandoff(Base):
    __tablename__ = "staff_handoff"
    __table_args__ = (run_fk(), UniqueConstraint("run_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
    reason_code: Mapped[str] = mapped_column(String(60))
    risk: Mapped[str] = mapped_column(String(10))
    accepted_by: Mapped[str | None] = mapped_column(ForeignKey("principal.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelBudget(Base):
    __tablename__ = "model_budget"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    day: Mapped[str] = mapped_column(String(10))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SimulatedMessage(Base):
    __tablename__ = "simulated_message"
    __table_args__ = (run_fk(), UniqueConstraint("run_id", "event_id", "kind"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(30))
    body: Mapped[str] = mapped_column(String(2600))
    translation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_version: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def message_order():
    # Several messages from one decision can share the database clock tick.
    from sqlalchemy import case

    return case(
        (SimulatedMessage.kind == "concern_acknowledgement", 0),
        (SimulatedMessage.kind.in_(["preference_saved", "needs_acknowledgement"]), 1),
        else_=2,
    )


class PatientMemory(Base):
    __tablename__ = "patient_memory"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"], ["patient_ref.clinic_id", "patient_ref.id"]
        ),
        UniqueConstraint("step_id", "key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_id: Mapped[str] = mapped_column(String(36), index=True)
    case_id: Mapped[str] = mapped_column(String(36))
    key: Mapped[str] = mapped_column(String(40))
    value: Mapped[dict] = mapped_column(JSON)
    scope: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16))
    quote: Mapped[str] = mapped_column(String(240))
    message_id: Mapped[str] = mapped_column(String(36))
    step_id: Mapped[str] = mapped_column(String(36))
    supersedes: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
