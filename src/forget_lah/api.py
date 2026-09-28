import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from forget_lah.agents import AGENT_CATALOG
from forget_lah.auth import authenticate, digest, session_principal
from forget_lah.bridge import install_bridge_routes
from forget_lah.channel import WEBHOOK, install_channel_routes
from forget_lah.db import (
    AuditEvent,
    Clinic,
    FollowupCase,
    Membership,
    Patient,
    make_engine,
    session_factory,
)
from forget_lah.demo_reset import demo_reset_cases, install_demo_routes, reset_enabled
from forget_lah.runtime.models import AgentRun
from forget_lah.runtime.routes import install_routes, latest_run
from forget_lah.security import allowed_roles, mask_identifier, mask_name, record_denial
from forget_lah.settings import Settings
from forget_lah.simulator import install_simulator_routes


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class LoginLimiter:
    """Local, single-process foundation limit; replace with shared limits before scaling."""

    def __init__(self):
        self.events = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, address: str) -> bool:
        now = time.monotonic()
        with self.lock:
            if address not in self.events and len(self.events) >= 1000:
                self.events = defaultdict(
                    deque,
                    {
                        key: value
                        for key, value in self.events.items()
                        if value and value[-1] > now - 60
                    },
                )
                if len(self.events) >= 1000:
                    return False
            events = self.events[address]
            while events and events[0] < now - 60:
                events.popleft()
            if len(events) >= 10:
                return False
            events.append(now)
            return True


def create_app(settings: Settings | None = None, engine=None, bridge_analyzer=None) -> FastAPI:
    settings = settings or Settings()
    owns_engine = engine is None
    engine = engine or make_engine(settings.database_url.get_secret_value())
    factory = session_factory(engine)

    @asynccontextmanager
    async def lifespan(_):
        yield
        if owns_engine:
            engine.dispose()

    app = FastAPI(
        title="forget-lah",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    limiter = LoginLimiter()

    async def unexpected_error(request: Request, exc: Exception):
        # An unbound HTTP failure is not authority to send a patient message.
        return JSONResponse(
            {
                "detail": "Unable to complete this request. Please try again or contact clinic staff."
            },
            status_code=500,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        # Driver errors may embed identifiers or bound values. Do not echo or log them.
        return JSONResponse({"detail": "Database operation unavailable"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/simulator"):
            issues = [
                f"{'.'.join(str(p) for p in item['loc'][1:]) or 'Record'}: {item['msg']}"
                for item in exc.errors()[:4]
            ]
            return JSONResponse(
                {"detail": "Please check the form. " + "; ".join(issues)}, status_code=422
            )
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        if request.url.path == "/api/bridge/analyse":
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2_110_000:
                    record_denial(factory, request, 413)
                    return JSONResponse({"detail": "Upload request too large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path != WEBHOOK:
            if request.headers.get("origin") != settings.public_origin:
                record_denial(factory, request, 403)
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        response = await call_next(request)
        if response.status_code in {401, 403, 404, 413, 422, 429} and request.url.path.startswith(
            "/api/"
        ):
            record_denial(factory, request, response.status_code)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.middleware("http")
    async def safe_error_boundary(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            # Catch before ServerErrorMiddleware can log raw exception values.
            response = await unexpected_error(request, exc)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

    def authorise(db, request):
        identity = session_principal(db, request.cookies.get("forget_lah_session"))
        if not identity:
            raise HTTPException(401, "Please sign in")
        user, session = identity
        request.state.security_actor = user.id
        request.state.security_clinics = list(
            db.scalars(
                select(Membership.clinic_id).where(
                    Membership.principal_id == user.id, Membership.active.is_(True)
                )
            )
        )
        memberships = list(
            db.scalars(
                select(Membership.clinic_id).where(
                    Membership.principal_id == user.id,
                    Membership.active.is_(True),
                    Membership.role.in_(allowed_roles(request)),
                )
            )
        )
        if not memberships:
            raise HTTPException(403, "No permitted clinic role")
        return user, session, memberships

    @app.get("/health/live")
    def live():
        return {"status": "ok", "version": "0.2.0"}

    @app.get("/health/ready")
    def ready():
        try:
            with factory() as db:
                if db.scalar(text("SELECT version_num FROM alembic_version")) != "0017":
                    raise ValueError("Agent migration is required")
                db.execute(select(Clinic.id).limit(1))
                db.execute(select(AgentRun.id).limit(1))
            return {"status": "ready"}
        except Exception as exc:
            raise HTTPException(503, "Database or migrations unavailable") from exc

    @app.post("/api/auth/login")
    def login(body: LoginInput, request: Request, response: Response):
        if not limiter.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(429, "Too many attempts; wait one minute")
        result = authenticate(factory, body.email, body.password, settings.session_hours)
        if not result:
            raise HTTPException(401, "Invalid credentials")
        token, csrf = result
        response.set_cookie(
            "forget_lah_session",
            token,
            httponly=True,
            samesite="strict",
            secure=settings.public_origin.startswith("https:"),
            max_age=settings.session_hours * 3600,
            path="/",
        )
        response.set_cookie(
            "forget_lah_csrf",
            csrf,
            httponly=False,
            samesite="strict",
            secure=settings.public_origin.startswith("https:"),
            max_age=settings.session_hours * 3600,
            path="/",
        )
        return {"csrf_token": csrf}

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response):
        with factory.begin() as db:
            _, session, _ = authorise(db, request)
            supplied = digest(request.headers.get("X-CSRF-Token", ""))
            if not secrets.compare_digest(supplied, session.csrf_hash):
                raise HTTPException(403, "Invalid CSRF token")
            db.delete(session)
        response.delete_cookie("forget_lah_session", path="/")
        response.delete_cookie("forget_lah_csrf", path="/")

    @app.get("/api/me")
    def me(request: Request):
        with factory() as db:
            user, _, clinics = authorise(db, request)
            return {"email": user.email, "clinic_ids": clinics}

    @app.get("/api/system")
    def system(request: Request):
        with factory() as db:
            _, _, clinics = authorise(db, request)
            demo_reset = reset_enabled(settings, clinics)
            demo_case_ids = [case.id for case in demo_reset_cases(db)] if demo_reset else []
            from forget_lah.db import BridgeIntakeBatch
            from forget_lah.source import DEMO_CLINIC_ID

            intake_case_ids = (
                [
                    case.id
                    for case in demo_reset_cases(db, include_intake=True)
                    if case.id not in demo_case_ids
                ]
                if demo_reset
                else []
            )
            intake_batch_ids = (
                list(
                    db.scalars(
                        select(BridgeIntakeBatch.id).where(
                            BridgeIntakeBatch.clinic_id == DEMO_CLINIC_ID
                        )
                    )
                )
                if demo_reset
                else []
            )
        return {
            "demo_reset_enabled": demo_reset,
            "demo_reset_case_ids": demo_case_ids,
            "demo_reset_intake_case_ids": intake_case_ids,
            "demo_reset_intake_batch_ids": intake_batch_ids,
            "milestone": "M2a agent runtime",
            "data_mode": "synthetic",
            "model_mode": settings.agent_model_mode,
            "model_configured": settings.model_configured,
            "outreach_enabled": False,
            "agents": [{**agent, "status": settings.agent_model_mode} for agent in AGENT_CATALOG],
        }

    from forget_lah.dashboard import install_dashboard_routes

    install_dashboard_routes(app, factory, settings, authorise)

    @app.get("/api/cases")
    def list_cases(request: Request):
        with factory() as db:
            user, _, clinics = authorise(db, request)
            rows = db.execute(
                select(FollowupCase, Patient.display_alias, Membership.role)
                .join(
                    Patient,
                    (Patient.id == FollowupCase.patient_id)
                    & (Patient.clinic_id == FollowupCase.clinic_id),
                )
                .join(
                    Membership,
                    (Membership.clinic_id == FollowupCase.clinic_id)
                    & (Membership.principal_id == user.id)
                    & Membership.active.is_(True),
                )
                .where(FollowupCase.clinic_id.in_(clinics))
                .order_by(FollowupCase.created_at)
                .limit(200)
            )
            return [
                {
                    "id": case.id,
                    "patient": mask_name(alias) if role == "viewer" else alias,
                    "specialty": case.specialty,
                    "trigger": case.trigger,
                    "state": case.state,
                    "source_episode_ref": mask_identifier(case.source_episode_ref),
                    "case_version": case.case_version,
                    "agent_status": (run.status if (run := latest_run(db, case.id)) else None),
                }
                for case, alias, role in rows
            ]

    @app.get("/api/cases/{case_id}/events")
    def case_events(case_id: str, request: Request):
        with factory() as db:
            _, _, clinics = authorise(db, request)
            case = db.scalar(
                select(FollowupCase).where(
                    FollowupCase.id == case_id,
                    FollowupCase.clinic_id.in_(clinics),
                )
            )
            if not case:
                raise HTTPException(404, "Case not found")
            events = db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.case_id == case.id,
                    AuditEvent.clinic_id == case.clinic_id,
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
            return [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "origin": e.decision_origin,
                    "details": e.details,
                    "created_at": (
                        e.created_at.replace(tzinfo=UTC)
                        if e.created_at.tzinfo is None
                        else e.created_at
                    ).isoformat(),
                }
                for e in events
            ]

    install_routes(app, factory, settings, authorise)
    from forget_lah.security_audit import install_audit_routes

    install_audit_routes(app, factory, authorise)
    from forget_lah.staff_changes import install_staff_change_routes

    install_staff_change_routes(app, factory, settings, authorise)
    install_channel_routes(app, factory, settings, authorise)
    install_bridge_routes(app, factory, settings, authorise, analyzer=bridge_analyzer)
    install_demo_routes(app, factory, settings, authorise)
    install_simulator_routes(app, factory, settings, authorise)
    return app
