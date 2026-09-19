"""Signed WhatsApp transport for explicitly registered synthetic test patients."""

import re
import secrets
from datetime import timedelta
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator

from forget_lah.auth import digest
from forget_lah.channel_models import (
    ChannelBinding,
    ChannelInbox,
    ChannelOutbox,
    ChannelRoutingState,
)
from forget_lah.channel_routing import channel_notice, conversation, patient_cases, resolve_case
from forget_lah.db import Clinic, FollowupCase, uid, utcnow
from forget_lah.runtime.engine import abort_delegation, as_utc, release
from forget_lah.runtime.models import AgentEvent, AgentRun, SimulatedMessage, StaffHandoff
from forget_lah.runtime.startup import SIMULATOR_GOAL, automation_authorised
from forget_lah.service_identity import AUTOMATION_PRINCIPAL_ID
from forget_lah.source import DEMO_CLINIC_ID
from forget_lah.whatsapp import WhatsAppClient, WhatsAppError, WhatsAppSettings

WEBHOOK = "/api/channels/whatsapp/inbound"
BINDING = "whatsapp-test-phone"


def configuration(settings):
    if not settings.whatsapp_enabled:
        return None
    return WhatsAppSettings()


def latest_run(db, case_id):
    return db.scalar(
        select(AgentRun)
        .where(AgentRun.case_id == case_id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


class BindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    enabled: bool
    binding_id: str | None = Field(default=None, max_length=40)
    recipient: str | None = None

    @field_validator("recipient")
    @classmethod
    def phone(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value.startswith("whatsapp:"):
            value = "whatsapp:" + value
        if not re.fullmatch(r"whatsapp:\+[1-9][0-9]{7,14}", value):
            raise ValueError("Use international format, for example +6591234567")
        return value


def install_channel_routes(app, factory, settings, authorise):
    @app.get("/api/channels/whatsapp")
    def state(request: Request):
        with factory() as db:
            _, _, clinics = authorise(db, request)
            if DEMO_CLINIC_ID not in clinics:
                raise HTTPException(403, "Test clinic access required")
            bindings = list(
                db.scalars(select(ChannelBinding).where(ChannelBinding.clinic_id == DEMO_CLINIC_ID))
            )
            binding = next((b for b in bindings if b.id == BINDING), None)
            outbox = db.scalars(
                select(ChannelOutbox)
                .where(ChannelOutbox.clinic_id == DEMO_CLINIC_ID)
                .order_by(ChannelOutbox.created_at.desc())
                .limit(20)
            )
            inbox = db.scalars(
                select(ChannelInbox)
                .where(ChannelInbox.clinic_id == DEMO_CLINIC_ID)
                .order_by(ChannelInbox.created_at.desc())
                .limit(20)
            )
            return {
                "configured": settings.whatsapp_enabled,
                "webhook_url": settings.public_origin + WEBHOOK,
                "case_id": binding.case_id if binding and binding.enabled else None,
                "bindings": [
                    {
                        "id": b.id,
                        "recipient": b.recipient,
                        "case_id": b.case_id,
                        "enabled": b.enabled,
                        "case_ids": [c.id for c in patient_cases(db, b)],
                        "window_open": bool(
                            b.inbound_at and as_utc(b.inbound_at) > utcnow() - timedelta(hours=23)
                        ),
                    }
                    for b in bindings
                ],
                "scope": "patient",
                "case_ids": [c.id for c in patient_cases(db, binding)]
                if binding and binding.enabled
                else [],
                "outgoing": [
                    {
                        "id": m.id,
                        "case_id": m.case_id,
                        "status": m.status,
                        "error": m.error_code,
                        "provider_sid": m.provider_sid,
                    }
                    for m in outbox
                ],
                "incoming": [
                    {"sid": m.sid, "case_id": m.case_id, "status": m.status} for m in inbox
                ],
            }

    @app.post("/api/channels/whatsapp/binding")
    def bind(body: BindingInput, request: Request):
        config = configuration(settings)
        if not config or not settings.simulation_configured:
            raise HTTPException(403, "WhatsApp test channel is not configured")
        with factory.begin() as db:
            _, session, clinics = authorise(db, request)
            if not secrets.compare_digest(
                digest(request.headers.get("X-CSRF-Token", "")), session.csrf_hash
            ):
                raise HTTPException(403, "Invalid CSRF token")
            # Serialize enrollment changes for this clinic, including first registrations.
            db.scalar(select(Clinic).where(Clinic.id == DEMO_CLINIC_ID).with_for_update())
            recipient = body.recipient or config.twilio_whatsapp_test_to
            binding = db.scalar(
                select(ChannelBinding)
                .where(
                    ChannelBinding.clinic_id == DEMO_CLINIC_ID,
                    ChannelBinding.id == body.binding_id
                    if body.binding_id
                    else ChannelBinding.recipient == recipient,
                )
                .with_for_update()
            )
            if body.binding_id and not binding:
                raise HTTPException(404, "Test phone not found")
            if binding:
                if body.recipient and body.recipient != binding.recipient:
                    raise HTTPException(
                        409, "Disconnect and register a new phone to change the number"
                    )
                recipient = binding.recipient
            case = db.scalar(
                select(FollowupCase)
                .where(
                    FollowupCase.id == body.case_id,
                    FollowupCase.clinic_id.in_(clinics),
                    FollowupCase.clinic_id == DEMO_CLINIC_ID,
                )
                .with_for_update()
            )
            if not case or not automation_authorised(db, case.clinic_id):
                raise HTTPException(404, "Synthetic case not available")
            if binding and binding.enabled and binding.case_id != case.id:
                raise HTTPException(409, "Disconnect the current case before selecting another")
            if body.enabled:
                for other in db.scalars(
                    select(ChannelBinding).where(
                        ChannelBinding.clinic_id == case.clinic_id, ChannelBinding.enabled.is_(True)
                    )
                ):
                    anchor = db.get(FollowupCase, other.case_id)
                    if other != binding and anchor and anchor.patient_id == case.patient_id:
                        raise HTTPException(
                            409, "This patient is already connected to another test phone"
                        )
            if db.scalar(
                select(ChannelOutbox.id)
                .where(ChannelOutbox.status == "sending", ChannelOutbox.recipient == recipient)
                .limit(1)
            ):
                raise HTTPException(
                    409, "A message is being sent; wait before changing the binding"
                )
            if not binding:
                binding = ChannelBinding(
                    id=BINDING
                    if recipient == config.twilio_whatsapp_test_to
                    and not db.get(ChannelBinding, BINDING)
                    else uid(),
                    clinic_id=case.clinic_id,
                    case_id=case.id,
                    recipient=recipient,
                )
                db.add(binding)
            if body.enabled and not binding.enabled:
                binding.created_at = utcnow()
                if binding.case_id != case.id:
                    binding.inbound_at = None
            if not body.enabled or not binding.enabled:
                routing = db.get(ChannelRoutingState, binding.id)
                if routing:
                    routing.data = {}
            binding.case_id, binding.enabled = case.id, body.enabled
            binding.recipient = recipient
            if not body.enabled:
                for message in db.scalars(
                    select(ChannelOutbox).where(
                        ChannelOutbox.status == "queued", ChannelOutbox.recipient == recipient
                    )
                ):
                    message.status = "canceled"
                for incoming in db.scalars(
                    select(ChannelInbox).where(ChannelInbox.status == "queued")
                ):
                    routing = db.get(ChannelRoutingState, incoming.sid)
                    if routing and routing.data.get("binding_id", BINDING) == binding.id:
                        incoming.status = "disconnected"
            return {"id": binding.id, "case_id": case.id, "enabled": binding.enabled}

    @app.post(WEBHOOK)
    async def inbound(request: Request):
        config = configuration(settings)
        if not config:
            raise HTTPException(404, "Channel disabled")
        if (
            request.url.query
            or request.headers.get("content-type", "").split(";")[0]
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(400, "Unsupported webhook format")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16000:
                raise HTTPException(413, "Webhook too large")
        try:
            values = FormData(
                parse_qsl(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=100)
            )
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid form") from None
        if not RequestValidator(config.twilio_auth_token.get_secret_value()).validate(
            settings.public_origin + WEBHOOK, values, request.headers.get("X-Twilio-Signature", "")
        ):
            raise HTTPException(403, "Invalid webhook signature")
        if any(
            len(values.getlist(k)) != 1 for k in ("AccountSid", "MessageSid", "From", "To", "Body")
        ):
            raise HTTPException(400, "Invalid message fields")
        if (
            values["AccountSid"] != config.twilio_account_sid
            or values["To"] != config.twilio_whatsapp_from
        ):
            raise HTTPException(403, "Test sender not allowed")
        sid, body = values["MessageSid"], values["Body"].strip()
        if not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
            raise HTTPException(400, "Invalid message identifier")
        with factory.begin() as db:
            binding = db.scalar(
                select(ChannelBinding)
                .where(
                    ChannelBinding.clinic_id == DEMO_CLINIC_ID,
                    ChannelBinding.recipient == values["From"],
                )
                .with_for_update()
            )
            if not binding:
                raise HTTPException(403, "Test sender not registered")
            if db.get(ChannelInbox, sid):
                return Response("<Response/>", media_type="application/xml")
            if not binding or not binding.enabled or not db.get(FollowupCase, binding.case_id):
                raise HTTPException(409, "Select a synthetic case before testing")
            reply_to = values.get("OriginalRepliedMessageSid")
            if reply_to and (
                len(values.getlist("OriginalRepliedMessageSid")) != 1
                or not re.fullmatch(r"SM[0-9a-fA-F]{32}", reply_to)
            ):
                raise HTTPException(400, "Invalid reply context")
            latest_sent = db.scalar(
                select(ChannelOutbox)
                .where(
                    ChannelOutbox.clinic_id == binding.clinic_id,
                    ChannelOutbox.recipient == binding.recipient,
                    ChannelOutbox.status.in_(["sent", "delivered", "read"]),
                )
                .order_by(ChannelOutbox.created_at.desc(), ChannelOutbox.id.desc())
                .limit(1)
            )
            if latest_sent:
                focus_delivered(db, latest_sent)
            db.add(
                ChannelRoutingState(
                    id=sid,
                    clinic_id=binding.clinic_id,
                    data={
                        "binding_id": binding.id,
                        "reply_to_sid": reply_to,
                        "active_case_id": conversation(db, binding).data.get("active_case_id"),
                    },
                )
            )
            binding.inbound_at = utcnow()
            db.add(
                ChannelInbox(
                    sid=sid,
                    clinic_id=binding.clinic_id,
                    case_id=binding.case_id,
                    body=body[:1600],
                    status="queued"
                    if body and len(body) <= 600 and values.get("NumMedia", "0") == "0"
                    else "needs_staff",
                )
            )
        return Response("<Response/>", media_type="application/xml")


def ingest_one(factory, settings=None, binding_id=None):
    if binding_id is None:
        with factory() as db:
            ids = list(
                db.scalars(
                    select(ChannelBinding.id)
                    .where(
                        ChannelBinding.enabled.is_(True), ChannelBinding.clinic_id == DEMO_CLINIC_ID
                    )
                    .order_by(ChannelBinding.id)
                )
            )
        for ident in ids:
            ingest_one(factory, settings, binding_id=ident)
        return
    with factory.begin() as db:
        binding = db.scalar(
            select(ChannelBinding)
            .where(ChannelBinding.id == binding_id, ChannelBinding.clinic_id == DEMO_CLINIC_ID)
            .with_for_update()
        )
        if not binding or not binding.enabled:
            return
        ids = [c.id for c in patient_cases(db, binding)]
        incoming = db.scalar(
            select(ChannelInbox)
            .where(
                ChannelInbox.status == "queued",
                ChannelInbox.clinic_id == binding.clinic_id,
                ChannelInbox.case_id.in_(ids),
            )
            .order_by(ChannelInbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not incoming:
            return
        context = db.get(ChannelRoutingState, incoming.sid)
        if context and context.data.get("binding_id", BINDING) != binding.id:
            incoming.status = "disconnected"
            return
        incoming = resolve_case(db, binding, incoming)
        if not incoming:
            return
        case = db.scalar(
            select(FollowupCase)
            .where(
                FollowupCase.id == incoming.case_id, FollowupCase.clinic_id == incoming.clinic_id
            )
            .with_for_update()
        )
        run = latest_run(db, incoming.case_id)
        if not case or not automation_authorised(db, incoming.clinic_id):
            incoming.status = "needs_staff"
            return
        if not run:
            return  # Foundation readiness will create the first review.
        if run.status in {"queued", "running"}:
            return
        if run.status == "completed":
            previous = run
            run = AgentRun(
                id=uid(),
                clinic_id=case.clinic_id,
                case_id=case.id,
                start_key=f"automatic:reply:{incoming.sid}",
                start_case_version=case.case_version,
                started_by=AUTOMATION_PRINCIPAL_ID,
                authorised_by=AUTOMATION_PRINCIPAL_ID,
                mode=settings.agent_model_mode if settings else previous.mode,
                goal=SIMULATOR_GOAL,
                checkpoint={"reopened_from_run_id": previous.id},
            )
            db.add(run)
            db.flush()
        elif run.status != "waiting":
            incoming.status = "needs_staff"
            handoff = db.scalar(
                select(StaffHandoff).where(
                    StaffHandoff.run_id == run.id, StaffHandoff.clinic_id == run.clinic_id
                )
            )
            staff_status = (
                "Clinic staff have accepted your request and it is awaiting their action. "
                if handoff and handoff.accepted_by
                else "Your request is awaiting assignment to clinic staff. "
            )
            if run.checkpoint.get("cancellation_request"):
                staff_status += "The appointment has not been cancelled yet. "
            staff_status += "I've saved your latest message for staff review; it has not changed your appointment."
            channel_notice(
                db,
                case,
                incoming,
                (
                    "I'm sorry, automated review is temporarily paused. Your message has been saved, "
                    "but I haven't recorded an attendance confirmation or changed your appointment from it."
                    if run.status == "paused"
                    else staff_status
                ),
            )
            return
        # This remains a synthetic test reply. Provider receipt verifies transport,
        # not a real patient's identity or consent. Existing tools remain synthetic.
        context = db.get(ChannelRoutingState, incoming.sid)
        reply_content = (context.data if context else {}).get("resolved_content", incoming.body)
        event_id = uid()
        db.add(
            AgentEvent(
                id=event_id,
                clinic_id=case.clinic_id,
                case_id=case.id,
                run_id=run.id,
                client_key=incoming.sid,
                actor_id=AUTOMATION_PRINCIPAL_ID,
                kind="demo_reply",
                content=reply_content,
                expected_case_version=case.case_version,
            )
        )
        abort_delegation(db, run)
        barriers = run.checkpoint.get("barriers")
        run.checkpoint = {
            **(
                {"reopened_from_run_id": run.checkpoint["reopened_from_run_id"]}
                if run.checkpoint.get("reopened_from_run_id")
                else {}
            ),
            "latest_event": {
                "id": event_id,
                "reply_event_id": event_id,
                "kind": "demo_reply",
                "content": reply_content,
                "channel": "whatsapp_test",
            },
            "returned_specialists": [],
            "delegation_start": 0,
            "patient_simulator_enabled": True,
            **({"barriers": barriers} if barriers else {}),
        }
        run.authorised_by, run.active_role = AUTOMATION_PRINCIPAL_ID, "coordinator"
        case.case_version += 1
        release(run, "queued", delay=0)
        if settings and not settings.model_configured:
            run.checkpoint = {**run.checkpoint, "pause_reason": "MODEL_NOT_CONFIGURED"}
            release(run, "paused")
            channel_notice(
                db,
                case,
                incoming,
                "I've received your message. Automated review is unavailable; clinic staff need to review it.",
            )
        incoming.status, incoming.event_id = "processed", event_id


def collect_messages(factory, binding_id=None):
    if binding_id is None:
        with factory() as db:
            ids = list(
                db.scalars(
                    select(ChannelBinding.id)
                    .where(
                        ChannelBinding.enabled.is_(True), ChannelBinding.clinic_id == DEMO_CLINIC_ID
                    )
                    .order_by(ChannelBinding.id)
                )
            )
        for ident in ids:
            collect_messages(factory, binding_id=ident)
        return
    with factory.begin() as db:
        binding = db.scalar(
            select(ChannelBinding)
            .where(ChannelBinding.id == binding_id, ChannelBinding.clinic_id == DEMO_CLINIC_ID)
            .with_for_update()
        )
        if not binding or not binding.enabled or not db.get(FollowupCase, binding.case_id):
            return
        ids = [c.id for c in patient_cases(db, binding)]
        # Same patient, new episodes included; never replay history predating enrollment.
        for message in db.scalars(
            select(SimulatedMessage)
            .where(
                SimulatedMessage.case_id.in_(ids),
                SimulatedMessage.clinic_id == binding.clinic_id,
                SimulatedMessage.created_at >= binding.created_at,
            )
            .order_by(SimulatedMessage.created_at)
        ):
            if message.translation and message.translation.get("status") != "ready":
                continue
            if not db.scalar(
                select(ChannelOutbox.id).where(ChannelOutbox.message_id == message.id)
            ):
                db.add(
                    ChannelOutbox(
                        message_id=message.id,
                        clinic_id=binding.clinic_id,
                        case_id=message.case_id,
                        recipient=binding.recipient,
                        body=message.translation["body"] if message.translation else message.body,
                    )
                )


def dispatch_one(factory, client, binding_id=None):
    if binding_id is None:
        with factory() as db:
            registered = {
                b.recipient: b.id
                for b in db.scalars(
                    select(ChannelBinding).where(
                        ChannelBinding.enabled.is_(True), ChannelBinding.clinic_id == DEMO_CLINIC_ID
                    )
                )
            }
            ids = list(
                dict.fromkeys(
                    registered[r]
                    for r in db.scalars(
                        select(ChannelOutbox.recipient)
                        .where(ChannelOutbox.status == "queued")
                        .order_by(ChannelOutbox.created_at, ChannelOutbox.id)
                    )
                    if r in registered
                )
            )
        for ident in ids:
            if dispatch_one(factory, client, binding_id=ident):
                return True
        return
    now = utcnow()
    with factory.begin() as db:
        binding = db.scalar(
            select(ChannelBinding)
            .where(ChannelBinding.id == binding_id, ChannelBinding.clinic_id == DEMO_CLINIC_ID)
            .with_for_update()
        )
        if (
            not binding
            or not binding.enabled
            or not binding.inbound_at
            or as_utc(binding.inbound_at) < now - timedelta(hours=23)
        ):
            return
        allowed = getattr(client, "allowed_recipients", None)
        if allowed is not None and binding.recipient not in allowed:
            return  # A newly enrolled phone will enter the next tick's allowlist.
        ids = [c.id for c in patient_cases(db, binding)]
        message = db.scalar(
            select(ChannelOutbox)
            .where(
                ChannelOutbox.status == "queued",
                ChannelOutbox.case_id.in_(ids),
                ChannelOutbox.clinic_id == binding.clinic_id,
                ChannelOutbox.recipient == binding.recipient,
            )
            .order_by(ChannelOutbox.created_at, ChannelOutbox.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not message:
            return
        if not db.get(FollowupCase, message.case_id):
            message.status = "canceled"
            return
        message.status, message.updated_at = "sending", now
        message_id, recipient, body = message.id, message.recipient, message.body
    # Commit before HTTP. A crash or ambiguous response must never cause a resend.
    try:
        receipt = client.send_text(recipient, body)
        state, code, sid = (
            receipt.status,
            str(receipt.error_code) if receipt.error_code else None,
            receipt.sid,
        )
        if state in {"queued", "sending"}:
            state = "provider_" + state
    except WhatsAppError as exc:
        state, code, sid = "uncertain" if exc.delivery_uncertain else "failed", exc.code, None
    with factory.begin() as db:
        message = db.get(ChannelOutbox, message_id)
        if message:
            message.status, message.error_code, message.provider_sid = state, code, sid
            message.updated_at = utcnow()
            focus_delivered(db, message)

    return True


def focus_delivered(db, message):
    """Only successful patient-facing dispatch establishes conversational focus."""
    if message.status not in {"sent", "delivered", "read"}:
        return
    binding = db.scalar(
        select(ChannelBinding)
        .where(
            (ChannelBinding.recipient == message.recipient)
            & (ChannelBinding.clinic_id == message.clinic_id)
        )
        .with_for_update()
    )
    if (
        not binding
        or not binding.enabled
        or message.recipient != binding.recipient
        or message.case_id not in {c.id for c in patient_cases(db, binding)}
    ):
        return
    latest = db.scalar(
        select(ChannelOutbox)
        .where(
            ChannelOutbox.clinic_id == binding.clinic_id,
            ChannelOutbox.recipient == binding.recipient,
            ChannelOutbox.status.in_(["sent", "delivered", "read"]),
        )
        .order_by(ChannelOutbox.created_at.desc(), ChannelOutbox.id.desc())
        .limit(1)
    )
    source = db.get(SimulatedMessage, message.message_id)
    if not latest or latest.id != message.id or (source and source.kind == "channel_routing"):
        return
    state = conversation(db, binding)
    if not state.data.get("pending_sid") and state.data.get("focus_message_id") != message.id:
        state.data = {
            **state.data,
            "active_case_id": message.case_id,
            "focus_message_id": message.id,
        }


def poll_delivery(factory, client):
    with factory.begin() as db:
        # Crashes after dispatch are visible, not automatically retried.
        for item in db.scalars(
            select(ChannelOutbox).where(
                ChannelOutbox.status == "sending",
                ChannelOutbox.updated_at < utcnow() - timedelta(minutes=2),
            )
        ):
            item.status, item.error_code = "uncertain", "DISPATCH_INTERRUPTED"
        item = db.scalar(
            select(ChannelOutbox)
            .where(
                ChannelOutbox.provider_sid.is_not(None),
                ChannelOutbox.status.in_(
                    ["provider_queued", "provider_sending", "accepted", "sent"]
                ),
                ChannelOutbox.updated_at < utcnow() - timedelta(seconds=15),
            )
            .order_by(ChannelOutbox.updated_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not item:
            return
        item.updated_at = utcnow()
        sid, ident = item.provider_sid, item.id
    try:
        receipt = client.message_status(sid)
    except WhatsAppError:
        return
    with factory.begin() as db:
        item = db.get(ChannelOutbox, ident)
        if item:
            item.status = (
                "provider_" + receipt.status
                if receipt.status in {"queued", "sending"}
                else receipt.status
            )
            item.error_code = str(receipt.error_code) if receipt.error_code else None
            focus_delivered(db, item)


def channel_tick(factory, settings):
    config = configuration(settings)
    if not config:
        return
    ingest_one(factory, settings)
    collect_messages(factory)
    with factory() as db:
        recipients = list(
            db.scalars(
                select(ChannelBinding.recipient).where(
                    ChannelBinding.enabled.is_(True), ChannelBinding.clinic_id == DEMO_CLINIC_ID
                )
            )
        )
    client = WhatsAppClient(config, allowed_recipients=recipients)
    # Shared Sandbox sender permits one send per three seconds across all phones.
    with factory.begin() as db:
        db.scalar(select(Clinic).where(Clinic.id == DEMO_CLINIC_ID).with_for_update())
        clock = db.get(ChannelRoutingState, "whatsapp-send-clock")
        now = utcnow().timestamp()
        send_allowed = not clock or now - clock.data.get("reserved_at", 0) >= 3
        if send_allowed:
            if not clock:
                clock = ChannelRoutingState(id="whatsapp-send-clock", clinic_id=DEMO_CLINIC_ID)
                db.add(clock)
            clock.data = {"reserved_at": now}
    if send_allowed:
        dispatch_one(factory, client)
    poll_delivery(factory, client)
