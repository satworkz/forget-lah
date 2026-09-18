"""Authenticated local test-data console; all source writes remain in the mock service."""

import secrets
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request

from forget_lah.auth import digest
from forget_lah.source import DEMO_CLINIC_ID
from services.mock_clinic.contracts import CreateEpisode, CreateSlot, UpdateEpisode, UpdateSlot


def install_simulator_routes(app, factory, settings, authorise):
    app.state.simulator_transport = None  # Injectable HTTP transport for integration tests.

    def forward(request, method, path, body=None):
        with factory() as db:
            _, session, clinics = authorise(db, request)
            if DEMO_CLINIC_ID not in clinics or settings.app_env not in {"local", "test", "demo"}:
                raise HTTPException(403, "Simulator is available only for the local demo clinic")
            if method != "GET" and not secrets.compare_digest(
                digest(request.headers.get("X-CSRF-Token", "")), session.csrf_hash
            ):
                raise HTTPException(403, "Invalid CSRF token")
        if not settings.mock_clinic_admin_key:
            raise HTTPException(503, "Simulator is not configured. Run scripts/dev.ps1 up.")
        try:
            with httpx.Client(
                timeout=10, follow_redirects=False, transport=app.state.simulator_transport
            ) as client:
                response = client.request(
                    method,
                    f"{settings.mock_clinic_url.rstrip('/')}/internal/admin/{path}",
                    headers={"X-Simulator-Key": settings.mock_clinic_admin_key.get_secret_value()},
                    json=body.model_dump(mode="json") if body else None,
                )
            if response.status_code == 409:
                raise HTTPException(
                    409, response.json().get("detail", "Source data changed. Reload the simulator.")
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                503,
                "Clinic simulator is unavailable. Your application history is unchanged; reload before retrying a save.",
            ) from exc

    @app.get("/api/simulator")
    def snapshot(request: Request):
        return forward(request, "GET", "snapshot")

    @app.post("/api/simulator/episodes", status_code=201)
    def create_episode(body: CreateEpisode, request: Request):
        return forward(request, "POST", "episodes", body)

    @app.put("/api/simulator/episodes/{episode}")
    def update_episode(episode: str, body: UpdateEpisode, request: Request):
        return forward(request, "PUT", f"episodes/{quote(episode, safe='')}", body)

    @app.post("/api/simulator/slots", status_code=201)
    def create_slot(body: CreateSlot, request: Request):
        return forward(request, "POST", "slots", body)

    @app.put("/api/simulator/slots/{slot_id}")
    def update_slot(slot_id: str, body: UpdateSlot, request: Request):
        return forward(request, "PUT", f"slots/{quote(slot_id, safe='')}", body)
