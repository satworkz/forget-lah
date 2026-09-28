from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import select

from forget_lah.api import create_app
from forget_lah.db import FollowupCase, Membership, make_engine, session_factory
from forget_lah.detector import detect
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.app import MockSettings
from services.mock_clinic.app import create_app as create_mock
from services.mock_clinic.bootstrap import migrate
from services.mock_clinic.store import Base, seed

KEY = "test-only-simulator-key"
ADMIN = {"X-Simulator-Key": KEY}
EPISODE = "DEMO-MYOPIA-VISIT-01"


@pytest.fixture
def simulator(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}")
    migrate(engine)
    seed(session_factory(engine))
    settings = MockSettings(mock_database_url="sqlite://", mock_clinic_admin_key=KEY)
    with TestClient(create_mock(settings, engine)) as client:
        yield client, engine
    engine.dispose()


def transport_for(client):
    def handler(request):
        response = client.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.content
        )
        return httpx.Response(response.status_code, json=response.json())

    return httpx.MockTransport(handler)


def episode_body(client, ref=EPISODE):
    row = next(
        e
        for e in client.get("/internal/admin/snapshot", headers=ADMIN).json()["episodes"]
        if e["source_episode_ref"] == ref
    )
    return {
        **{
            k: row[k]
            for k in (
                "specialty",
                "record_type",
                "source_status",
                "scheduled_at",
                "due_at",
                "has_future_booking",
                "doctor_note",
                "note_approved",
                "prerequisite",
            )
        },
        "expected_version": row["version"],
    }


def test_source_migration_and_seed_preserve_edits_and_dates(simulator):
    client, engine = simulator
    body = episode_body(client)
    body["doctor_note"] = "Bring the blue demo folder."
    body["scheduled_at"] = "2030-02-03T10:30:00+08:00"
    assert (
        client.put(f"/internal/admin/episodes/{EPISODE}", headers=ADMIN, json=body).status_code
        == 200
    )
    before = client.get(f"/internal/followup-context/{EPISODE}").json()
    migrate(engine)
    seed(session_factory(engine))
    assert client.get(f"/internal/followup-context/{EPISODE}").json() == before
    assert before["instructions"][0]["approved_text"] == body["doctor_note"]
    assert datetime.fromisoformat(before["context"]["scheduled_at"]) == datetime.fromisoformat(
        body["scheduled_at"]
    )
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_source_edits_reach_existing_adapter_and_approval_is_explicit(simulator):
    client, _ = simulator
    source = client.get(f"/internal/followup-context/{EPISODE}").json()
    binding = {k: source[k] for k in ("clinic_id", "patient_id", "source_episode_ref")}
    tools = ClinicTools("http://source", transport_for(client))
    body = episode_body(client)
    body.update(
        doctor_note="Synthetic instruction. Do not turn this into clinical advice.",
        note_approved=False,
    )
    client.put(f"/internal/admin/episodes/{EPISODE}", headers=ADMIN, json=body).raise_for_status()
    assert tools.execute("get_approved_instructions", binding).data["instructions"] == []
    body = episode_body(client)
    body.update(note_approved=True, prerequisite="STAFF_REVIEW_REQUIRED")
    client.put(f"/internal/admin/episodes/{EPISODE}", headers=ADMIN, json=body).raise_for_status()
    result = tools.execute("get_approved_instructions", binding)
    assert result.status == "succeeded"
    assert result.source_version != source["source_version"]
    assert result.data["instructions"][0]["approved_text"] == body["doctor_note"]
    assert tools.execute("check_prerequisites", binding).data == {
        "prerequisites": ["STAFF_REVIEW_REQUIRED"]
    }
    assert (
        tools.execute("read_followup_context", {**binding, "patient_id": str(uuid4())}).error_code
        == "SOURCE_INVALID"
    )


def new_slot(**changes):
    start = datetime.now(UTC) + timedelta(days=3)
    return {
        "request_id": str(uuid4()),
        "specialty": "myopia",
        "doctor": f"Demo {uuid4().hex[:6]}",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(minutes=30)).isoformat(),
        "available": True,
        **changes,
    }


def test_slots_filter_version_and_stale_writes(simulator):
    client, _ = simulator
    original = client.get(f"/internal/followup-context/{EPISODE}").json()["source_version"]
    body = new_slot()
    response = client.post("/internal/admin/slots", headers=ADMIN, json=body)
    assert response.status_code == 201
    slot_id = response.json()["id"]
    for extra in [
        new_slot(specialty="dental"),
        new_slot(available=False),
        new_slot(starts_at="2020-01-01T00:00:00Z", ends_at="2020-01-01T00:30:00Z"),
    ]:
        assert client.post("/internal/admin/slots", headers=ADMIN, json=extra).status_code == 201
    context = client.get(f"/internal/followup-context/{EPISODE}").json()
    assert [s["id"] for s in context["context"]["available_slots"]] == [slot_id]
    assert context["source_version"] != original
    update = {
        **{k: v for k, v in body.items() if k != "request_id"},
        "available": False,
        "expected_version": 1,
    }
    assert (
        client.put(f"/internal/admin/slots/{slot_id}", headers=ADMIN, json=update).status_code
        == 200
    )
    assert (
        client.put(f"/internal/admin/slots/{slot_id}", headers=ADMIN, json=update).status_code
        == 409
    )
    assert (
        client.get(f"/internal/followup-context/{EPISODE}").json()["context"]["available_slots"]
        == []
    )
    assert client.post("/internal/admin/slots", headers=ADMIN, json=body).status_code == 409


@pytest.mark.parametrize(
    "patch",
    [
        {"scheduled_at": "2026-09-13T10:00:00"},
        {"source_status": "due"},
        {"note_approved": True, "doctor_note": ""},
        {"doctor_note": "x" * 401},
    ],
)
def test_invalid_source_changes_are_rejected(simulator, patch):
    client, _ = simulator
    body = {**episode_body(client), **patch}
    assert (
        client.put(f"/internal/admin/episodes/{EPISODE}", headers=ADMIN, json=body).status_code
        == 422
    )


def test_new_episode_detection_deduplication_and_reset_use_current_source(simulator, store):
    from forget_lah.demo_reset import lock_reset_tables, reset_demo

    client, _ = simulator
    body = episode_body(client)
    body.pop("expected_version")
    body.update(request_id=str(uuid4()), display_alias="Scenario Alex")
    response = client.post("/internal/admin/episodes", headers=ADMIN, json=body)
    assert response.status_code == 201
    assert client.post("/internal/admin/episodes", headers=ADMIN, json=body).status_code == 409
    factory = store[1]
    rows = candidates_from_payload(client.get("/internal/candidates").json())
    assert detect(factory, DEMO_CLINIC_ID, rows) == 4
    assert detect(factory, DEMO_CLINIC_ID, rows) == 0
    ref = response.json()["source_episode_ref"]
    edit = {**episode_body(client, ref), "source_status": "cancelled"}
    client.put(f"/internal/admin/episodes/{ref}", headers=ADMIN, json=edit).raise_for_status()
    with factory() as db:
        old_ids = list(db.scalars(select(FollowupCase.id)))
    with factory.begin() as db:
        lock_reset_tables(db)
        result = reset_demo(
            db, old_ids, candidates_from_payload(client.get("/internal/candidates").json())
        )
    assert len(result["case_ids"]) == 3
    assert len(client.get("/internal/candidates").json()) == 4


@pytest.mark.parametrize("existing_demo", [True, False])
def test_another_appointment_keeps_patient_and_old_case(simulator, store, existing_demo):
    from forget_lah.demo_reset import validate_candidates
    from services.mock_clinic.store import Patient

    client, engine = simulator
    original = client.get(f"/internal/followup-context/{EPISODE}").json()
    body = episode_body(client)
    body.pop("expected_version")
    body.update(request_id=str(uuid4()), display_alias="New test patient")
    if not existing_demo:
        result = client.post("/internal/admin/episodes", headers=ADMIN, json=body)
        result.raise_for_status()
        original = client.get(
            "/internal/followup-context/" + result.json()["source_episode_ref"]
        ).json()
    factory = store[1]
    detect(
        factory, DEMO_CLINIC_ID, candidates_from_payload(client.get("/internal/candidates").json())
    )
    with factory() as db:
        old_ids = set(db.scalars(select(FollowupCase.id)))
    with session_factory(engine)() as db:
        old_patients = set(db.scalars(select(Patient.id)))
    body.update(
        request_id=str(uuid4()),
        patient_id=original["patient_id"],
        display_alias="Must not rename existing patient",
        scheduled_at=(datetime.now(UTC) + timedelta(days=4)).isoformat(),
    )
    result = client.post("/internal/admin/episodes", headers=ADMIN, json=body)
    assert result.status_code == 201
    ref = result.json()["source_episode_ref"]
    new = client.get(f"/internal/followup-context/{ref}").json()
    assert new["patient_id"] == original["patient_id"]
    assert (
        client.get("/internal/followup-context/" + original["source_episode_ref"]).json()
        == original
    )
    with session_factory(engine)() as db:
        assert set(db.scalars(select(Patient.id))) == old_patients
        assert db.get(Patient, original["patient_id"]).display_alias != body["display_alias"]
    rows = candidates_from_payload(client.get("/internal/candidates").json())
    validate_candidates(rows)
    assert detect(factory, DEMO_CLINIC_ID, rows) == 1
    assert detect(factory, DEMO_CLINIC_ID, rows) == 0
    with factory() as db:
        assert old_ids < set(db.scalars(select(FollowupCase.id)))
    assert client.post("/internal/admin/episodes", headers=ADMIN, json=body).status_code == 409
    body.update(request_id=str(uuid4()), patient_id=str(uuid4()))
    assert client.post("/internal/admin/episodes", headers=ADMIN, json=body).status_code == 404


def test_console_requires_clinic_session_origin_csrf_and_internal_key(simulator, store):
    client, _ = simulator
    assert client.get("/internal/admin/snapshot").status_code == 403
    settings = Settings(app_env="test", database_url="sqlite://", mock_clinic_admin_key=KEY)
    app = create_app(settings, store[0])
    app.state.simulator_transport = transport_for(client)
    with TestClient(app, base_url="http://localhost:8080") as console:
        assert console.get("/api/simulator").status_code == 401
        console.post(
            "/api/auth/login",
            headers={"Origin": "http://localhost:8080"},
            json={
                "email": "staff@forget-lah.example",
                "password": "unit-test-only-not-a-live-credential",
            },
        ).raise_for_status()
        assert console.get("/api/simulator").status_code == 200
        body = new_slot()
        assert console.post("/api/simulator/slots", json=body).status_code == 403
        headers = {"Origin": "http://localhost:8080"}
        assert console.post("/api/simulator/slots", headers=headers, json=body).status_code == 403
        headers["X-CSRF-Token"] = console.cookies.get("forget_lah_csrf")
        assert console.post("/api/simulator/slots", headers=headers, json=body).status_code == 201
        invalid = console.post(
            "/api/simulator/slots",
            headers=headers,
            json={**new_slot(), "ends_at": "2000-01-01T00:00:00Z"},
        )
        assert invalid.status_code == 422 and "end must be later" in invalid.json()["detail"]
        with store[1].begin() as db:
            db.scalar(select(Membership)).active = False
        assert console.get("/api/simulator").status_code == 403


def test_month_search_filters_before_limit_and_keeps_source_version(simulator):
    client, _ = simulator
    for day in range(1, 14):
        body = {
            "request_id": str(uuid4()),
            "specialty": "myopia",
            "starts_at": f"2030-10-{day:02d}T10:00:00+08:00",
            "ends_at": f"2030-10-{day:02d}T10:30:00+08:00",
            "doctor": "Test clinician",
            "available": True,
        }
        assert client.post("/internal/admin/slots", headers=ADMIN, json=body).status_code == 201
    body.update(
        request_id=str(uuid4()),
        starts_at="2030-11-01T00:00:00+08:00",
        ends_at="2030-11-01T00:30:00+08:00",
    )
    assert client.post("/internal/admin/slots", headers=ADMIN, json=body).status_code == 201
    base = client.get(f"/internal/followup-context/{EPISODE}").json()
    tools = ClinicTools("http://source", transport=transport_for(client))
    binding = {k: base[k] for k in ("clinic_id", "patient_id", "source_episode_ref")}
    binding["slot_date_window"] = {"date_from": "2030-11-01", "date_to": "2030-11-30"}
    result = tools.execute("read_followup_context", binding)
    assert result.status == "succeeded"
    assert result.source_version == base["source_version"]
    assert len(result.data["available_slots"]) == 1
    assert result.data["available_slots"][0]["id"] == body["request_id"]
    assert not result.data["more_available_slots"]
    assert len(base["context"]["available_slots"]) == 10
    empty = client.get(
        f"/internal/followup-context/{EPISODE}?date_from=2030-12-01&date_to=2030-12-31"
    ).json()
    assert empty["context"]["available_slots"] == []
    assert empty["source_version"] == base["source_version"]
