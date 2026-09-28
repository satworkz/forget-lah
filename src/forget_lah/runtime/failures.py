"""Durable case-bound recovery; never repeats a denied or uncertain source action."""

from sqlalchemy import or_, select

from forget_lah.db import FollowupCase, SecurityEvent
from forget_lah.runtime.memory import effective_memory
from forget_lah.runtime.models import AgentRun, AgentStep, SimulatedMessage, StaffHandoff
from forget_lah.runtime.policy import has_authority
from forget_lah.runtime.simulation import saved_reply

FAILURE_CODES = {
    "POLICY_DENIED",
    "STEP_BUDGET_EXHAUSTED",
    "ROLE_BUDGET_EXHAUSTED",
    "UNEXPECTED_WORKFLOW_ERROR",
    "STALE_CHECKPOINT",
    "STALE_OR_REVOKED_CONTEXT",
    "SIMULATOR_DISABLED",
}


NOTICES = {
    "en": "I couldn't complete your request safely. I've sent it to the clinic team for review. Please check with the clinic before assuming an appointment change has been completed.",
    "ms": "Saya tidak dapat menyelesaikan permintaan anda dengan selamat. Saya telah menghantarnya kepada pasukan klinik untuk semakan. Sila semak dengan klinik sebelum menganggap perubahan temu janji telah selesai.",
    "zh": "我无法安全地完成您的请求，已将请求提交给诊所团队审核。请先向诊所确认，不要假定预约更改已经完成。",
    "ta": "உங்கள் கோரிக்கையைப் பாதுகாப்பாக நிறைவேற்ற முடியவில்லை. பரிசீலனைக்காக அதைக் கிளினிக் குழுவிற்கு அனுப்பியுள்ளேன். சந்திப்பு மாற்றம் நிறைவடைந்ததாகக் கருதுவதற்கு முன் கிளினிக்கிடம் உறுதிப்படுத்தவும்.",
}


def escalate_failure(factory, settings, run_id, *, unexpected_token=None):
    from forget_lah.runtime.engine import pause, request_handoff

    with factory.begin() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if not run or not has_authority(db, run):
            return False
        case = db.scalar(
            select(FollowupCase).where(
                FollowupCase.id == run.case_id, FollowupCase.clinic_id == run.clinic_id
            )
        )
        if not case:
            return False
        latest = db.scalar(
            select(AgentRun.id)
            .where(AgentRun.case_id == run.case_id, AgentRun.clinic_id == run.clinic_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        if latest != run.id:
            return False
        if unexpected_token is not None:
            if run.status != "running" or run.lease_token != unexpected_token:
                return False
            step = db.scalar(
                select(AgentStep)
                .where(AgentStep.run_id == run.id)
                .order_by(AgentStep.sequence.desc())
                .limit(1)
            )
            if step and step.status in {"pending", "tool_pending"}:
                step.error_code = "UNEXPECTED_WORKFLOW_ERROR"
                step.status = "error"
            pause(run, "UNEXPECTED_WORKFLOW_ERROR")
        code = run.checkpoint.get("pause_reason") or ""
        recoverable = code.startswith(("MODEL_", "SOURCE_")) or code in FAILURE_CODES
        reply = saved_reply(db, run)
        if run.status == "escalated":
            handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
            if (
                not handoff
                or handoff.accepted_by
                or not reply
                or db.scalar(
                    select(SimulatedMessage.id).where(
                        SimulatedMessage.run_id == run.id, SimulatedMessage.event_id == reply.id
                    )
                )
                or run.checkpoint.get("failure_review")
            ):
                return False
            code = handoff.reason_code
        else:
            if run.status != "paused" or not recoverable or code == "MODEL_MODE_CHANGED":
                return False
            request_handoff(db, run, "AUTOMATION_REVIEW_REQUIRED", risk="AMBER")
        memory = effective_memory(db, case)
        language = memory.get("preferred_language", "en")
        blocked = (
            not settings.patient_simulator_enabled
            or not reply
            or memory.get("contact_permission") == "stopped"
            or language not in NOTICES
            or language in memory.get("excluded_languages", [])
        )
        run.checkpoint = {
            **run.checkpoint,
            "failure_review": {"code": code, "notice": "withheld" if blocked else "queued"},
        }
        if not blocked:
            notice = NOTICES["en"]
            if language == "en" and run.checkpoint.get("appointment_status_review_required"):
                notice = "Your original appointment time has passed. The clinic team needs to check its status before arranging a change. I've sent your request for staff review. No appointment change has been made."
            # Static translations remain usable when the model is unavailable.
            # Existing channel enrollment/consent and delivery retries still apply.
            db.add(
                SimulatedMessage(
                    clinic_id=run.clinic_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    event_id=reply.id,
                    kind="failure_acknowledgement",
                    body=notice,
                    translation={
                        "language": language,
                        "status": "ready",
                        "body": NOTICES[language],
                        "provider": "static",
                    }
                    if language != "en"
                    else None,
                    source_version="failure-handoff-v1",
                    evidence={
                        "reason_code": code,
                        "origin": "rule",
                        "staff_review_requested": True,
                    },
                )
            )
        db.add(
            SecurityEvent(
                clinic_id=run.clinic_id,
                resource_id=run.case_id,
                action="automation_failure_handoff",
                decision="ESCALATE",
                details={
                    "run_id": run.id,
                    "code": code,
                    "notice": "withheld" if blocked else "queued",
                },
            )
        )
        return True


def recover_paused_failures(factory, settings):
    """Recover persisted terminal failures even after a process dies between commits."""
    with factory() as db:
        code = AgentRun.checkpoint["pause_reason"].as_string()
        ids = list(
            db.scalars(
                select(AgentRun.id)
                .where(
                    AgentRun.status == "paused",
                    or_(
                        code.startswith("MODEL_"),
                        code.startswith("SOURCE_"),
                        code.in_(FAILURE_CODES),
                    ),
                    code != "MODEL_MODE_CHANGED",
                )
                .order_by(AgentRun.created_at)
                .limit(50)
            )
        )
    return sum(escalate_failure(factory, settings, ident) for ident in ids)
