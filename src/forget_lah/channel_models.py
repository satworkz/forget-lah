"""Test-phone channel ledger. Case references survive reset for replay protection."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from forget_lah.db import Base, uid, utcnow


class ChannelRoutingState(Base):
    """Durable conversation focus and signed reply context, scoped to the demo clinic."""

    __tablename__ = "channel_routing_state"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ChannelBinding(Base):
    __tablename__ = "channel_binding"
    __table_args__ = (UniqueConstraint("clinic_id", "recipient", name="uq_channel_phone"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"))
    case_id: Mapped[str] = mapped_column(String(36))
    recipient: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChannelInbox(Base):
    __tablename__ = "channel_inbox"
    sid: Mapped[str] = mapped_column(String(34), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"))
    case_id: Mapped[str] = mapped_column(String(36))
    body: Mapped[str] = mapped_column(String(1600))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    event_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChannelOutbox(Base):
    __tablename__ = "channel_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    message_id: Mapped[str] = mapped_column(String(80), unique=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"))
    case_id: Mapped[str] = mapped_column(String(36))
    recipient: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(String(2600))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    provider_sid: Mapped[str | None] = mapped_column(String(34), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
