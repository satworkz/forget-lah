import base64
import io
import zipfile
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from forget_lah.api import create_app
from forget_lah.bridge import (
    BridgeBatchAnalysis,
    BridgeRecordAnalysis,
    parse_upload,
)
from forget_lah.db import BridgeImportProfile, BridgeIntakeBatch, BridgeIntakeRecord, FollowupCase
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.settings import Settings


def mutation_headers(client):
    return {
        "Origin": "http://localhost:8080",
        "X-CSRF-Token": client.cookies.get("forget_lah_csrf"),
    }


class FakeBridgeAnalyzer:
    def __init__(self):
        self.calls = []

    def analyse(self, rows, *, previous_mapping=None, staff_instruction=None):
        self.calls.append((previous_mapping, staff_instruction, rows))
        tomorrow = (datetime.now(UTC) + timedelta(days=1)).astimezone().replace(microsecond=0)
        yesterday = (datetime.now(UTC) - timedelta(days=1)).astimezone().replace(microsecond=0)
        records = []
        for index, row in enumerate(rows):
            text = " | ".join(row["cells"].values())
            name = "Mrs Semantic One" if "Semantic One" in text else "Mr Semantic Two"
            phone = "+6591111111" if "Semantic One" in text else "+6592222222"
            status = "scheduled" if index == 0 else "no_show"
            records.append(
                BridgeRecordAnalysis(
                    row_number=row["row_number"],
                    external_ref=None,
                    patient_name=name,
                    phone=phone,
                    appointment_at=(tomorrow if index == 0 else yesterday).isoformat(),
                    due_at=None,
                    record_type="appointment",
                    source_status=status,
                    specialty="general",
                    doctor_notes=(
                        "Bring the referral letter." if "referral" in text.casefold() else None
                    ),
                    preferred_language="en",
                    confidence=94,
                    evidence=[
                        {"field": "patient_name", "quote": name},
                        {"field": "phone", "quote": phone},
                        {
                            "field": "appointment_at",
                            "quote": row["cells"]["Next thing"],
                        },
                        *(
                            [{"field": "doctor_notes", "quote": "Bring the referral letter."}]
                            if "referral" in text.casefold()
                            else []
                        ),
                    ],
                    issues=[],
                )
            )
        return BridgeBatchAnalysis(
            purpose="MIXED",
            confidence=93,
            mapping=[
                {
                    "canonical_field": "patient_name",
                    "source_columns": ["Who / Contact"],
                    "confidence": 96,
                    "rationale": "Names and mobile numbers are combined in this field.",
                },
                {
                    "canonical_field": "appointment_at",
                    "source_columns": ["Next thing"],
                    "confidence": 91,
                    "rationale": "Values describe visit timing.",
                },
                {
                    "canonical_field": "doctor_notes",
                    "source_columns": ["Free text"],
                    "confidence": 90,
                    "rationale": "Contains follow-up instructions.",
                },
            ],
            warnings=[],
            records=records,
        )


def bridge_client(store, analyzer):
    engine, _ = store
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        public_origin="http://localhost:8080",
        agent_model_mode="mock",
    )
    client = TestClient(
        create_app(settings, engine, bridge_analyzer=analyzer),
        base_url="http://localhost:8080",
    )
    client.__enter__()
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:8080"},
        json={
            "email": "staff@forget-lah.example",
            "password": "unit-test-only-not-a-live-credential",
        },
    )
    assert response.status_code == 200
    return client


def upload_csv(client):
    data = (
        b"Who / Contact,Next thing,Free text\n"
        b'"Mrs Semantic One / +6591111111","tomorrow morning","Bring the referral letter."\n'
        b'"Mr Semantic Two / +6592222222","missed yesterday",""\n'
    )
    return client.post(
        "/api/bridge/analyse",
        headers=mutation_headers(client),
        json={
            "filename": "whatever-the-clinic-exported.csv",
            "content_base64": base64.b64encode(data).decode(),
        },
    )


def test_bridge_analyse_preview_then_approve_creates_managed_followups(store):
    analyzer = FakeBridgeAnalyzer()
    client = bridge_client(store, analyzer)
    try:
        response = upload_csv(client)
        assert response.status_code == 200, response.text
        batch = response.json()
        assert batch["purpose"] == "MIXED"
        assert batch["confidence"] == 93
        assert [row["status"] for row in batch["records"]] == ["READY", "READY"]
        assert batch["records"][0]["normalized"]["specialty"] == "general"
        with store[1]() as db:
            assert db.scalar(select(func.count()).select_from(FollowupCase)) == 0
            assert db.scalar(select(func.count()).select_from(BridgeIntakeBatch)) == 1
            assert db.scalar(select(func.count()).select_from(BridgeIntakeRecord)) == 2

        approved = client.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        )
        assert approved.status_code == 200, approved.text
        result = approved.json()
        assert result["status"] == "APPROVED"
        assert result["cases_created"] == 2
        with store[1]() as db:
            cases = list(db.scalars(select(FollowupCase).order_by(FollowupCase.created_at)))
            assert len(cases) == 2
            assert all(case.source_episode_ref.startswith("bridge:") for case in cases)
            assert (
                db.scalar(
                    select(BridgeIntakeRecord).where(
                        BridgeIntakeRecord.source_episode_ref == cases[0].source_episode_ref
                    )
                )
                is not None
            )
            binding = {
                "clinic_id": cases[0].clinic_id,
                "patient_id": cases[0].patient_id,
                "source_episode_ref": cases[0].source_episode_ref,
            }

        tools = ClinicTools("http://must-not-be-used", factory=store[1])
        context = tools.execute("read_followup_context", binding)
        assert context.status == "succeeded"
        assert context.data["source_kind"] == "bridge_upload"
        assert context.data["record_owner"] == "forget_lah"
        assert context.data["can_simulate_confirmation"] is True
        assert context.data["can_write_appointments"] is False
        instructions = tools.execute("get_approved_instructions", binding)
        assert instructions.status == "succeeded"
        assert instructions.data["instructions"][0]["approved_text"] == "Bring the referral letter."
        write = tools.confirm(binding, {"operation_id": "x", "run_id": "y"})
        assert write.status == "failed" and write.error_code == "SOURCE_INVALID"
    finally:
        client.__exit__(None, None, None)


def test_bridge_staff_can_correct_mapping_in_plain_language_and_profile_is_remembered(store):
    analyzer = FakeBridgeAnalyzer()
    client = bridge_client(store, analyzer)
    try:
        first = upload_csv(client).json()
        revised = client.post(
            f"/api/bridge/batches/{first['id']}/revise",
            headers=mutation_headers(client),
            json={
                "instruction": "Phone is inside Who / Contact. Free text is the doctor instruction."
            },
        )
        assert revised.status_code == 200
        assert revised.json()["analysis_version"] == 2
        assert analyzer.calls[-1][1].startswith("Phone is inside")
        approved = client.post(
            f"/api/bridge/batches/{first['id']}/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        )
        assert approved.status_code == 200
        with store[1]() as db:
            profile = db.scalar(select(BridgeImportProfile))
            assert profile and profile.mapping
        second = upload_csv(client)
        assert second.status_code == 200
        assert analyzer.calls[-1][0]
    finally:
        client.__exit__(None, None, None)


def test_bridge_rejects_ungrounded_doctor_note_and_keeps_row_for_review(store):
    class HallucinatingAnalyzer(FakeBridgeAnalyzer):
        def analyse(self, rows, **kwargs):
            analysis = super().analyse(rows, **kwargs)
            first_payload = analysis.records[0].model_dump()
            first_payload["doctor_notes"] = "Invented instruction not present in the upload."
            first_payload["evidence"] = [
                *first_payload["evidence"],
                {
                    "field": "doctor_notes",
                    "quote": "Invented instruction not present in the upload.",
                },
            ]
            first = BridgeRecordAnalysis.model_validate(first_payload)
            return analysis.model_copy(update={"records": [first, *analysis.records[1:]]})

    client = bridge_client(store, HallucinatingAnalyzer())
    try:
        batch = upload_csv(client).json()
        first = batch["records"][0]
        assert first["status"] == "REVIEW"
        assert first["normalized"]["doctor_notes"] is None
        assert "Doctor notes were not copied from this row" in first["issues"]
    finally:
        client.__exit__(None, None, None)


def test_bridge_csv_parser_does_not_require_traditional_column_names():
    body = b"Alpha,Beta,Gamma\nAlice,+6591234567,2026-09-22 10:00\n"
    kind, rows = parse_upload("clinic-export.csv", body)
    assert kind == "csv"
    assert rows == [
        {
            "row_number": 2,
            "cells": {"Alpha": "Alice", "Beta": "+6591234567", "Gamma": "2026-09-22 10:00"},
        }
    ]


def _minimal_xlsx(matrix):
    shared = []
    index = {}
    for row in matrix:
        for cell in row:
            if cell not in index:
                index[cell] = len(shared)
                shared.append(cell)
    strings = "".join(f"<si><t>{escape(value)}</t></si>" for value in shared)
    rows = []
    for r, row in enumerate(matrix, 1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            cells.append(f'<c r="{ref}" t="s"><v>{index[value]}</v></c>')
        rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{strings}</sst>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(rows)}</sheetData></worksheet>",
        )
    return stream.getvalue()


def test_bridge_reads_first_xlsx_sheet_without_excel_dependency():
    data = _minimal_xlsx([["Patient whatever", "Next"], ["Asha", "tomorrow"]])
    kind, rows = parse_upload("legacy.xlsx", data)
    assert kind == "xlsx"
    assert rows[0]["cells"] == {"Patient whatever": "Asha", "Next": "tomorrow"}


def test_bridge_anthropic_schemas_avoid_unsupported_array_bounds():
    from forget_lah.bridge import _profile_schema, _records_schema

    def contains(value, key):
        if isinstance(value, dict):
            return key in value or any(contains(item, key) for item in value.values())
        if isinstance(value, list):
            return any(contains(item, key) for item in value)
        return False

    for schema in (_profile_schema(), _records_schema()):
        assert not contains(schema, "maxItems")
        assert not contains(schema, "minItems")


def test_bridge_model_context_is_bounded_without_mutating_raw_rows():
    from forget_lah.bridge import _rows_for_model

    raw = [{"row_number": 2, "cells": {f"C{i}": "x" * 1000 for i in range(20)}}]
    compact = _rows_for_model(raw)
    assert sum(len(value) for value in compact[0]["cells"].values()) <= 1800
    assert len(raw[0]["cells"]["C0"]) == 1000
