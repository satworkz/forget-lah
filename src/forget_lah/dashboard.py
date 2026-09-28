"""Read-only source inventory; viewing a record never starts a follow-up."""

import hashlib

import httpx
from fastapi import Request
from sqlalchemy import select

from forget_lah.bridge import _candidate
from forget_lah.db import BridgeEpisode, FollowupCase, Membership, Patient, utcnow
from forget_lah.detector import trigger_for
from forget_lah.runtime.routes import latest_run
from forget_lah.security import mask_name
from forget_lah.source import DEMO_CLINIC_ID, read_candidates


def install_dashboard_routes(app, factory, settings, authorise):
    @app.get("/api/dashboard/records")
    def records(request: Request):
        with factory() as db:
            user, _, clinics = authorise(db, request)
            roles = dict(
                db.execute(
                    select(Membership.clinic_id, Membership.role).where(
                        Membership.principal_id == user.id,
                        Membership.active.is_(True),
                        Membership.clinic_id.in_(clinics),
                    )
                ).all()
            )
            warnings, sources = [], []
            if DEMO_CLINIC_ID in clinics:
                try:
                    sources.extend(
                        (DEMO_CLINIC_ID, "Clinic System", c)
                        for c in read_candidates(settings.mock_clinic_url)
                    )
                except (httpx.HTTPError, ValueError):
                    warnings.append(
                        "Clinic System is unavailable. Its full record list could not be refreshed."
                    )
            for episode in db.scalars(
                select(BridgeEpisode).where(BridgeEpisode.clinic_id.in_(clinics))
            ):
                try:
                    sources.append((episode.clinic_id, "Intelligent Intake", _candidate(episode)))
                except (ValueError, TypeError):
                    warnings.append(
                        "An imported record needs data review and could not be displayed."
                    )
            cases = {
                (c.clinic_id, c.source_episode_ref): (c, name)
                for c, name in db.execute(
                    select(FollowupCase, Patient.display_alias)
                    .join(
                        Patient,
                        (Patient.id == FollowupCase.patient_id)
                        & (Patient.clinic_id == FollowupCase.clinic_id),
                    )
                    .where(FollowupCase.clinic_id.in_(clinics))
                )
            }
            now, result, seen = utcnow(), [], set()

            def add(clinic, origin, candidate, case, name):
                run = latest_run(db, case.id) if case else None
                agent_status = run.status if run else None
                trigger = trigger_for(candidate, now) if candidate else None
                when = candidate.scheduled_at or candidate.due_at if candidate else None
                past = bool(
                    candidate and candidate.source_status == "scheduled" and when and when < now
                )
                needs_staff = agent_status in {"escalated", "paused"}
                attention = needs_staff or past or bool(trigger and agent_status != "completed")
                reason = (
                    "Staff review required"
                    if needs_staff
                    else "Past appointment — verify status"
                    if past
                    else "Follow-up completed"
                    if agent_status == "completed"
                    else {
                        "UPCOMING": "Due within 7 days",
                        "MISSED": "Missed appointment",
                        "RECALL_OVERDUE": "Overdue recall",
                    }.get(trigger)
                    or (
                        "Outside follow-up window"
                        if candidate and candidate.source_status in {"scheduled", "due"}
                        else "No current follow-up required"
                    )
                )
                result.append(
                    {
                        "key": hashlib.sha256(
                            f"{clinic}:{candidate.source_episode_ref if candidate else case.source_episode_ref}".encode()
                        ).hexdigest(),
                        "patient": mask_name(name) if roles.get(clinic) == "viewer" else name,
                        "specialty": candidate.specialty if candidate else case.specialty,
                        "source": origin,
                        "source_status": candidate.source_status if candidate else "unavailable",
                        "appointment_at": when.isoformat() if when else None,
                        "requires_attention": attention,
                        "reason": reason,
                        "case_id": case.id if case else None,
                        "trigger": case.trigger if case else trigger or "NOT_DUE",
                        "agent_status": agent_status,
                    }
                )

            for clinic, origin, candidate in sources:
                key = (clinic, candidate.source_episode_ref)
                if key in seen:
                    continue
                seen.add(key)
                case, _ = cases.get(key, (None, None))
                add(clinic, origin, candidate, case, candidate.display_alias)
            for key, (case, name) in cases.items():
                if key not in seen:
                    add(case.clinic_id, "Saved follow-up", None, case, name)
            result.sort(
                key=lambda r: (not r["requires_attention"], r["appointment_at"] or "", r["patient"])
            )
            return {"records": result, "warnings": list(dict.fromkeys(warnings))}
