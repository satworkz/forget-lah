"""Deterministic access policy and bounded, secret-free security evidence."""

import logging
import re
from datetime import timedelta

from sqlalchemy import func, select

from forget_lah.db import SecurityEvent, utcnow

log = logging.getLogger(__name__)
SUMMARY_PATHS = {"/api/me", "/api/cases", "/api/system"}


def allowed_roles(request):
    if request.url.path == "/api/auth/logout":
        return {"staff", "admin", "auditor", "viewer"}
    if request.method in {"GET", "HEAD"}:
        return (
            {"staff", "admin", "auditor", "viewer"}
            if request.url.path in SUMMARY_PATHS
            else {"staff", "admin", "auditor"}
        )
    return {"staff", "admin"}


def mask_identifier(value):
    return "••••" + str(value)[-4:] if value else value


def mask_name(value):
    return " ".join(part[:1] + "•••" for part in value.split())


def model_context(value, role):
    """Keep clinical/task evidence; strip structured identity and transport metadata."""
    excluded = {
        "clinic_id",
        "patient_id",
        "source_episode_ref",
        "run_id",
        "phone",
        "recipient",
        "patient_name",
        "display_alias",
        "email",
        "password",
        "api_key",
        "token",
        "authorization",
    }
    if role in {"coordinator", "preparation"}:
        excluded.add("available_slots")
    if isinstance(value, dict):
        return {k: model_context(v, role) for k, v in value.items() if k.lower() not in excluded}
    if isinstance(value, list):
        return [model_context(v, role) for v in value]
    return value


def safe_details(value):
    """Defence in depth for displayed audit metadata; never expose credentials."""
    if isinstance(value, dict):
        return {
            k: (
                "[redacted]"
                if any(
                    term in k.lower()
                    for term in ("password", "secret", "token", "api_key", "authorization")
                )
                else safe_details(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [safe_details(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(bearer\s+|sk-ant-)[\w.-]+", "[redacted]", value)
    return value


def record_action(db, *, clinic_id, actor_id, resource_id, action, details):
    db.add(
        SecurityEvent(
            clinic_id=clinic_id,
            actor_id=actor_id,
            resource_id=resource_id,
            action=action,
            decision="allowed",
            details=safe_details(details),
        )
    )


def record_denial(factory, request, status):
    route = getattr(request.scope.get("route"), "path", "unmatched")
    action = f"{request.method} {route}"[:120]
    actor = getattr(request.state, "security_actor", None)
    clinics = getattr(request.state, "security_clinics", [])
    # Do not record submitted bodies, raw URLs, query strings, cookies or headers.
    with factory.begin() as db:
        recent = db.scalar(
            select(func.count())
            .select_from(SecurityEvent)
            .where(
                SecurityEvent.actor_id == actor,
                SecurityEvent.action == action,
                SecurityEvent.created_at >= utcnow() - timedelta(minutes=5),
                SecurityEvent.decision == "denied",
            )
        )
        db.add(
            SecurityEvent(
                clinic_id=clinics[0] if len(clinics) == 1 else None,
                actor_id=actor,
                action=action,
                decision="denied",
                details={
                    "http_status": status,
                    "repeated": recent >= 2,
                    "category": "invalid_upload"
                    if request.url.path == "/api/bridge/analyse" and status in {413, 422}
                    else "access_denied",
                },
            )
        )
    log.warning("security_event action=%s status=%s repeated=%s", action, status, recent >= 2)
