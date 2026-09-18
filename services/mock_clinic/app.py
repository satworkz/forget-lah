import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from forget_lah.db import make_engine, session_factory
from services.mock_clinic.contracts import CreateEpisode, CreateSlot, UpdateEpisode, UpdateSlot
from services.mock_clinic.store import (
    Episode,
    Patient,
    Slot,
    candidate,
    envelope,
    latest_confirmation,
    slot_dict,
)


class MockSettings(BaseSettings):
    mock_database_url: SecretStr
    mock_clinic_admin_key: SecretStr
    mock_clinic_followup_key: SecretStr | None = None


def create_app(settings=None, engine=None):
    settings = settings or MockSettings()
    owns_engine = engine is None
    engine = engine or make_engine(settings.mock_database_url.get_secret_value())
    factory = session_factory(engine)

    @asynccontextmanager
    async def lifespan(_):
        yield
        if owns_engine:
            engine.dispose()

    app = FastAPI(
        title="Clinic simulator — synthetic source",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    from services.mock_clinic.confirmations import install_confirmation_routes

    install_confirmation_routes(app, factory, settings)

    @app.middleware("http")
    async def secure_admin(request: Request, call_next):
        if request.url.path.startswith("/internal/admin"):
            expected = settings.mock_clinic_admin_key.get_secret_value()
            if not expected or not secrets.compare_digest(
                request.headers.get("X-Simulator-Key", ""), expected
            ):
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Simulator access denied"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health/live")
    def health():
        try:
            with factory() as db:
                if db.scalar(text("SELECT version_num FROM alembic_version")) != "sim0003":
                    raise ValueError("Migration required")
            return {"status": "ok", "synthetic": True}
        except Exception as exc:
            raise HTTPException(503, "Simulator database is not ready") from exc

    @app.get("/internal/candidates")
    def candidates():
        with factory() as db:
            return [
                candidate(db, row)
                for row in db.scalars(select(Episode).order_by(Episode.ref).limit(200))
            ]

    @app.get("/internal/followup-context/{episode}")
    def context(episode: str):
        with factory() as db:
            row = db.get(Episode, episode)
            if not row:
                raise HTTPException(404, "Synthetic episode not found")
            return envelope(db, row)

    @app.get("/internal/admin/snapshot")
    def snapshot():
        with factory() as db:
            episodes = [
                {
                    **candidate(db, row),
                    "doctor_note": row.doctor_note,
                    "note_approved": row.note_approved,
                    "prerequisite": row.prerequisite,
                    "version": row.version,
                    "attendance_confirmation": latest_confirmation(db, row),
                }
                for row in db.scalars(select(Episode).order_by(Episode.ref).limit(200))
            ]
            slots = [
                slot_dict(row)
                for row in db.scalars(select(Slot).order_by(Slot.starts_at, Slot.id).limit(500))
            ]
            return {"synthetic": True, "episodes": episodes, "slots": slots}

    @app.post("/internal/admin/episodes", status_code=201)
    def create_episode(body: CreateEpisode):
        ref = f"SIM-{body.request_id}"
        patient_id = str(body.patient_id or body.request_id)
        try:
            with factory.begin() as db:
                if db.bind.dialect.name == "postgresql":
                    db.execute(text("SELECT pg_advisory_xact_lock(76139002)"))
                if db.scalar(select(func.count()).select_from(Episode)) >= 200:
                    raise HTTPException(409, "Local simulator limit is 200 episodes")
                if body.patient_id:
                    if not db.get(Patient, patient_id):
                        raise HTTPException(
                            404, "Synthetic patient not found. Reload the simulator."
                        )
                else:
                    alias = body.display_alias
                    if not alias.endswith("(demo)"):
                        alias += " (demo)"
                    db.add(Patient(id=patient_id, display_alias=alias))
                db.flush()
                db.add(
                    Episode(
                        ref=ref,
                        patient_id=patient_id,
                        **body.model_dump(exclude={"request_id", "display_alias", "patient_id"}),
                    )
                )
        except IntegrityError as exc:
            raise HTTPException(
                409, "This test episode already exists. Reload the simulator."
            ) from exc
        return {"source_episode_ref": ref}

    @app.put("/internal/admin/episodes/{episode}")
    def edit_episode(episode: str, body: UpdateEpisode):
        with factory.begin() as db:
            changed = db.execute(
                update(Episode)
                .where(Episode.ref == episode, Episode.version == body.expected_version)
                .values(
                    **body.model_dump(exclude={"expected_version"}), version=Episode.version + 1
                )
            )
            if changed.rowcount != 1:
                raise HTTPException(
                    409, "Record changed or no longer exists. Reload before editing."
                )
        return {"source_episode_ref": episode, "version": body.expected_version + 1}

    @app.post("/internal/admin/slots", status_code=201)
    def create_slot(body: CreateSlot):
        try:
            with factory.begin() as db:
                if db.bind.dialect.name == "postgresql":
                    db.execute(text("SELECT pg_advisory_xact_lock(76139003)"))
                if db.scalar(select(func.count()).select_from(Slot)) >= 500:
                    raise HTTPException(409, "Local simulator limit is 500 slots")
                db.add(Slot(id=str(body.request_id), **body.model_dump(exclude={"request_id"})))
        except IntegrityError as exc:
            raise HTTPException(
                409, "Slot already exists, or this doctor already has a slot at that start time."
            ) from exc
        return {"id": str(body.request_id)}

    @app.put("/internal/admin/slots/{slot_id}")
    def edit_slot(slot_id: str, body: UpdateSlot):
        try:
            with factory.begin() as db:
                changed = db.execute(
                    update(Slot)
                    .where(Slot.id == slot_id, Slot.version == body.expected_version)
                    .values(
                        **body.model_dump(exclude={"expected_version"}), version=Slot.version + 1
                    )
                )
                if changed.rowcount != 1:
                    raise HTTPException(
                        409, "Slot changed or no longer exists. Reload before editing."
                    )
        except IntegrityError as exc:
            raise HTTPException(409, "This doctor already has a slot at that start time.") from exc
        return {"id": slot_id, "version": body.expected_version + 1}

    return app
