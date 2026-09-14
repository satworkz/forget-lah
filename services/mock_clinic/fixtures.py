from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from forget_lah.source import DEMO_CLINIC_ID


def candidates():
    # Stable episode IDs prevent duplicate cases across polls. Relative dates keep setup usable.
    now = datetime.now(UTC).replace(hour=2, minute=0, second=0, microsecond=0)
    return [
        {
            "patient_id": "20000000-0000-4000-8000-000000000001",
            "display_alias": "Mr Lim (demo)",
            "source_episode_ref": "DEMO-DENTAL-RECALL-01",
            "specialty": "dental",
            "record_type": "recall",
            "source_status": "due",
            "has_future_booking": False,
            "due_at": (now - timedelta(days=14)).isoformat(),
        },
        {
            "patient_id": "20000000-0000-4000-8000-000000000002",
            "display_alias": "Alex (demo)",
            "source_episode_ref": "DEMO-MYOPIA-VISIT-01",
            "specialty": "myopia",
            "record_type": "appointment",
            "source_status": "scheduled",
            "scheduled_at": (now + timedelta(days=3)).isoformat(),
        },
        {
            "patient_id": "20000000-0000-4000-8000-000000000003",
            "display_alias": "Priya (demo)",
            "source_episode_ref": "DEMO-ANTENATAL-VISIT-01",
            "specialty": "antenatal",
            "record_type": "appointment",
            "source_status": "no_show",
            "scheduled_at": (now - timedelta(days=1)).isoformat(),
        },
    ]


def followup_context(episode: str):
    row = next((item for item in candidates() if item["source_episode_ref"] == episode), None)
    if row is None:
        raise HTTPException(404, "Synthetic episode not found")
    # Administrative demo text only; not clinically validated or sent to a patient.
    notes = {
        "dental": "Demo clinic note: bring your appointment confirmation.",
        "myopia": "Demo clinic note: bring your existing spectacles if you have them.",
        "antenatal": "Demo clinic note: bring your maternity appointment booklet if you have one.",
    }
    return {
        "clinic_id": DEMO_CLINIC_ID,
        "patient_id": row["patient_id"],
        "source_episode_ref": episode,
        "source_version": "synthetic-v1",
        "synthetic": True,
        "context": {
            "specialty": row["specialty"],
            "source_status": row["source_status"],
            "scheduled_at": row.get("scheduled_at"),
            "due_at": row.get("due_at"),
            "can_contact_patient": False,
            "can_write_appointments": False,
        },
        "instructions": [
            {
                "instruction_id": f"DEMO-{row['specialty'].upper()}-NOTE",
                "version": "1",
                "locale": "en-SG",
                "approved_text": notes[row["specialty"]],
                "synthetic": True,
            }
        ],
        "prerequisites": ["NOT_APPLICABLE"],
    }
