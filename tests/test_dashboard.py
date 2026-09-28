from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from forget_lah.db import (
    BridgeEpisode,
    BridgeIntakeBatch,
    BridgeIntakeRecord,
    FollowupCase,
    Membership,
    Principal,
    uid,
)
from forget_lah.detector import detect
from forget_lah.source import DEMO_CLINIC_ID, Candidate


def candidate(days, name="Priya", ref="private-source-ref"):
    return Candidate(
        patient_id="20000000-0000-4000-8000-000000000003",
        display_alias=name,
        source_episode_ref=ref,
        specialty="antenatal",
        record_type="appointment",
        source_status="scheduled",
        scheduled_at=datetime(2026, 9, 28, tzinfo=UTC) + timedelta(days=days),
    )


def test_all_records_window_and_read_only(store, signed_client, monkeypatch):
    now = datetime(2026, 9, 28, tzinfo=UTC)
    monkeypatch.setattr("forget_lah.dashboard.utcnow", lambda: now)
    source = [
        candidate(12),
        candidate(7, "Alex", "at-boundary"),
        candidate(8, "Omar", "outside"),
        candidate(-1, "Ahmad", "past"),
    ]
    monkeypatch.setattr("forget_lah.dashboard.read_candidates", lambda _: source)
    body = signed_client.get("/api/dashboard/records").json()
    rows = {r["patient"]: r for r in body["records"]}
    assert len(rows) == 4
    assert rows["Alex"]["requires_attention"]
    assert rows["Ahmad"]["reason"] == "Past appointment — verify status"
    assert not rows["Priya"]["requires_attention"]
    assert not rows["Omar"]["requires_attention"]
    assert all(r["case_id"] is None for r in rows.values())
    assert "private-source-ref" not in str(body)
    with store[1]() as db:
        assert db.scalar(select(func.count()).select_from(FollowupCase)) == 0


def test_source_failure_preserves_case_visibility(store, signed_client, monkeypatch):
    c = candidate(1)
    detect(store[1], DEMO_CLINIC_ID, [c], now=datetime(2026, 9, 28, tzinfo=UTC))

    def failed(_):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("forget_lah.dashboard.read_candidates", failed)
    body = signed_client.get("/api/dashboard/records").json()
    assert body["warnings"]
    assert body["records"][0]["case_id"]
    assert body["records"][0]["source"] == "Saved follow-up"


def test_bridge_outside_window_and_viewer_masking(store, signed_client, monkeypatch):
    monkeypatch.setattr("forget_lah.dashboard.read_candidates", lambda _: [])
    with store[1].begin() as db:
        principal = db.scalar(select(Principal))
        batch = BridgeIntakeBatch(
            clinic_id=DEMO_CLINIC_ID,
            uploaded_by=principal.id,
            filename="demo.csv",
            file_type="csv",
            sha256="a" * 64,
        )
        db.add(batch)
        db.flush()
        record = BridgeIntakeRecord(clinic_id=DEMO_CLINIC_ID, batch_id=batch.id, row_number=2)
        db.add(record)
        db.flush()
        db.add(
            BridgeEpisode(
                clinic_id=DEMO_CLINIC_ID,
                patient_id=uid(),
                record_id=record.id,
                source_episode_ref="bridge:private",
                normalized={
                    "patient_name": "Mrs Nila",
                    "record_type": "appointment",
                    "source_status": "scheduled",
                    "specialty": "general",
                    "appointment_at": "2099-10-07T10:00:00+08:00",
                },
            )
        )
    body = signed_client.get("/api/dashboard/records").json()
    assert body["records"][0]["patient"] == "Mrs Nila"
    assert body["records"][0]["source"] == "Intelligent Intake"
    assert not body["records"][0]["requires_attention"]
    with store[1].begin() as db:
        db.scalar(select(Membership)).role = "viewer"
    response = signed_client.get("/api/dashboard/records")
    assert "Mrs Nila" not in response.text
    assert "bridge:private" not in response.text
    with store[1].begin() as db:
        db.scalar(select(Membership)).active = False
    assert signed_client.get("/api/dashboard/records").status_code == 403


def test_requires_login(client):
    assert client.get("/api/dashboard/records").status_code == 401
