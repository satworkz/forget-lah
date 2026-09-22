import base64
import io
import json
import zipfile

import pytest
from sqlalchemy import select
from test_bridge import FakeBridgeAnalyzer, bridge_client, upload_csv
from test_postgres import postgres_schema  # noqa: F401 - shared isolated PostgreSQL fixture

from forget_lah.bridge import MAX_UPLOAD_BYTES, parse_upload
from forget_lah.db import (
    Clinic,
    FollowupCase,
    Membership,
    Patient,
    Principal,
    SecurityEvent,
    uid,
)
from forget_lah.detector import detect
from forget_lah.runtime.engine import observation_for
from forget_lah.runtime.models import AgentRun, AgentStep
from forget_lah.runtime.policy import has_authority
from forget_lah.security import model_context
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.fixtures import candidates


def mutation_headers(client):
    return {
        "Origin": "http://localhost:8080",
        "X-CSRF-Token": client.cookies.get("forget_lah_csrf"),
        "Idempotency-Key": uid(),
    }


def setup_cases(store):
    detect(store[1], DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with store[1]() as db:
        return db.scalar(select(FollowupCase.id))


def set_role(store, role):
    with store[1].begin() as db:
        db.scalar(
            select(Membership).join(Principal).where(Principal.email == "staff@forget-lah.example")
        ).role = role


def foreign_case(store):
    with store[1].begin() as db:
        clinic = Clinic(name="Foreign clinic sentinel")
        db.add(clinic)
        db.flush()
        patient = Patient(id=uid(), clinic_id=clinic.id, display_alias="FOREIGN_PATIENT_SENTINEL")
        db.add(patient)
        db.flush()
        case = FollowupCase(
            clinic_id=clinic.id,
            patient_id=patient.id,
            source_episode_ref="foreign-secret-ref",
            specialty="general",
            trigger="UPCOMING",
        )
        db.add(case)
        db.flush()
        return case.id, clinic.id


@pytest.mark.parametrize("suffix", ["agent", "events", "audit", "appointment-change"])
def test_foreign_case_read_denied(store, signed_client, suffix):
    case_id, _ = foreign_case(store)
    response = signed_client.get(f"/api/cases/{case_id}/{suffix}")
    assert response.status_code == 404
    assert "FOREIGN_PATIENT" not in response.text


@pytest.mark.parametrize("role", ["viewer", "auditor", "unknown"])
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/bridge/analyse", {"filename": "test.csv", "content_base64": "eCx5CjEsMg=="}),
        ("/api/bridge/batches/absent/approve", {"include_review_rows": False}),
        ("/api/bridge/batches/absent/revise", {"instruction": "Check mapping"}),
        ("/api/cases/{case}/appointment-change/review", {"expected_case_version": 1}),
        ("/api/cases/{case}/appointment-change/absent/retry", None),
        ("/api/bridge/cases/{case}/options/absent/withdraw", {"expected_version": 1}),
    ],
)
def test_read_only_roles_cannot_mutate(store, signed_client, role, path, body):
    case_id = setup_cases(store)
    set_role(store, role)
    response = signed_client.post(
        path.replace("{case}", case_id), json=body, headers=mutation_headers(signed_client)
    )
    assert response.status_code == 403, response.text


def test_role_is_scoped_per_clinic_and_checked_again_on_worker(store, signed_client):
    case_id = setup_cases(store)
    foreign_id, clinic_id = foreign_case(store)
    with store[1].begin() as db:
        user = db.scalar(select(Principal).where(Principal.email == "staff@forget-lah.example"))
        db.add(Membership(principal_id=user.id, clinic_id=clinic_id, role="viewer"))
        run = AgentRun(clinic_id=clinic_id, authorised_by=user.id)
        assert not has_authority(db, run)
    summaries = {item["id"]: item for item in signed_client.get("/api/cases").json()}
    assert "•••" not in summaries[case_id]["patient"]
    assert summaries[foreign_id]["patient"] != "FOREIGN_PATIENT_SENTINEL"
    assert "•••" in summaries[foreign_id]["patient"]
    assert signed_client.get(f"/api/cases/{case_id}/audit").status_code == 200
    assert signed_client.get(f"/api/cases/{foreign_id}/audit").status_code == 404
    assert (
        signed_client.post(
            f"/api/cases/{foreign_id}/appointment-change/review",
            json={"expected_case_version": 1},
            headers=mutation_headers(signed_client),
        ).status_code
        == 404
    )


@pytest.mark.parametrize("role", ["staff", "admin", "auditor"])
def test_staff_names_and_masked_identifiers_in_summary(store, signed_client, role):
    case_id = setup_cases(store)
    set_role(store, role)
    foreign_id, *_ = foreign_case(store)
    with store[1]() as db:
        case = db.get(FollowupCase, case_id)
        name = db.get(Patient, case.patient_id).display_alias
        reference = case.source_episode_ref
    response = signed_client.get("/api/cases")
    assert response.status_code == 200
    summary = response.text
    assert name in summary and reference not in summary
    assert foreign_id not in summary and "FOREIGN_PATIENT_SENTINEL" not in summary
    assert signed_client.get(f"/api/cases/{case_id}/audit").json()["patient"] == name
    set_role(store, "viewer")
    response = signed_client.get("/api/cases")
    assert response.status_code == 200
    assert name not in response.text and reference not in response.text
    assert signed_client.get(f"/api/cases/{case_id}/audit").status_code == 403


@pytest.mark.parametrize(
    "filename,data",
    [
        ("bad.xls", b"x,y\n1,2"),
        ("bad.xlsm", b"x,y\n1,2"),
        ("bad.xlsx", b"encrypted-not-zip"),
        ("bad.csv", b"x" * (MAX_UPLOAD_BYTES + 1)),
        ("bad.csv", b"header\n" + b"value\n" * 201),
        ("bad.tsv", b"header\n" + b"value\n" * 201),
        ("bad.csv", (",".join(["column"] * 41) + "\n1").encode()),
    ],
    ids=["xls", "xlsm", "encrypted", "oversize", "csv_rows", "tsv_rows", "columns"],
)
def test_upload_limits_reject_instead_of_truncate(filename, data):
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        parse_upload(filename, data)


def test_csv_formula_remains_literal_untrusted_data():
    _, rows = parse_upload("values.csv", b'Name,Value\nTest,"=SUM(A1:A2)"\n')
    assert rows[0]["cells"]["Value"] == "=SUM(A1:A2)"


def test_zip_bomb_and_macro_parts_rejected_before_xml_parsing():
    for name, data in [
        ("xl/vbaProject.bin", b"macro"),
        ("xl/sharedStrings.xml", b"a" * 8_000_001),
        ("xl/externalLinks/link.xml", b"external"),
    ]:
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(name, data)
        with pytest.raises(ValueError):
            parse_upload("attack.xlsx", content.getvalue())


@pytest.mark.parametrize("attack", ["formula", "entity", "rows", "duplicate", "encrypted"])
def test_xlsx_unsafe_parts_are_rejected(attack):
    from test_bridge import _minimal_xlsx

    original = _minimal_xlsx([["Name"], ["Literal"]])
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output, "w") as target:
        for part in source.infolist():
            data = source.read(part.filename)
            if "worksheets/" in part.filename:
                if attack == "formula":
                    data = data.replace(b"</c>", b'<f>HYPERLINK("https://invalid")</f></c>', 1)
                elif attack == "entity":
                    data = b'<!DOCTYPE sheet [<!ENTITY evil "boom">]>' + data
                elif attack == "rows":
                    data = data.replace(b"</sheetData>", b"<row/>" * 201 + b"</sheetData>")
            target.writestr(part.filename, data)
            if attack == "duplicate" and "worksheets/" in part.filename:
                with pytest.warns(UserWarning):
                    target.writestr(part.filename, data)
    payload = output.getvalue()
    if attack == "encrypted":
        payload = bytearray(payload)
        # Set encryption bit in both local and central ZIP headers.
        for signature, offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
            start = payload.find(signature)
            payload[start + offset] |= 1
        payload = bytes(payload)
    with pytest.raises(ValueError):
        parse_upload("unsafe.xlsx", payload)


@pytest.mark.parametrize(
    "suffix,body",
    [
        (
            "appointment-change",
            {
                "expected_case_version": 1,
                "expected_version": 1,
                "expected_source_version": "v1",
                "slot_id": "00000000-0000-0000-0000-000000000001",
                "slot_version": 1,
            },
        ),
        ("appointment-change/review", {"expected_case_version": 1}),
        ("appointment-change/missing/retry", None),
    ],
)
def test_foreign_appointment_mutations_are_denied(store, signed_client, suffix, body):
    case_id, _ = foreign_case(store)
    response = signed_client.post(
        f"/api/cases/{case_id}/{suffix}", json=body, headers=mutation_headers(signed_client)
    )
    assert response.status_code == 404


def test_foreign_bridge_slot_add_is_denied(store, signed_client):
    case_id, _ = foreign_case(store)
    response = signed_client.post(
        f"/api/bridge/cases/{case_id}/options",
        headers=mutation_headers(signed_client),
        json={
            "expected_version": 1,
            "starts_at": "2099-01-01T09:00:00+08:00",
            "ends_at": "2099-01-01T10:00:00+08:00",
            "doctor": "Clinic team",
        },
    )
    assert response.status_code == 404


@pytest.mark.postgres
def test_postgres_security_roles_audit_and_upload_rejection(request):
    from alembic import command
    from alembic.config import Config

    from forget_lah.seed import seed

    store = request.getfixturevalue("postgres_schema")
    command.upgrade(Config("alembic.ini"), "head")
    seed(store[1], "staff@forget-lah.example", "unit-test-only-not-a-live-credential")
    with bridge_client(store, FakeBridgeAnalyzer()) as client:
        case_id = setup_cases(store)
        foreign_id, _ = foreign_case(store)
        assert client.get(f"/api/cases/{foreign_id}/audit").status_code == 404
        set_role(store, "auditor")
        assert client.get(f"/api/cases/{case_id}/audit").status_code == 200
        assert upload_csv(client).status_code == 403
        set_role(store, "staff")
        assert upload_csv(client).status_code == 200
        rejected = client.post(
            "/api/bridge/analyse",
            headers=mutation_headers(client),
            json={"filename": "unsafe.xlsm", "content_base64": "eA=="},
        )
        assert rejected.status_code == 422
        with store[1]() as db:
            assert (
                len(
                    list(
                        db.scalars(select(SecurityEvent).where(SecurityEvent.decision == "denied"))
                    )
                )
                == 3
            )


def test_invalid_uploads_are_logged_without_echoing_data(store, signed_client, caplog):
    secret = "SENSITIVE_UPLOAD_SENTINEL"
    for _ in range(3):
        response = signed_client.post(
            "/api/bridge/analyse",
            headers=mutation_headers(signed_client),
            json={
                "filename": "test.xlsx",
                "content_base64": base64.b64encode(secret.encode()).decode(),
            },
        )
        assert response.status_code == 422 and secret not in response.text
    with store[1]() as db:
        events = list(db.scalars(select(SecurityEvent).where(SecurityEvent.decision == "denied")))
        assert len(events) == 3 and any(e.details["repeated"] for e in events)
        assert secret not in json.dumps([e.details for e in events])
    assert secret not in caplog.text
    response = signed_client.post(
        "/api/bridge/analyse", headers=mutation_headers(signed_client), content=b"x" * 2_110_001
    )
    assert response.status_code == 413


def test_bridge_audit_provenance_and_cross_clinic_scope(store):
    analyzer = FakeBridgeAnalyzer()
    with bridge_client(store, analyzer) as client:
        batch = upload_csv(client).json()
        client.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        ).raise_for_status()
        with store[1]() as db:
            case_id = db.scalar(select(FollowupCase.id))
        events = client.get(f"/api/cases/{case_id}/audit").json()["events"]
        assert any(
            e["action"] == "bridge_provenance" and len(e["evidence"]["sha256"]) == 64
            for e in events
        )
        assert any(e["action"] == "bridge_approve" and e["actor"] != "Not recorded" for e in events)
        _, foreign_clinic = foreign_case(store)
        denied = client.post(
            "/api/bridge/analyse",
            headers=mutation_headers(client),
            json={
                "filename": "test.csv",
                "content_base64": "eCx5CjEsMg==",
                "clinic_id": foreign_clinic,
            },
        )
        assert denied.status_code == 403 and len(analyzer.calls) == 1
        with store[1].begin() as db:
            db.scalar(select(Membership)).clinic_id = foreign_clinic
        assert client.get(f"/api/bridge/batches/{batch['id']}").status_code == 404
        assert (
            client.post(
                f"/api/bridge/batches/{batch['id']}/approve",
                headers=mutation_headers(client),
                json={"include_review_rows": False},
            ).status_code
            == 404
        )
        assert client.get(f"/api/cases/{case_id}/audit").status_code == 404


@pytest.mark.parametrize("role", ["coordinator", "engagement", "preparation"])
def test_observation_excludes_unrelated_case_and_nested_identity(store, signed_client, role):
    case_id = setup_cases(store)
    unrelated_id, _ = foreign_case(store)
    with store[1].begin() as db:
        user = db.scalar(select(Principal))
        case = db.get(FollowupCase, case_id)
        run_id = uid()
        run = AgentRun(
            id=run_id,
            clinic_id=case.clinic_id,
            case_id=case.id,
            start_key=uid(),
            start_case_version=1,
            started_by=user.id,
            authorised_by=user.id,
            mode="mock",
            goal="Review",
            active_role=role,
            checkpoint={"latest_event": {"id": run_id, "kind": "started", "content": ""}},
        )
        db.add(run)
        db.flush()
        other = db.get(FollowupCase, unrelated_id)
        other_run = AgentRun(
            id=uid(),
            clinic_id=other.clinic_id,
            case_id=other.id,
            start_key=uid(),
            start_case_version=1,
            started_by=user.id,
            authorised_by=user.id,
            mode="mock",
            goal="FOREIGN_GOAL_SENTINEL",
        )
        db.add(other_run)
        db.flush()
        db.add(
            AgentStep(
                clinic_id=other.clinic_id,
                case_id=other.id,
                run_id=other_run.id,
                sequence=1,
                case_version=1,
                role="engagement",
                origin="mock",
                status="completed",
                tool_result={"foreign": "FOREIGN_TOOL_SENTINEL"},
            )
        )
        db.flush()
        observation = observation_for(db, run, case, uid())
        assert "FOREIGN_" not in json.dumps(observation)
        assert other.patient_id not in json.dumps(observation)
        with pytest.raises(ValueError, match="binding"):
            observation_for(db, run, other, uid())
    projected = model_context(
        {
            "result": {
                "patient_id": "secret",
                "phone": "secret",
                "available_slots": [1],
                "evidence": "keep",
            }
        },
        role,
    )
    assert "secret" not in json.dumps(projected)
    assert projected["result"]["evidence"] == "keep"
    assert ("available_slots" in projected["result"]) == (role == "engagement")
