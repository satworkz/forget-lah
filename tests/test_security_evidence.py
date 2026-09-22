import io
import zipfile

import pytest
from sqlalchemy import select
from test_bridge import FakeBridgeAnalyzer, bridge_client, upload_csv
from test_security import mutation_headers, set_role
from test_simulator import new_slot

from forget_lah.bridge import ReviewRecordInput
from forget_lah.db import FollowupCase, SecurityEvent
from forget_lah.runtime.provider import prompt_for


def test_empty_xlsx_values_remain_literal_and_long_coordinates_are_rejected():
    from test_bridge import _minimal_xlsx

    from forget_lah.bridge import parse_upload

    original = _minimal_xlsx([["Header"], ["Value"], ["Keep"]])
    for long_coordinate in (False, True):
        output = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(original)) as source,
            zipfile.ZipFile(output, "w") as target,
        ):
            for part in source.infolist():
                data = source.read(part.filename)
                if "worksheets/" in part.filename:
                    data = data.replace(b"<v>1</v>", b"<v/>")
                    if long_coordinate:
                        data = data.replace(b"A2", b"A" * 1000 + b"2")
                target.writestr(part.filename, data)
        if long_coordinate:
            with pytest.raises(ValueError, match="reference"):
                parse_upload("cells.xlsx", output.getvalue())
        else:
            _, rows = parse_upload("cells.xlsx", output.getvalue())
            assert rows[0]["cells"]["Header"] == "Keep"


def test_bridge_review_history_is_retained_and_case_audit_excludes_sibling_patient(store):
    with bridge_client(store, FakeBridgeAnalyzer()) as client:
        batch = upload_csv(client).json()
        first, sibling = batch["records"]
        for record, languages in [(first, ["ms", "ta"]), (sibling, ["zh"])]:
            for language in languages:
                body = {
                    k: v
                    for k, v in record["normalized"].items()
                    if k in ReviewRecordInput.model_fields
                }
                body["preferred_language"] = language
                body["review_note"] = "staff verified"
                response = client.post(
                    f"/api/bridge/batches/{batch['id']}/records/{record['id']}/review",
                    json=body,
                    headers=mutation_headers(client),
                )
                assert response.status_code == 200, response.text
        assert (
            client.post(
                f"/api/bridge/batches/{batch['id']}/approve",
                json={"include_review_rows": False},
                headers=mutation_headers(client),
            ).status_code
            == 200
        )
        with store[1]() as db:
            changes = list(
                db.scalars(select(SecurityEvent).where(SecurityEvent.action == "bridge_review"))
            )
            assert len(changes) == 3
            first_changes = [
                e.details["changes"]["preferred_language"]
                for e in changes
                if e.details["record_id"] == first["id"]
            ]
            assert first_changes == [{"from": "en", "to": "ms"}, {"from": "ms", "to": "ta"}]
            cases = list(db.scalars(select(FollowupCase.id)))
        seen_reviews = 0
        for case_id in cases:
            audit = client.get(f"/api/cases/{case_id}/audit").json()
            reviews = [e for e in audit["events"] if e["action"] == "bridge_review"]
            assert len({e["evidence"]["record_id"] for e in reviews}) == 1
            seen_reviews += len(reviews)
        assert seen_reviews == 3


@pytest.mark.parametrize("role", ["viewer", "auditor", "unknown"])
def test_simulator_slot_management_requires_write_role(store, signed_client, role):
    set_role(store, role)
    response = signed_client.post(
        "/api/simulator/slots", headers=mutation_headers(signed_client), json=new_slot()
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["coordinator", "engagement", "preparation"])
def test_prompt_contains_only_supplied_scoped_observation(role):
    from forget_lah.security import model_context

    observation = model_context(
        {
            "role": role,
            "request_id": "step",
            "expected_case_version": 1,
            "tools": [
                {
                    "result": {
                        "patient_id": "IDENTITY_SENTINEL",
                        "clinic_id": "CLINIC_SENTINEL",
                        "available_slots": [{"id": "SLOT_SENTINEL"}],
                        "evidence": "approved note",
                    }
                }
            ],
        },
        role,
    )
    prompt = prompt_for(observation, False)
    assert "IDENTITY_SENTINEL" not in prompt and "CLINIC_SENTINEL" not in prompt
    assert ("SLOT_SENTINEL" in prompt) == (role == "engagement")
    assert "approved note" in prompt
