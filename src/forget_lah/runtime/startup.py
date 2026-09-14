"""Queue each ready demo case once; database locks serialize competing starters."""

from sqlalchemy import select

from forget_lah.db import FollowupCase, Job, Membership, Principal, uid
from forget_lah.runtime.models import AgentRun
from forget_lah.service_identity import AUTOMATION_PRINCIPAL_ID
from forget_lah.source import DEMO_CLINIC_ID

REVIEW_GOAL = (
    "Coordinate the follow-up: delegate to Engagement and Preparation as needed, "
    "review their evidence, and decide the next action. Complete only after named staff acceptance."
)
SIMULATOR_GOAL = (
    "Coordinate follow-up with Engagement and Preparation. Complete a simulated attendance "
    "confirmation only after source receipt and acknowledgement evidence; otherwise reach an owned staff handoff."
)


def automation_authorised(db, clinic_id):
    # This release provisions automation for the synthetic demo clinic only.
    return (
        clinic_id == DEMO_CLINIC_ID
        and db.scalar(
            select(Membership.id)
            .join(Principal)
            .where(
                Principal.id == AUTOMATION_PRINCIPAL_ID,
                Principal.active.is_(True),
                Membership.clinic_id == clinic_id,
                Membership.active.is_(True),
            )
        )
        is not None
    )


def queue_case_review(db, case, settings):
    """Caller holds the case lock; the run and readiness commit together."""
    if not settings.agent_auto_start_enabled or not automation_authorised(db, case.clinic_id):
        return None
    if db.scalar(select(AgentRun.id).where(AgentRun.case_id == case.id).limit(1)):
        return None  # Completed/paused/historical reviews are not restarted automatically.
    run_id = uid()
    configured = settings.model_configured
    checkpoint = {
        "latest_event": {"id": run_id, "kind": "started", "content": ""},
        "returned_specialists": [],
        "patient_simulator_enabled": settings.simulation_configured,
    }
    if not configured:
        checkpoint["pause_reason"] = "MODEL_NOT_CONFIGURED"
    run = AgentRun(
        id=run_id,
        clinic_id=case.clinic_id,
        case_id=case.id,
        # ':' is not allowed in staff API idempotency keys. The reserved key
        # records provenance permanently, even after checkpoint replacement.
        start_key=f"automatic:{case.id}",
        start_case_version=case.case_version,
        started_by=AUTOMATION_PRINCIPAL_ID,
        authorised_by=AUTOMATION_PRINCIPAL_ID,
        mode=settings.agent_model_mode,
        status="queued" if configured else "paused",
        goal=SIMULATOR_GOAL if settings.simulation_configured else REVIEW_GOAL,
        checkpoint=checkpoint,
    )
    db.add(run)
    case.case_version += 1
    db.flush()
    return run


def queue_ready_reviews(factory, settings):
    """Recover older ready cases and interruptions without requiring a browser."""
    if not settings.agent_auto_start_enabled:
        return 0
    with factory.begin() as db:
        if not automation_authorised(db, DEMO_CLINIC_ID):
            return 0
        cases = list(
            db.scalars(
                select(FollowupCase)
                .where(
                    FollowupCase.clinic_id == DEMO_CLINIC_ID,
                    select(Job.id)
                    .where(Job.case_id == FollowupCase.id, Job.status == "done")
                    .exists(),
                    ~select(AgentRun.id).where(AgentRun.case_id == FollowupCase.id).exists(),
                )
                .order_by(FollowupCase.created_at, FollowupCase.id)
                .with_for_update(skip_locked=True)
                .limit(50)
            )
        )
        return sum(queue_case_review(db, case, settings) is not None for case in cases)
