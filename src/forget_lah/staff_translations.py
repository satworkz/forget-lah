"""Display-only English translations; never workflow input or outbound messages."""

from datetime import timedelta

from sqlalchemy import select

from forget_lah.db import utcnow
from forget_lah.runtime.budget import reserve_call
from forget_lah.runtime.models import AgentEvent, AgentRun
from forget_lah.runtime.provider import ModelError
from forget_lah.translations import translate


def initial_translation(settings, kind):
    if kind == "demo_reply" and settings and settings.translation_configured:
        return {"language": "en", "status": "pending"}
    return None


def translate_staff_one(factory, settings, *, translator=translate):
    if not settings.translation_configured:
        return
    with factory.begin() as db:
        rows = db.scalars(
            select(AgentEvent)
            .join(AgentRun, AgentRun.id == AgentEvent.run_id)
            .where(
                AgentEvent.kind == "demo_reply",
                AgentRun.status.in_(["waiting", "paused", "escalated", "completed"]),
                AgentEvent.staff_translation["status"].as_string().in_(["pending", "processing"]),
            )
            .order_by(AgentEvent.created_at, AgentEvent.id)
            .limit(100)
            .with_for_update(skip_locked=True, of=AgentEvent)
        )
        event = None
        for row in rows:
            data = row.staff_translation or {}
            if (
                data.get("status") == "processing"
                and data.get("started_at", "") < (utcnow() - timedelta(minutes=2)).isoformat()
            ):
                row.staff_translation = {
                    **data,
                    "status": "failed",
                    "error": "TRANSLATION_INTERRUPTED",
                }
            if data.get("status") == "pending":
                event = row
                break
        if event is None:
            return
        code, _ = reserve_call(db, settings)
        if code:
            if code != "MODEL_PACING":
                event.staff_translation = {"language": "en", "status": "failed", "error": code}
            return
        event_id, original = event.id, event.content
        claim = {"language": "en", "status": "processing", "started_at": utcnow().isoformat()}
        event.staff_translation = claim
    try:
        body = translator(settings, original, "en")
        result = {"language": "en", "status": "ready", "body": body, "provider": "anthropic"}
    except ModelError as exc:
        result = {"language": "en", "status": "failed", "error": exc.code}
    with factory.begin() as db:
        event = db.scalar(select(AgentEvent).where(AgentEvent.id == event_id).with_for_update())
        if event and event.content == original and event.staff_translation == claim:
            event.staff_translation = result
