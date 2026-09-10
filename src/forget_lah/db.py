from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Clinic(Base):
    __tablename__ = "clinic"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(150))


class Principal(Base):
    __tablename__ = "principal"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base):
    __tablename__ = "clinic_membership"
    __table_args__ = (UniqueConstraint("principal_id", "clinic_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Base):
    __tablename__ = "auth_session"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Patient(Base):
    __tablename__ = "patient_ref"
    __table_args__ = (UniqueConstraint("clinic_id", "id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"))
    display_alias: Mapped[str] = mapped_column(String(100))


class FollowupCase(Base):
    __tablename__ = "followup_case"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"], ["patient_ref.clinic_id", "patient_ref.id"]
        ),
        UniqueConstraint("clinic_id", "source_episode_ref"),
        UniqueConstraint("clinic_id", "id"),
        CheckConstraint("trigger IN ('UPCOMING','MISSED','RECALL_OVERDUE')"),
        CheckConstraint("state = 'NEW'"),
        CheckConstraint("specialty IN ('dental','myopia','antenatal')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"))
    patient_id: Mapped[str] = mapped_column(String(36))
    source_episode_ref: Mapped[str] = mapped_column(String(100))
    specialty: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(30), default="NEW")
    case_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "case_id"], ["followup_case.clinic_id", "followup_case.id"]
        ),
        UniqueConstraint("case_id", "kind"),
        CheckConstraint("status IN ('queued','running','done')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(50), default="foundation_case_ready")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "case_id"], ["followup_case.clinic_id", "followup_case.id"]
        ),
        UniqueConstraint("case_id", "event_type"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    clinic_id: Mapped[str] = mapped_column(String(36))
    case_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(60))
    decision_origin: Mapped[str] = mapped_column(String(20), default="rule")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
