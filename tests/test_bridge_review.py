from sqlalchemy import select
from test_bridge import FakeBridgeAnalyzer, bridge_client, mutation_headers, upload_csv

from forget_lah.db import BridgeIntakeRecord, FollowupCase


class SpecialtyReviewAnalyzer(FakeBridgeAnalyzer):
    def analyse(self, rows, **kwargs):
        analysis = super().analyse(rows, **kwargs)
        first = analysis.records[0].model_copy(
            update={
                "specialty": "general",
                "confidence": 85,
                "issues": ["Specialty unclear from context, defaulting to general"],
            }
        )
        return analysis.model_copy(update={"records": [first, *analysis.records[1:]]})


def _review_payload(row, **overrides):
    normalized = row["normalized"]
    payload = {
        "external_ref": normalized.get("external_ref"),
        "patient_name": normalized.get("patient_name") or "",
        "phone": normalized.get("phone"),
        "appointment_at": normalized.get("appointment_at"),
        "due_at": normalized.get("due_at"),
        "record_type": normalized.get("record_type") or "appointment",
        "source_status": normalized.get("source_status") or "scheduled",
        "specialty": normalized.get("specialty") or "general",
        "doctor_notes": normalized.get("doctor_notes"),
        "preferred_language": normalized.get("preferred_language") or "und",
        "review_note": "Reviewed in Bridge UI",
    }
    payload.update(overrides)
    return payload


def test_bridge_review_row_can_be_edited_to_ready_without_reupload(store):
    client = bridge_client(store, SpecialtyReviewAnalyzer())
    try:
        batch = upload_csv(client).json()
        first = batch["records"][0]
        assert first["status"] == "REVIEW"
        assert "Specialty unclear" in first["issues"][0]
        reviewed = client.post(
            f"/api/bridge/batches/{batch['id']}/records/{first['id']}/review",
            headers=mutation_headers(client),
            json=_review_payload(first, specialty="antenatal"),
        )
        assert reviewed.status_code == 200, reviewed.text
        result = reviewed.json()
        updated = next(row for row in result["records"] if row["id"] == first["id"])
        assert updated["status"] == "READY"
        assert updated["normalized"]["specialty"] == "antenatal"
        assert updated["issues"] == []
        assert updated["reviewed_at"]
        assert updated["raw"]["Free text"] == "Bring the referral letter."
        assert updated["staff_overrides"]["changes"]["specialty"] == {
            "from": "general",
            "to": "antenatal",
        }
        assert result["analysis_version"] == batch["analysis_version"] + 1
        with store[1]() as db:
            saved = db.get(BridgeIntakeRecord, first["id"])
            assert saved.reviewed_by
            assert saved.reviewed_at
            assert saved.staff_overrides["review_note"] == "Reviewed in Bridge UI"
    finally:
        client.__exit__(None, None, None)


def test_bridge_staff_review_keeps_doctor_notes_source_bound(store):
    client = bridge_client(store, SpecialtyReviewAnalyzer())
    try:
        batch = upload_csv(client).json()
        first = batch["records"][0]
        response = client.post(
            f"/api/bridge/batches/{batch['id']}/records/{first['id']}/review",
            headers=mutation_headers(client),
            json=_review_payload(
                first,
                specialty="antenatal",
                doctor_notes="Invented fasting instruction",
            ),
        )
        assert response.status_code == 422
        assert "uploaded row" in response.json()["detail"]
        with store[1]() as db:
            saved = db.get(BridgeIntakeRecord, first["id"])
            assert saved.status == "REVIEW"
            assert saved.reviewed_at is None
    finally:
        client.__exit__(None, None, None)


def test_bridge_review_then_approve_imports_previously_blocked_row(store):
    client = bridge_client(store, SpecialtyReviewAnalyzer())
    try:
        batch = upload_csv(client).json()
        first = batch["records"][0]
        assert [row["status"] for row in batch["records"]] == ["REVIEW", "READY"]
        reviewed = client.post(
            f"/api/bridge/batches/{batch['id']}/records/{first['id']}/review",
            headers=mutation_headers(client),
            json=_review_payload(first, specialty="antenatal"),
        ).json()
        assert [row["status"] for row in reviewed["records"]] == ["READY", "READY"]
        approved = client.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["cases_created"] == 2
        with store[1]() as db:
            cases = list(db.scalars(select(FollowupCase)))
            assert len(cases) == 2
            assert {case.specialty for case in cases} == {"antenatal", "general"}
    finally:
        client.__exit__(None, None, None)


def test_bridge_approved_batch_cannot_be_edited(store):
    client = bridge_client(store, FakeBridgeAnalyzer())
    try:
        batch = upload_csv(client).json()
        first = batch["records"][0]
        approved = client.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        )
        assert approved.status_code == 200
        response = client.post(
            f"/api/bridge/batches/{batch['id']}/records/{first['id']}/review",
            headers=mutation_headers(client),
            json=_review_payload(first, specialty="antenatal"),
        )
        assert response.status_code == 409
    finally:
        client.__exit__(None, None, None)


def test_partial_import_remaining_row_can_be_reviewed_and_approved(store):
    client = bridge_client(store, SpecialtyReviewAnalyzer())
    try:
        batch = upload_csv(client).json()
        pending, ready = batch["records"]
        path = f"/api/bridge/batches/{batch['id']}"
        first = client.post(
            path + "/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        )
        assert first.status_code == 200
        assert [r["status"] for r in first.json()["records"]] == ["REVIEW", "IMPORTED"]
        imported = first.json()["records"][1]
        locked = client.post(
            path + f"/records/{ready['id']}/review",
            headers=mutation_headers(client),
            json=_review_payload(ready, specialty="dental"),
        )
        assert locked.status_code == 409
        reviewed = client.post(
            path + f"/records/{pending['id']}/review",
            headers=mutation_headers(client),
            json=_review_payload(pending, specialty="antenatal"),
        )
        assert reviewed.status_code == 200, reviewed.text
        assert [r["status"] for r in reviewed.json()["records"]] == ["READY", "IMPORTED"]
        second = client.post(
            path + "/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        )
        assert second.status_code == 200, second.text
        assert second.json()["imported_records"] == 1
        assert second.json()["records"][1] == imported
        assert all(r["status"] == "IMPORTED" for r in second.json()["records"])
        with store[1]() as db:
            assert len(list(db.scalars(select(FollowupCase)))) == 2
        again = client.post(
            path + "/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        )
        assert again.status_code == 409
    finally:
        client.__exit__(None, None, None)
